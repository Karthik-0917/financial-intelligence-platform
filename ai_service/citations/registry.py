import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from core.schemas import Synthesis

REQUEST_NAMESPACE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_RECORDS = 200


@contextmanager
def _connection(path):
    connection = None

    try:
        connection = sqlite3.connect(path, timeout=3)
        with connection:
            yield connection
    except sqlite3.Error:
        raise OSError("Evidence storage unavailable or inconsistent") from None
    finally:
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error:
                pass


class Registry:
    """Request-namespaced evidence persisted for subsequent lookup."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        with _connection(self.path) as database:
            database.execute(
                "CREATE TABLE IF NOT EXISTS evidence ("
                "id TEXT PRIMARY KEY, "
                "body TEXT NOT NULL, "
                "created TEXT DEFAULT CURRENT_TIMESTAMP"
                ")"
            )

    def register(self, request_id, records):
        if not isinstance(request_id, str) or not REQUEST_NAMESPACE.fullmatch(
            request_id
        ):
            raise ValueError("Invalid application evidence namespace")

        if not isinstance(records, list) or not records or len(records) > MAX_RECORDS:
            raise ValueError("Invalid evidence record count")

        prepared = []
        result = {}

        for position, record in enumerate(records, 1):
            if (
                not isinstance(record, dict)
                or not isinstance(record.get("text"), str)
                or not record["text"].strip()
            ):
                raise ValueError("Evidence record lacks source text")

            identifier = f"EVIDENCE_{request_id}_{position:03}"
            body = {**record, "evidence_id": identifier}

            try:
                serialized = json.dumps(
                    body,
                    ensure_ascii=False,
                    allow_nan=False,
                )
                detached = json.loads(serialized)
            except (TypeError, ValueError):
                raise ValueError(
                    "Evidence record is not valid finite JSON data"
                ) from None

            prepared.append((identifier, serialized))
            result[identifier] = detached

        with _connection(self.path) as database:
            database.executemany(
                "INSERT INTO evidence(id, body) VALUES (?, ?)",
                prepared,
            )

        return result

    def get(self, evidence_id):
        if (
            not isinstance(evidence_id, str)
            or not evidence_id
            or len(evidence_id) > 100
        ):
            raise ValueError("Invalid evidence identifier")

        with _connection(self.path) as database:
            row = database.execute(
                "SELECT body FROM evidence WHERE id = ?",
                (evidence_id,),
            ).fetchone()

        if row is None:
            return None

        try:
            record = json.loads(row[0])
        except (TypeError, ValueError):
            raise OSError("Stored evidence is malformed") from None

        if (
            not isinstance(record, dict)
            or record.get("evidence_id") != evidence_id
            or not isinstance(record.get("text"), str)
            or not record["text"].strip()
        ):
            raise OSError("Stored evidence identity or text is invalid")

        return record


def validate_citations(synthesis: Synthesis, registry: dict):
    if not synthesis.claims:
        raise ValueError("Generated response contains no claims")

    identifiers = []

    for claim in synthesis.claims:
        if not claim.text.strip():
            raise ValueError("Generated claim has no text")

        if not claim.citation_ids:
            raise ValueError("Uncited claim")

        for identifier in claim.citation_ids:
            if identifier not in registry:
                raise ValueError("Unknown or out-of-context citation ID")

            record = registry[identifier]

            if (
                not isinstance(record, dict)
                or not isinstance(record.get("text"), str)
                or not record["text"].strip()
            ):
                raise ValueError("Citation has no evidence text")

            if identifier not in identifiers:
                identifiers.append(identifier)

    return identifiers

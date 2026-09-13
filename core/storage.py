import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def read_json(path: Path, default=None):
    path = Path(path)

    if not path.exists():
        return default

    return json.loads(path.read_text(encoding="utf-8"))


def write_bytes(path: Path, content: bytes) -> None:
    """Write bytes through a temporary file in the destination directory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)

    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path: Path, value: Any) -> None:
    """Serialize completely before replacing the destination file."""
    content = json.dumps(
        value,
        indent=2,
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")

    write_bytes(path, content)


def digest(value: Any) -> str:
    """Legacy canonical-JSON digest used by existing artifact versions.

    Do not use this function to label a downloaded file's raw-byte checksum.
    """
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()


def sha256_bytes(content: bytes) -> str:
    """SHA-256 of the exact supplied bytes."""
    return hashlib.sha256(content).hexdigest()

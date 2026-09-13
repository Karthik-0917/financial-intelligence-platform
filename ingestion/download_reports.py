"""SEC-only offline acquisition with verified caching and bounded retries.

Never instantiate this client in a runtime research request handler.

The cache stores exact response bytes and a separate integrity record.
A cache entry is reusable only when both files agree. Legacy entries
without integrity metadata are downloaded again rather than silently
treated as verified.

Checksums detect accidental corruption, not malicious changes by an
attacker who can write both the cache entry and its metadata.
"""

import re
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx

from core.storage import digest, read_json, sha256_bytes, write_bytes, write_json

ALLOWED_HOSTS = {"www.sec.gov", "data.sec.gov"}
TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}

MAX_ATTEMPTS = 4
MIN_REQUEST_INTERVAL_SECONDS = 0.25
MAX_RETRY_DELAY_SECONDS = 60.0
CACHE_FORMAT_VERSION = 1


class SECDownloadError(RuntimeError):
    """Acquisition failure with a safe, bounded diagnostic message."""


def _validate_url(url: str) -> None:
    try:
        parsed = urlsplit(url)

        if (
            parsed.scheme != "https"
            or parsed.hostname not in ALLOWED_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith("/")
        ):
            raise ValueError("Invalid SEC URL")
    except (TypeError, ValueError):
        raise SECDownloadError(
            "Only official SEC HTTPS URLs without credentials, "
            "queries, fragments, or nonstandard ports are allowed"
        ) from None


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    """Respect Retry-After within the client's documented delay bound."""
    fallback = min(
        MAX_RETRY_DELAY_SECONDS,
        float(2 ** (attempt + 1)),
    )

    if response is None:
        return fallback

    value = response.headers.get("Retry-After", "").strip()

    if not value:
        return fallback

    if re.fullmatch(r"\d+", value):
        return min(
            MAX_RETRY_DELAY_SECONDS,
            max(fallback, float(value)),
        )

    try:
        retry_at = parsedate_to_datetime(value)

        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)

        seconds = (retry_at - datetime.now(UTC)).total_seconds()
    except (TypeError, ValueError, OverflowError):
        return fallback

    return min(
        MAX_RETRY_DELAY_SECONDS,
        max(fallback, seconds),
    )


class SECClient:
    def __init__(self, settings):
        email = settings.sec_contact_email.strip()
        user_agent = settings.sec_user_agent.strip()

        if (
            not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)
            or email not in user_agent
            or "\r" in user_agent
            or "\n" in user_agent
        ):
            raise ValueError(
                "Set SEC_CONTACT_EMAIL and a descriptive SEC_USER_AGENT "
                "containing that email; configure real contact details locally"
            )

        self.cache = settings.data_dir / "raw"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.client = httpx.Client(
            headers={
                "User-Agent": user_agent,
                "Accept-Encoding": "gzip, deflate",
            },
            timeout=45,
            follow_redirects=False,
        )
        self.last: float | None = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def _cached(self, url: str) -> bytes | None:
        path = self.cache / digest(url)
        metadata_path = self.cache / f"{digest(url)}.meta.json"

        try:
            metadata = read_json(metadata_path)

            if (
                not isinstance(metadata, dict)
                or metadata.get("format_version") != CACHE_FORMAT_VERSION
                or metadata.get("source_url") != url
            ):
                return None

            content = path.read_bytes()

            if (
                not content
                or metadata.get("byte_count") != len(content)
                or metadata.get("content_sha256") != sha256_bytes(content)
            ):
                return None

            return content
        except (OSError, ValueError, TypeError):
            return None

    def _store(self, url: str, response: httpx.Response) -> bytes:
        content = response.content

        if not content:
            raise SECDownloadError("SEC returned an empty response body")

        path = self.cache / digest(url)
        metadata_path = self.cache / f"{digest(url)}.meta.json"

        # These are individually atomic, not a two-file transaction.
        # If publication stops between the writes, the next read rejects
        # any content/metadata mismatch and downloads the source again.
        write_bytes(path, content)
        write_json(
            metadata_path,
            {
                "format_version": CACHE_FORMAT_VERSION,
                "source_url": url,
                "retrieved_at": datetime.now(UTC).isoformat(),
                "byte_count": len(content),
                "content_sha256": sha256_bytes(content),
                "content_type": response.headers.get("Content-Type"),
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
            },
        )
        return content

    def _throttle(self) -> None:
        if self.last is not None:
            wait = MIN_REQUEST_INTERVAL_SECONDS - (time.monotonic() - self.last)

            if wait > 0:
                time.sleep(wait)

        self.last = time.monotonic()

    def get(self, url: str, *, refresh: bool = False) -> bytes:
        """Return verified cached bytes or perform a bounded SEC request.

        refresh=True bypasses a valid cache entry. It is intended for
        explicitly refreshing mutable submissions/Company Facts metadata
        in the offline pipeline, not for runtime network access.
        """
        _validate_url(url)

        if not refresh:
            cached = self._cached(url)

            if cached is not None:
                return cached

        for attempt in range(MAX_ATTEMPTS):
            self._throttle()

            try:
                response = self.client.get(url)
            except httpx.TransportError:
                if attempt + 1 == MAX_ATTEMPTS:
                    raise SECDownloadError(
                        "SEC transport failed after bounded retries"
                    ) from None

                time.sleep(_retry_delay(None, attempt))
                continue

            if response.status_code in TRANSIENT_STATUS_CODES:
                if attempt + 1 == MAX_ATTEMPTS:
                    raise SECDownloadError(
                        "SEC remained unavailable after bounded retries "
                        f"(HTTP {response.status_code})"
                    )

                time.sleep(_retry_delay(response, attempt))
                continue

            if response.status_code != 200:
                raise SECDownloadError(
                    "SEC request rejected without retry "
                    f"(HTTP {response.status_code}); inspect offline "
                    "configuration and official source metadata"
                )

            return self._store(url, response)

        raise SECDownloadError("SEC acquisition exhausted its attempt budget")

    def close(self):
        self.client.close()

"""SEC transport tests using synthetic bytes and HTTPX MockTransport.

The client never contacts SEC in these tests. Contact details below are
fictional test fixtures, not suggested production configuration.
"""

from types import SimpleNamespace

import httpx
import pytest

from core.storage import digest, read_json, sha256_bytes
from ingestion.download_reports import (
    MAX_ATTEMPTS,
    SECClient,
    SECDownloadError,
    _retry_delay,
)

URL = "https://data.sec.gov/submissions/CIK0000320193.json"


@pytest.fixture
def client(tmp_path, monkeypatch):
    settings = SimpleNamespace(
        data_dir=tmp_path,
        sec_contact_email="fixture@example.invalid",
        sec_user_agent="Offline unit test fixture@example.invalid",
    )
    instance = SECClient(settings)

    monkeypatch.setattr(
        "ingestion.download_reports.time.sleep",
        lambda seconds: None,
    )

    yield instance

    instance.close()


def install_transport(client, handler):
    client.client.close()
    client.client = httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
    )


def test_success_persists_verified_cache(client):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            content=b'{"synthetic": true}',
            headers={"Content-Type": "application/json"},
        )

    install_transport(client, handler)

    first = client.get(URL)
    second = client.get(URL)

    assert first == second == b'{"synthetic": true}'
    assert len(calls) == 1

    metadata = read_json(client.cache / f"{digest(URL)}.meta.json")

    assert metadata["source_url"] == URL
    assert metadata["byte_count"] == len(first)
    assert metadata["content_sha256"] == sha256_bytes(first)
    assert metadata["retrieved_at"]


def test_corrupt_cached_bytes_are_downloaded_again(client):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=b"synthetic source")

    install_transport(client, handler)

    client.get(URL)
    (client.cache / digest(URL)).write_bytes(b"interrupted")

    assert client.get(URL) == b"synthetic source"
    assert len(calls) == 2


def test_legacy_cache_without_metadata_is_not_trusted(client):
    (client.cache / digest(URL)).write_bytes(b"legacy unverified source")

    install_transport(
        client,
        lambda request: httpx.Response(200, content=b"verified response"),
    )

    assert client.get(URL) == b"verified response"


def test_refresh_bypasses_valid_cache(client):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            content=f"synthetic revision {len(calls)}".encode(),
        )

    install_transport(client, handler)

    assert client.get(URL) == b"synthetic revision 1"
    assert client.get(URL, refresh=True) == b"synthetic revision 2"
    assert len(calls) == 2


@pytest.mark.parametrize(
    "url",
    [
        "http://data.sec.gov/submissions/example.json",
        "https://example.invalid/source",
        "https://data.sec.gov.example.invalid/source",
        "https://user:password@data.sec.gov/source",
        "https://data.sec.gov:8443/source",
        "https://data.sec.gov:invalid/source",
        "https://data.sec.gov/source?token=example",
        "https://data.sec.gov/source#fragment",
    ],
)
def test_invalid_urls_fail_before_transport(client, url):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=b"unexpected")

    install_transport(client, handler)

    with pytest.raises(SECDownloadError):
        client.get(url)

    assert calls == []


@pytest.mark.parametrize("status_code", [301, 302, 400, 401, 403, 404])
def test_permanent_errors_and_redirects_do_not_retry(client, status_code):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status_code,
            headers={"Location": "https://example.invalid/redirect"},
            content=b"response body must not appear in public error",
        )

    install_transport(client, handler)

    with pytest.raises(SECDownloadError) as error:
        client.get(URL)

    assert len(calls) == 1
    assert f"HTTP {status_code}" in str(error.value)
    assert "response body" not in str(error.value)
    assert not (client.cache / digest(URL)).exists()


def test_transient_failure_can_recover(client):
    calls = []

    def handler(request):
        calls.append(request)

        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})

        return httpx.Response(200, content=b"synthetic recovered response")

    install_transport(client, handler)

    assert client.get(URL) == b"synthetic recovered response"
    assert len(calls) == 2


def test_transient_retries_are_bounded(client):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503)

    install_transport(client, handler)

    with pytest.raises(SECDownloadError):
        client.get(URL)

    assert len(calls) == MAX_ATTEMPTS


def test_transport_retries_are_bounded(client):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("synthetic private diagnostic", request=request)

    install_transport(client, handler)

    with pytest.raises(SECDownloadError) as error:
        client.get(URL)

    assert len(calls) == MAX_ATTEMPTS
    assert "private diagnostic" not in str(error.value)


def test_empty_response_is_not_cached(client):
    install_transport(
        client,
        lambda request: httpx.Response(200, content=b""),
    )

    with pytest.raises(SECDownloadError):
        client.get(URL)

    assert not (client.cache / digest(URL)).exists()


def test_retry_after_delay_is_capped():
    response = httpx.Response(429, headers={"Retry-After": "3600"})

    assert _retry_delay(response, 0) == 60.0


def test_invalid_retry_after_uses_backoff():
    response = httpx.Response(503, headers={"Retry-After": "not-a-date"})

    assert _retry_delay(response, 0) == 2.0

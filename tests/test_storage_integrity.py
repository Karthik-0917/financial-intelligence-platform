"""Offline storage tests. No external services or model artifacts."""

import hashlib
import json

import pytest

from core.storage import (
    digest,
    read_json,
    sha256_bytes,
    write_bytes,
    write_json,
)


def test_json_round_trip_uses_utf8(tmp_path):
    path = tmp_path / "nested" / "record.json"
    value = {
        "label": "Fiscal-year comparison — résumé",
        "values": ["₹", "£", "€"],
    }

    write_json(path, value)

    assert read_json(path) == value
    assert "résumé" in path.read_text(encoding="utf-8")


def test_missing_json_returns_supplied_default(tmp_path):
    default = {"facts": []}

    assert read_json(tmp_path / "missing.json", default) is default


def test_invalid_json_is_not_replaced_with_default(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text("{invalid", encoding="utf-8")

    with pytest.raises(ValueError):
        read_json(path, {"facts": []})


def test_serialization_failure_preserves_existing_file(tmp_path):
    path = tmp_path / "record.json"
    write_json(path, {"version": "existing"})

    cyclic = []
    cyclic.append(cyclic)

    with pytest.raises(ValueError):
        write_json(path, cyclic)

    assert read_json(path) == {"version": "existing"}
    assert not list(tmp_path.glob("*.tmp"))


def test_atomic_byte_replacement(tmp_path):
    path = tmp_path / "nested" / "source.bin"

    write_bytes(path, b"original")
    write_bytes(path, b"replacement")

    assert path.read_bytes() == b"replacement"
    assert not list(path.parent.glob("*.tmp"))


def test_raw_sha256_hashes_exact_bytes():
    content = b"<html>synthetic fixture</html>"

    assert sha256_bytes(content) == hashlib.sha256(content).hexdigest()
    assert sha256_bytes(content) != digest(content.hex())


def test_existing_json_digest_contract_is_preserved():
    value = {"ticker": "AAPL", "years": [2022, 2023, 2024]}
    expected = hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode()
    ).hexdigest()

    assert digest(value) == expected

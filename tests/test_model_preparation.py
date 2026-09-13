"""Model-preparation tests with an injected downloader and synthetic paths."""

from pathlib import Path
from types import SimpleNamespace

from core.storage import read_json
from ingestion.prepare_models import prepare_models


def test_prepares_both_roles_without_claiming_inference(tmp_path):
    settings = SimpleNamespace(
        embedding_model="synthetic/embedding",
        reranker_model="synthetic/reranker",
    )
    calls = []

    def download(**kwargs):
        calls.append(kwargs)
        return str(
            Path(kwargs["cache_dir"])
            / kwargs["repo_id"].replace("/", "--")
            / "snapshots"
            / "synthetic-revision"
        )

    cache = tmp_path / "huggingface" / "hub"
    result = prepare_models(settings, cache, downloader=download)

    assert len(calls) == 2
    assert {call["repo_id"] for call in calls} == {
        "synthetic/embedding",
        "synthetic/reranker",
    }
    assert all(call["local_files_only"] is False for call in calls)
    assert result["status"] == "assets_prepared"
    assert all(
        model["inference_status"] == "not_executed" for model in result["models"]
    )

    persisted = read_json(cache.parent / "preparation.json")

    assert persisted == result

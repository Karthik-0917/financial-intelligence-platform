"""Explicit model-asset preparation for later local-only inference.

This command downloads Hugging Face model assets when executed locally.
It does not contact SEC, Groq, or Ollama and does not build an index.

Runtime services should use the same cache directory.
A download receipt is not a model inference or compatibility test.
"""

import argparse
from datetime import UTC, datetime
from pathlib import Path

from core.config import Settings
from core.storage import write_json

MODEL_FILE_PATTERNS = [
    "*.json",
    "*.txt",
    "*.model",
    "*.safetensors",
    "pytorch_model.bin",
]


def prepare_models(settings, cache_dir, *, downloader=None):
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    if downloader is None:
        from huggingface_hub import snapshot_download

        downloader = snapshot_download

    prepared = []

    for role, model in (
        ("embedding", settings.embedding_model),
        ("reranker", settings.reranker_model),
    ):
        snapshot = downloader(
            repo_id=model,
            cache_dir=str(cache_dir),
            allow_patterns=MODEL_FILE_PATTERNS,
            local_files_only=False,
        )
        snapshot_path = Path(snapshot)

        prepared.append(
            {
                "role": role,
                "model": model,
                "snapshot_directory": str(snapshot_path),
                "resolved_snapshot_name": snapshot_path.name,
                "download_status": "completed",
                "inference_status": "not_executed",
            }
        )

    receipt = {
        "status": "assets_prepared",
        "created_at": datetime.now(UTC).isoformat(),
        "cache_directory": str(cache_dir),
        "models": prepared,
        "scope": (
            "Model asset download receipt only. Model construction, "
            "embedding dimensions, reranker behavior, and query latency "
            "have not been tested by this command."
        ),
    }
    write_json(cache_dir.parent / "preparation.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cache-dir",
        default="models/huggingface/hub",
        help="Hugging Face hub cache directory shared with runtime services",
    )
    args = parser.parse_args()

    try:
        prepare_models(Settings(), Path(args.cache_dir))
    except ImportError:
        raise SystemExit(
            "Model preparation dependencies are unavailable. "
            "Install the project's ML extras locally first."
        ) from None


if __name__ == "__main__":
    main()

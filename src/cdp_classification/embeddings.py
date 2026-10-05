"""Shared local embedding-model registry and encoding utilities."""

from __future__ import annotations

import gzip
import hashlib
import inspect
import json
import platform
import re
import time
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
LEGACY_MODELS = ROOT / "data" / "models" / "cdp_encoder_competition"
MODEL_CACHE = ROOT / "data" / "models" / "cdp_action_taxonomy"

MODEL_SPECS = {
    "minilm": {
        "model_id": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "legacy_key": "minilm",
    },
    "e5_base": {
        "model_id": "intfloat/multilingual-e5-base",
        "legacy_key": "e5",
        "prompt": "query: ",
    },
    "bge_m3": {
        "model_id": "BAAI/bge-m3",
        "legacy_key": "bge_m3",
    },
    "qwen3_06b": {
        "model_id": "Qwen/Qwen3-Embedding-0.6B",
        "legacy_key": "qwen3",
        "prompt": "Instruct: Classify a corporate climate action.\nQuery: ",
    },
    "gte_multilingual": {
        "model_id": "Alibaba-NLP/gte-multilingual-base",
        "trust_remote_code": True,
    },
    "jina_v3": {
        "model_id": "jinaai/jina-embeddings-v3",
        "trust_remote_code": True,
        "task": "separation",
    },
    "e5_large_instruct": {
        "model_id": "intfloat/multilingual-e5-large-instruct",
        "prompt": "Instruct: Classify a corporate climate action.\nQuery: ",
    },
}
DEFAULT_MODELS = tuple(MODEL_SPECS)


def read_jsonl(path: Path) -> list[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def file_digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".pending")
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(path)


def clean_classification_text(text: str, company: str = "") -> str:
    result = text
    if company.strip():
        result = re.sub(re.escape(company.strip()), " ", result, flags=re.IGNORECASE)
    for pattern in (
        r"\bCDP\b",
        r"\bduring the reporting (?:year|period)\b",
        r"\bin the reporting (?:year|period)\b",
        r"\bplease (?:describe|explain|provide)\b",
        r"\bthis (?:question|response|disclosure)\b",
        r"https?://\S+",
    ):
        result = re.sub(pattern, " ", result, flags=re.IGNORECASE)
    result = re.sub(r"\s+", " ", result).strip(" -–—:;,.\n")
    return result or text.strip()


def _legacy_model_path(spec: dict) -> Path | None:
    key = spec.get("legacy_key")
    folder = LEGACY_MODELS / key if key else None
    if folder is None or not folder.exists():
        return None
    candidates = [path for path in folder.iterdir() if path.is_dir() and (path / "config.json").exists()]
    return candidates[0] if len(candidates) == 1 else None


def _resolve_model(key: str, spec: dict, offline: bool) -> tuple[Path, str]:
    legacy = _legacy_model_path(spec)
    if legacy is not None:
        return legacy, legacy.name
    cached_root = MODEL_CACHE / "huggingface" / ("models--" + spec["model_id"].replace("/", "--")) / "snapshots"
    cached = [path for path in cached_root.iterdir() if path.is_dir() and (path / "config.json").exists()] if cached_root.exists() else []
    if len(cached) == 1:
        return cached[0], cached[0].name
    from huggingface_hub import snapshot_download

    path = Path(snapshot_download(
        repo_id=spec["model_id"],
        local_dir=MODEL_CACHE / "snapshots" / key,
        local_dir_use_symlinks=False,
        local_files_only=offline,
    ))
    return path, path.name


def encode_model(
    key: str,
    records: list[dict],
    output: Path,
    *,
    batch_size: int,
    device: str,
    offline: bool,
) -> None:
    """Encode ``classification_text`` and reuse a valid cached matrix."""
    import torch
    from sentence_transformers import SentenceTransformer

    spec = MODEL_SPECS[key]
    folder = output / "encoders" / key
    folder.mkdir(parents=True, exist_ok=True)
    matrix_path = folder / "embeddings.npy"
    manifest_path = folder / "manifest.json"
    sample_hash = file_digest(output / "span_records.jsonl.gz")
    if manifest_path.exists() and matrix_path.exists():
        try:
            state = json.loads(manifest_path.read_text(encoding="utf-8"))
            matrix = np.load(matrix_path, allow_pickle=False)
            if state.get("sample_sha256") == sample_hash and len(matrix) == len(records) and np.isfinite(matrix).all():
                return
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            pass

    model_path, revision = _resolve_model(key, spec, offline)
    started = time.perf_counter()
    model = SentenceTransformer(
        str(model_path),
        device=device,
        local_files_only=offline,
        trust_remote_code=spec.get("trust_remote_code", False),
        model_kwargs={"torch_dtype": torch.float32} if device == "cpu" else {},
    )
    kwargs = {
        "batch_size": batch_size,
        "normalize_embeddings": True,
        "convert_to_numpy": True,
        "show_progress_bar": True,
    }
    task_applied = "none"
    if spec.get("task"):
        signature = inspect.signature(model.encode).parameters
        module_kwargs = getattr(model, "module_kwargs", None) or {}
        forwards_task = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.values()
        ) and any("task" in keywords for keywords in module_kwargs.values())
        if "task" in signature or forwards_task:
            kwargs["task"] = spec["task"]
            task_applied = spec["task"]
        elif "prompt_name" in signature and spec["task"] in getattr(model, "prompts", {}):
            kwargs["prompt_name"] = spec["task"]
            task_applied = "prompt_name:" + spec["task"]
        else:
            raise RuntimeError(f"The installed sentence-transformers version cannot apply the {spec['task']!r} task for {key}.")

    texts = [spec.get("prompt", "") + row["classification_text"] for row in records]
    vectors = model.encode(texts, **kwargs).astype("float32")
    if not np.isfinite(vectors).all() or not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-4):
        raise ValueError(f"{key} returned invalid or unnormalised vectors")
    np.save(matrix_path, vectors)
    write_json(manifest_path, {
        "key": key,
        "model_id": spec["model_id"],
        "resolved_revision": revision,
        "sample_sha256": sample_hash,
        "records": len(records),
        "dimension": vectors.shape[1],
        "prompt": spec.get("prompt", ""),
        "task": task_applied,
        "seconds": time.perf_counter() - started,
        "device": device,
        "python": platform.python_version(),
    })

"""Offline, resumable exact-text embedding and evidence-score cache."""

from __future__ import annotations

import os
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
if __name__ == "__main__":
    import torch  # Initialize the Windows inference DLLs before NumPy.

import gc
import gzip
import importlib.metadata
import json
import logging
import sqlite3
import time
import platform
from pathlib import Path

import numpy as np
from src.cdp_text_clustering.cdp_encoder_settings import MODEL_CACHE, MODELS, PREFIXES, DEFAULT_OUTPUT as REVISIONS
from src.cdp_text_clustering.cdp_field_chunking import aggregate_chunks, chunk_text, token_count, validate_codebook
from src.cdp_extraction.cdp_section_fields import OUTPUT, digest, file_digest, read_fields, write_json

LOGGER = logging.getLogger(__name__)
HERE = Path(__file__).resolve().parent


def record_environment(output: Path) -> dict:
    environment = {
        "python": platform.python_version(),
        "packages": {name: importlib.metadata.version(name) for name in (
            "torch", "transformers", "sentence-transformers", "numpy", "scipy",
            "scikit-learn", "pandas", "threadpoolctl",
        )},
        "inference": "CPU float32", "torch_threads": 6, "clustering_threads": 2,
    }
    path = output / "runtime_environment.json"
    if path.exists() and json.loads(path.read_text()) != environment:
        raise ValueError("Runtime packages changed; do not mix encoder caches across environments")
    if not path.exists():
        write_json(path, environment)
    return environment


def section_codebook() -> list[dict]:
    base = json.loads((HERE / "cdp_field_codebook.json").read_text(encoding="utf-8"))
    additions = json.loads((HERE / "cdp_section_codebook.json").read_text(encoding="utf-8"))
    for code in base:
        if code["code"] in {"supplier_engagement", "measurement_planning", "insufficient_information",
                            "general_environmental_effort"}:
            code["roles"] = [*code["roles"], "engagement"]
    result = base + additions
    validate_codebook(result)
    return result


class EncoderCache:
    def __init__(self, key: str, output: Path, *, max_tokens: int = 128, batch_size: int = 16):
        import torch
        from sentence_transformers import SentenceTransformer

        self.key, self.output, self.batch_size = key, output, batch_size
        self.max_tokens, self.prefix = max_tokens, PREFIXES[key]
        self.folder = output / "encoders" / key
        self.folder.mkdir(parents=True, exist_ok=True)
        record_environment(output)
        revision_path = output / f"{key}_revision.json"
        if not revision_path.exists():
            revision_path = REVISIONS / f"{key}_revision.json"
        revision = json.loads(revision_path.read_text())
        if revision["repository"] != MODELS[key]:
            raise ValueError("Pinned encoder repository mismatch")
        self.codebook = section_codebook()
        self.fingerprint = {
            "version": 1, "model": MODELS[key], "revision": revision["revision"],
            "max_tokens": max_tokens, "prefix": self.prefix, "dtype": "float32",
            "codebook_sha256": digest(json.dumps(self.codebook, sort_keys=True)),
        }
        manifest = self.folder / "cache_manifest.json"
        if manifest.exists() and json.loads(manifest.read_text()) != self.fingerprint:
            raise ValueError("Encoder cache settings changed; choose a new output")
        write_json(manifest, self.fingerprint)
        torch.set_num_threads(6)
        started = time.perf_counter()
        self.model = SentenceTransformer(
            str(MODEL_CACHE / key / revision["revision"]), device="cpu",
            local_files_only=True, trust_remote_code=False, model_kwargs={"torch_dtype": torch.float32},
        )
        self.model.max_seq_length = max_tokens
        if key == "qwen3":
            self.model.tokenizer.padding_side = "left"
        self.dimension = self.model.get_sentence_embedding_dimension()
        if not isinstance(self.dimension, int):
            raise ValueError("Missing encoder dimension")
        self.connection = sqlite3.connect(self.folder / "text_cache.sqlite3")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS texts (text_hash TEXT PRIMARY KEY, vector BLOB NOT NULL, "
            "prefix_vector BLOB, payload BLOB NOT NULL)")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS timing (id INTEGER PRIMARY KEY CHECK(id=1), seconds REAL NOT NULL, fields INTEGER NOT NULL)")
        self.connection.execute("INSERT OR IGNORE INTO timing VALUES (1,0,0)")
        self.connection.commit()
        descriptions = [self.prefix + code["definition"] for code in self.codebook]
        if any(token_count(self.model.tokenizer, code["definition"], self.prefix) > max_tokens
               for code in self.codebook):
            raise ValueError("Code definition exceeds common token budget")
        self.code_vectors = self._encode(descriptions)
        LOGGER.info("%s loaded in %.1fs; dimension=%s", key, time.perf_counter() - started, self.dimension)

    def _encode(self, inputs: list[str]) -> np.ndarray:
        result = self.model.encode(
            inputs, batch_size=self.batch_size, prompt="", normalize_embeddings=True,
            convert_to_numpy=True, show_progress_bar=False,
        ).astype("float32")
        if not np.isfinite(result).all() or not np.allclose(np.linalg.norm(result, axis=1), 1, atol=1e-4):
            raise ValueError("Invalid or unnormalized encoder vectors")
        return result

    def get(self, text_hash: str) -> tuple[np.ndarray, np.ndarray | None, dict] | None:
        row = self.connection.execute(
            "SELECT vector,prefix_vector,payload FROM texts WHERE text_hash=?", (text_hash,)).fetchone()
        if row is None:
            return None
        vector = np.frombuffer(row[0], dtype="float32")
        prefix = np.frombuffer(row[1], dtype="float32") if row[1] is not None else None
        if vector.shape != (self.dimension,) or not np.isfinite(vector).all():
            raise ValueError("Corrupted cached field vector")
        if prefix is not None and prefix.shape != vector.shape:
            raise ValueError("Corrupted cached prefix vector")
        return vector, prefix, json.loads(gzip.decompress(row[2]).decode("utf-8"))

    def ensure(self, fields: list[dict], *, prefixes: bool = False) -> None:
        unique = {row["text_sha256"]: row["text"] for row in fields}
        missing = []
        prefix_missing = []
        for text_hash, text in unique.items():
            cached = self.get(text_hash)
            if cached is None:
                missing.append((text_hash, text))
            elif prefixes and cached[1] is None:
                prefix_missing.append((text_hash, text))
        for start in range(0, len(missing), 16):
            batch = missing[start:start + 16]
            begun = time.perf_counter()
            all_spans, inputs = [], []
            for _, text in batch:
                spans = chunk_text(text, self.model.tokenizer, self.max_tokens, self.prefix)
                all_spans.append(spans)
                inputs.extend(self.prefix + span["text"] for span in spans)
            vectors = self._encode(inputs)
            scores = vectors @ self.code_vectors.T
            truncated = self._encode([self.prefix + text for _, text in batch]) if prefixes else None
            position = 0
            for number, ((text_hash, text), spans) in enumerate(zip(batch, all_spans)):
                stop = position + len(spans)
                vector = aggregate_chunks(vectors[position:stop],
                                          np.asarray([span["weight"] for span in spans]))
                payload = {
                    "source_characters": len(text),
                    "original_input_tokens": token_count(self.model.tokenizer, text, self.prefix),
                    "spans": [{name: span[name] for name in (
                        "start", "end", "weight", "input_tokens")} for span in spans],
                    "code_scores": scores[position:stop].round(7).tolist(),
                }
                self.connection.execute(
                    "INSERT INTO texts VALUES (?,?,?,?)",
                    (text_hash, vector.tobytes(), truncated[number].tobytes() if prefixes else None,
                     gzip.compress(json.dumps(payload).encode("utf-8"))),
                )
                position = stop
            elapsed = time.perf_counter() - begun
            self.connection.execute("UPDATE timing SET seconds=seconds+?,fields=fields+? WHERE id=1",
                                    (elapsed, len(batch)))
            self.connection.commit()
            LOGGER.info("%s: cached %s/%s new exact fields (%.1fs batch)",
                        self.key, min(start + 16, len(missing)), len(missing), elapsed)
        for start in range(0, len(prefix_missing), 16):
            batch = prefix_missing[start:start + 16]
            vectors = self._encode([self.prefix + text for _, text in batch])
            for (text_hash, _), vector in zip(batch, vectors):
                self.connection.execute("UPDATE texts SET prefix_vector=? WHERE text_hash=?",
                                        (vector.tobytes(), text_hash))
            self.connection.commit()

    def close(self):
        self.connection.close()
        del self.model
        gc.collect()


def encode_benchmark(key: str, output: Path = OUTPUT) -> None:
    fields = read_fields(output / "sample_fields.jsonl")
    folder = output / "encoders" / key
    finished = folder / "benchmark_complete.json"
    sample_hash = file_digest(output / "sample_fields.jsonl")
    if finished.exists():
        state = json.loads(finished.read_text())
        if state["sample_sha256"] != sample_hash:
            raise ValueError("Benchmark embeddings belong to another sample")
        for name in ("complete.npy", "prefix.npy"):
            matrix = np.load(folder / name, allow_pickle=False)
            if len(matrix) != len(fields) or not np.isfinite(matrix).all():
                raise ValueError(f"Invalid cached benchmark matrix: {key}/{name}")
        LOGGER.info("%s: benchmark embeddings already complete", key)
        return
    cache = EncoderCache(key, output)
    try:
        cache.ensure(fields, prefixes=True)
        complete, prefix, audits = [], [], []
        for field in fields:
            vector, truncated, payload = cache.get(field["text_sha256"])
            if truncated is None:
                raise ValueError("Missing prefix comparator")
            complete.append(vector)
            prefix.append(truncated)
            spans = payload["spans"]
            audits.append({
                "field_id": field["field_id"], "chunks": len(spans),
                "source_characters": len(field["text"]),
                "covered_characters": sum(span["end"] - span["start"] for span in spans),
                "max_chunk_tokens": max(span["input_tokens"] for span in spans),
                "prefix_would_truncate": payload["original_input_tokens"] > cache.max_tokens,
            })
        for name, values in (("complete", complete), ("prefix", prefix)):
            np.save(folder / f"{name}.npy", np.stack(values))
        import pandas as pd
        pd.DataFrame(audits).to_csv(folder / "coverage_audit.csv", index=False)
        seconds, unique_fields = cache.connection.execute("SELECT seconds,fields FROM timing").fetchone()
        write_json(finished, {
            **cache.fingerprint, "sample_sha256": sample_hash, "fields": len(fields),
            "cached_unique_fields": unique_fields, "chunk_and_prefix_compute_seconds": seconds,
            "chunks": sum(row["chunks"] for row in audits),
            "all_characters_covered": all(row["source_characters"] == row["covered_characters"] for row in audits),
            "prefix_truncation_fraction": float(np.mean([row["prefix_would_truncate"] for row in audits])),
        })
    finally:
        cache.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--models", nargs="+", choices=list(MODELS), default=list(MODELS))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for key in args.models:
        encode_benchmark(key, args.output)

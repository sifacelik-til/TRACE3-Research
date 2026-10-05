"""Local, resumable E5/BGE-M3/Qwen3/MiniLM competition on matched CDP splits.

Downloads model weights only; no response text is sent to a remote service.
Requires sentence-transformers >=5.1, transformers >=4.51, and PyTorch,
plus the dependencies of verify_cdp_clustering_choice.py.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import itertools
import json
import os
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import torch  # Initialize Windows DLLs before importing numerical libraries.
import joblib
import numpy as np
import pandas as pd
from huggingface_hub import HfApi, snapshot_download
from sentence_transformers import SentenceTransformer
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import adjusted_rand_score, silhouette_score
from threadpoolctl import threadpool_limits

from src.cdp_text_clustering.cdp_encoder_settings import (
    ROOT, PREVIOUS, DEFAULT_OUTPUT, MODEL_CACHE, MODELS, PREFIXES, SEEDS,
)
DATASETS = (
    "longitudinal_initiative", "longitudinal_risk", "longitudinal_opportunity",
    "q7_55_2", "q7_55_3", "q7_55_4",
)


def write_json(path: Path, content: dict) -> None:
    pending = path.with_suffix(path.suffix + ".pending")
    pending.write_text(json.dumps(content, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    pending.replace(path)


def sha_text(texts: list[str]) -> str:
    return hashlib.sha256(json.dumps(texts, ensure_ascii=False).encode()).hexdigest()


def prepare(output: Path, per_dataset: int, max_tokens: int) -> pd.DataFrame:
    manifest = pd.read_csv(PREVIOUS / "split_manifest.csv", dtype={"company_id": str})
    selected = []
    for dataset in DATASETS:
        source = pd.read_csv(
            PREVIOUS / f"{dataset}_kmeans_assignments.csv.gz", dtype={"company_id": str}
        )
        split = manifest.loc[manifest.dataset.eq(dataset)]
        for role, budget in (("train", int(per_dataset * 0.8)),
                             ("holdout", per_dataset - int(per_dataset * 0.8))):
            candidates = split.loc[split.split.eq(role)]
            take = candidates.sample(n=min(budget, len(candidates)), random_state=20260929)
            take = take.merge(source[["record_id", "text"]], on="record_id",
                              how="left", validate="one_to_one")
            if take.text.isna().any():
                raise ValueError("Missing narrative in matched sample")
            selected.append(take)
    frame = pd.concat(selected, ignore_index=True)
    for dataset, rows in frame.groupby("dataset"):
        train = rows.loc[rows.split.eq("train")]
        test = rows.loc[rows.split.eq("holdout")]
        if set(train.connected_group) & set(test.connected_group):
            raise ValueError(f"Connected-group leakage: {dataset}")
        if set(train.company_id) & set(test.company_id):
            raise ValueError(f"Company leakage: {dataset}")
    fingerprint = {
        "records_and_text_sha256": sha_text(
            (frame.dataset + ":" + frame.record_id + ":" + frame.split + ":" + frame.text).tolist()
        ),
        "per_dataset_budget": per_dataset, "max_tokens": max_tokens,
        "seeds": list(SEEDS), "models": MODELS, "prefixes": PREFIXES,
        "sample_rows": len(frame),
    }
    output.mkdir(parents=True, exist_ok=True)
    path = output / "experiment.json"
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8"))["fingerprint"] != fingerprint:
            raise ValueError("Existing experiment differs; choose another output directory")
    else:
        write_json(path, {
            "fingerprint": fingerprint,
            "packages": {package: importlib.metadata.version(package) for package in (
                "torch", "transformers", "sentence-transformers", "numpy", "pandas", "scikit-learn"
            )},
            "design": "CPU float32, common 256-token default cap including prompts; identical company-separated rows; five k-means seeds; k=12 except Q7.55.4 k=6.",
            "limitations": [
                "Development sample, not independent human validation or current SOTA ranking.",
                "Sequence cap is configurable; the recorded max_tokens value is authoritative.",
                "Equal token caps are not equal retained content across tokenizers; truncation is measured.",
                "MiniLM's distributed limit is 128; overriding it is an experimental setting.",
                "No model uses its full long-context capacity in the default run.",
                "Prompt and encoder are evaluated jointly; one untuned clustering instruction is used for Qwen.",
                "Longitudinal inputs contain structured options; 2024 inputs are narrative-only.",
                "Five seeds measure initialization stability, not company-resampling stability.",
                "K-means forces assignments; coverage is not accuracy.",
                "Cross-encoder silhouettes remain representation-dependent; no single space is ground truth.",
                "No language-stratified or temporal generalization claim; exact/near duplicates across datasets may exist.",
            ],
        })
    frame.drop(columns="text").to_csv(output / "sample_manifest.csv", index=False)
    frame.to_json(output / "sample_texts.jsonl", orient="records", lines=True, force_ascii=False)
    return frame


def download_model(key: str, output: Path) -> tuple[Path, str]:
    path = output / f"{key}_revision.json"
    repo = MODELS[key]
    if path.exists():
        revision = json.loads(path.read_text())["revision"]
    else:
        revision = HfApi().model_info(repo).sha
        if not revision:
            raise ValueError(f"No resolved model revision for {repo}")
        write_json(path, {"repository": repo, "revision": revision})
    print(f"Downloading/reusing {repo} @ {revision}", flush=True)
    files = HfApi().list_repo_files(repo, revision=revision)
    if "model.safetensors" in files or "model.safetensors.index.json" in files:
        weights = ["*.safetensors"]
    elif "pytorch_model.bin" in files:
        weights = ["pytorch_model.bin"]
    else:
        raise ValueError(f"No supported transformer weights in {repo} @ {revision}")
    folder = snapshot_download(
        repo_id=repo, revision=revision, local_dir=MODEL_CACHE / key / revision,
        allow_patterns=["*.json", "*.model", "vocab.txt", "merges.txt", *weights],
        ignore_patterns=["onnx/*", "openvino/*", "*sparse_linear*", "*colbert_linear*"],
        max_workers=3,
    )
    return Path(folder), revision


def encode(key: str, frame: pd.DataFrame, output: Path, max_tokens: int, batch_size: int) -> None:
    needed = [dataset for dataset in DATASETS
              if not (output / f"{key}_{dataset}_embeddings.npy").exists()]
    if not needed:
        print(f"{key}: all embeddings already saved", flush=True)
        return
    folder, revision = download_model(key, output)
    started = time.perf_counter()
    model = SentenceTransformer(
        str(folder), device="cpu", local_files_only=True, trust_remote_code=False,
        model_kwargs={"torch_dtype": torch.float32},
    )
    model.max_seq_length = max_tokens
    if key == "qwen3":
        model.tokenizer.padding_side = "left"
    print(f"{key}: loaded in {time.perf_counter() - started:.1f}s", flush=True)
    stats_path = output / f"{key}_encoding_stats.json"
    stats = json.loads(stats_path.read_text()) if stats_path.exists() else {}
    for dataset in DATASETS:
        rows = frame.loc[frame.dataset.eq(dataset)]
        texts = rows.text.tolist()
        target = output / f"{key}_{dataset}_embeddings.npy"
        if target.exists():
            if dataset not in stats or stats[dataset]["text_sha256"] != sha_text(texts):
                raise ValueError(f"Embedding cache metadata mismatch: {key}/{dataset}")
            continue
        inputs = [PREFIXES[key] + text for text in texts]
        lengths = [len(ids) for ids in model.tokenizer(
            inputs, truncation=False, padding=False, verbose=False
        )["input_ids"]]
        dimension = model.get_sentence_embedding_dimension()
        if dimension is None:
            raise ValueError("Encoder does not expose output dimension")
        partial = output / f"{key}_{dataset}_embeddings.partial.npy"
        progress_path = output / f"{key}_{dataset}_progress.json"
        fingerprint = {"revision": revision, "text_sha256": sha_text(inputs),
                       "max_tokens": max_tokens, "dimension": dimension}
        if partial.exists() != progress_path.exists():
            raise ValueError(f"Incomplete cache/progress pair: {partial}")
        if partial.exists():
            progress = json.loads(progress_path.read_text())
            if progress["fingerprint"] != fingerprint:
                raise ValueError(f"Partial cache fingerprint mismatch: {partial}")
            matrix = np.lib.format.open_memmap(partial, mode="r+")
        else:
            matrix = np.lib.format.open_memmap(
                partial, mode="w+", dtype="float32", shape=(len(inputs), dimension)
            )
            progress = {"fingerprint": fingerprint, "completed": 0, "encoding_seconds": 0.0}
            write_json(progress_path, progress)
        for first in range(progress["completed"], len(inputs), 64):
            last = min(first + 64, len(inputs))
            started = time.perf_counter()
            matrix[first:last] = model.encode(
                inputs[first:last], batch_size=batch_size, normalize_embeddings=True,
                show_progress_bar=False, convert_to_numpy=True, prompt="",
            )
            elapsed = time.perf_counter() - started
            matrix.flush()
            progress["completed"] = last
            progress["encoding_seconds"] += elapsed
            write_json(progress_path, progress)
            print(f"{key}/{dataset}: {last}/{len(inputs)} "
                  f"({progress['encoding_seconds']:.1f}s)", flush=True)
        if not np.isfinite(matrix).all() or not np.allclose(
            np.linalg.norm(matrix, axis=1), 1, atol=1e-4
        ):
            raise ValueError("Nonfinite or unnormalized encoder output")
        stats[dataset] = {
            "revision": revision, "text_sha256": sha_text(texts),
            "rows": len(inputs), "dimension": dimension,
            "max_tokens": max_tokens, "prefix": PREFIXES[key],
            "truncated_rows": sum(length > max_tokens for length in lengths),
            "truncated_fraction": float(np.mean(np.asarray(lengths) > max_tokens)),
            "median_input_tokens": float(np.median(lengths)),
            "encoding_seconds": progress["encoding_seconds"],
        }
        # Persist metadata first so an interrupted rename can be resumed.
        write_json(stats_path, stats)
        del matrix
        partial.replace(target)
        progress_path.unlink()
    del model


def evaluate(frame: pd.DataFrame, output: Path) -> None:
    metrics, stability, cross_space, pairwise, summaries = [], [], [], [], []
    with threadpool_limits(limits=4):
        for dataset in DATASETS:
            rows = frame.loc[frame.dataset.eq(dataset)].reset_index(drop=True)
            train = np.flatnonzero(rows.split.eq("train"))
            test = np.flatnonzero(rows.split.eq("holdout"))
            vectors = {
                key: np.load(output / f"{key}_{dataset}_embeddings.npy") for key in MODELS
            }
            for key, matrix in vectors.items():
                if len(matrix) != len(rows) or not np.isfinite(matrix).all():
                    raise ValueError(f"Invalid vectors: {key}/{dataset}")
            vectorizer = TfidfVectorizer(
                stop_words="english", min_df=2, max_df=0.9, max_features=15000
            )
            x_train = vectorizer.fit_transform(rows.iloc[train].text)
            x_test = vectorizer.transform(rows.iloc[test].text)
            terms = np.asarray(vectorizer.get_feature_names_out())
            reference_predictions = {}
            for key, matrix in vectors.items():
                predictions = []
                for seed in SEEDS:
                    model = KMeans(n_clusters=6 if dataset == "q7_55_4" else 12,
                                   n_init=10, random_state=seed)
                    model.fit(matrix[train])
                    labels = model.predict(matrix[test])
                    predictions.append(labels)
                    entry = {
                        "dataset": dataset, "encoder": key, "seed": seed,
                        "train_rows": len(train), "holdout_rows": len(test),
                        "holdout_topics": len(set(labels)),
                        "lexical_silhouette": float(silhouette_score(x_test, labels, metric="cosine")),
                        "largest_topic_share": float(pd.Series(labels).value_counts(normalize=True).max()),
                    }
                    for space, features in vectors.items():
                        score = float(silhouette_score(features[test], labels, metric="cosine"))
                        cross_space.append({
                            "dataset": dataset, "encoder": key, "seed": seed,
                            "evaluation_space": space, "silhouette": score,
                        })
                        entry[f"silhouette_in_{space}"] = score
                    metrics.append(entry)
                    if seed == 42:
                        reference_predictions[key] = labels
                        joblib.dump(model, output / f"{key}_{dataset}_kmeans.joblib")
                        assigned = rows[["record_id", "company_id", "split", "text"]].copy()
                        assigned["cluster"] = model.predict(matrix)
                        assigned.to_csv(output / f"{key}_{dataset}_assignments.csv.gz", index=False)
                        examples = []
                        for topic in range(model.n_clusters):
                            members = np.flatnonzero(model.labels_ == topic)
                            scores = np.asarray(x_train[members].mean(axis=0)).ravel()
                            summaries.append({
                                "dataset": dataset, "encoder": key, "cluster": topic,
                                "train_rows": len(members),
                                "sample_rows": int(assigned.cluster.eq(topic).sum()),
                                "top_words": "; ".join(terms[np.argsort(scores)[-10:][::-1]]),
                                "label_status": "automatic_words_not_validated",
                            })
                            indices = train[members]
                            nearest = indices[np.argsort(np.linalg.norm(
                                matrix[indices] - model.cluster_centers_[topic], axis=1
                            ))[:2]]
                            for index in nearest:
                                examples.append({
                                    "cluster": topic, "record_id": rows.iloc[index].record_id,
                                    "text": rows.iloc[index].text,
                                })
                        write_json(output / f"{key}_{dataset}_examples.json", {"examples": examples})
                aris = [adjusted_rand_score(a, b) for a, b in itertools.combinations(predictions, 2)]
                stability.append({
                    "dataset": dataset, "encoder": key,
                    "seed_ari_mean": float(np.mean(aris)), "seed_ari_min": float(min(aris)),
                })
            for first, second in itertools.combinations(MODELS, 2):
                pairwise.append({
                    "dataset": dataset, "first_encoder": first, "second_encoder": second,
                    "seed42_ari": adjusted_rand_score(
                        reference_predictions[first], reference_predictions[second]
                    ),
                })
    pd.DataFrame(metrics).to_csv(output / "metrics_by_seed.csv", index=False)
    pd.DataFrame(cross_space).to_csv(output / "cross_encoder_silhouettes.csv", index=False)
    pd.DataFrame(pairwise).to_csv(output / "between_encoder_agreement.csv", index=False)
    pd.DataFrame(summaries).to_csv(output / "cluster_summaries.csv", index=False)
    pd.DataFrame(stability).to_csv(output / "seed_stability.csv", index=False)
    summary = pd.DataFrame(metrics).groupby(["dataset", "encoder"]).mean(numeric_only=True)
    summary = summary.drop(columns="seed").reset_index().merge(
        pd.DataFrame(stability), on=["dataset", "encoder"], validate="one_to_one"
    )
    summary.to_csv(output / "comparison_summary.csv", index=False)
    print(f"Completed encoder competition: {output}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--per-dataset", type=int, default=600)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--models", nargs="+", choices=list(MODELS), default=list(MODELS))
    parser.add_argument("--evaluate-only", action="store_true")
    args = parser.parse_args()
    if args.per_dataset < 100 or not 32 <= args.max_tokens <= 512 or args.batch_size < 1:
        parser.error("Require per-dataset >=100, 32<=max-tokens<=512, and batch-size>=1")
    torch.set_num_threads(6)
    frame = prepare(args.output, args.per_dataset, args.max_tokens)
    if not args.evaluate_only:
        for key in args.models:
            encode(key, frame, args.output, args.max_tokens, args.batch_size)
    missing = [f"{key}/{dataset}" for key in MODELS for dataset in DATASETS
               if not (args.output / f"{key}_{dataset}_embeddings.npy").exists()]
    if missing:
        print(f"Encoding incomplete; remaining: {', '.join(missing)}", flush=True)
        return
    evaluate(frame, args.output)


if __name__ == "__main__":
    main()

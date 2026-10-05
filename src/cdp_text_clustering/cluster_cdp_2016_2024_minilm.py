"""Cluster CDP 2016–2024 responses with a local multilingual MiniLM encoder.

The encoder is a transformer language model, not the TF-IDF baseline. Its
embeddings are cached on disk so an interrupted run can resume. Separate
MiniBatchKMeans models are fitted for initiatives, risks and opportunities;
every eligible response is assigned to a semantic cluster. Cluster names are
descriptive keywords, not validated causal or intervention labels.

Run with the project Python environment::

    python -m src.cdp_text_clustering.cluster_cdp_2016_2024_minilm

Use --trial N for a small end-to-end check without touching final outputs.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
from pathlib import Path

os.environ.setdefault("LOKY_MAX_CPU_COUNT", "8")
import torch  # Windows c10.dll needs torch loaded before NumPy/pandas.
import numpy as np
import pandas as pd

from src.cdp_text_clustering.cluster_cdp_2016_2024_climate_actions import MODEL_NAME, OUTPUT, RECORDS


def save_json(path: Path, payload: dict) -> None:
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def balanced_fit_indices(years: np.ndarray, limit: int, rng: np.random.Generator) -> np.ndarray:
    """Sample each response year, then fill unused places from remaining rows."""
    all_indices = np.arange(len(years))
    selected = []
    per_year = max(1, limit // len(np.unique(years)))
    for year in np.unique(years):
        candidates = all_indices[years == year]
        selected.extend(rng.choice(candidates, min(per_year, len(candidates)), replace=False))
    selected = np.asarray(selected, dtype=int)
    if len(selected) < min(limit, len(years)):
        remaining = np.setdiff1d(all_indices, selected, assume_unique=True)
        extra = rng.choice(remaining, min(limit - len(selected), len(remaining)), replace=False)
        selected = np.r_[selected, extra]
    return np.sort(selected)


def run(
    input_path: Path,
    output_dir: Path,
    *,
    trial: int | None,
    clusters_per_type: int,
    fit_limit: int,
    batch_size: int,
    max_seq_length: int,
) -> None:
    from sklearn.cluster import MiniBatchKMeans
    from sklearn.feature_extraction.text import TfidfVectorizer

    output_dir.mkdir(parents=True, exist_ok=True)
    print("Reading extracted CDP records...", flush=True)
    frame = pd.read_csv(
        input_path,
        usecols=["record_id", "record_type", "year", "narrative_for_clustering"],
        dtype={"record_id": "string", "record_type": "string", "year": "Int16", "narrative_for_clustering": "string"},
        low_memory=False,
    )
    if trial is not None:
        frame = frame.groupby(["record_type", "year"], group_keys=False, sort=False).head(trial).reset_index(drop=True)
    eligible = frame["narrative_for_clustering"].fillna("").str.len().ge(35).to_numpy()
    eligible_rows = np.flatnonzero(eligible)
    documents = frame.loc[eligible, "narrative_for_clustering"].astype(str).reset_index(drop=True)
    codes, unique_texts = pd.factorize(documents, sort=False)
    print(
        f"Eligible: {len(documents):,} responses; {len(unique_texts):,} unique narratives; "
        f"{len(frame) - len(documents):,} too short for clustering.", flush=True,
    )
    if not len(unique_texts):
        raise ValueError("No eligible narratives were found")

    from sentence_transformers import SentenceTransformer

    torch.set_num_threads(min(8, os.cpu_count() or 1))
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    encoder = SentenceTransformer(MODEL_NAME, local_files_only=True, device="cpu")
    encoder.max_seq_length = max_seq_length
    dimension = encoder.get_embedding_dimension()
    fingerprint = {
        "input_path": str(input_path.resolve()),
        "input_bytes": input_path.stat().st_size,
        "input_mtime_ns": input_path.stat().st_mtime_ns,
        "trial": trial,
        "model": MODEL_NAME,
        "max_seq_length": max_seq_length,
        "unique_narratives": len(unique_texts),
        "dimension": dimension,
    }
    # Keep the earlier 128-token checkpoint recoverable while using a
    # separate cache for the requested 256-token run.
    cache_suffix = "" if max_seq_length == 128 else f"_seq{max_seq_length}"
    embedding_path = output_dir / f"minilm_embeddings{cache_suffix}.npy"
    partial_embedding_path = output_dir / f"minilm_embeddings{cache_suffix}.partial.npy"
    progress_path = output_dir / f"minilm_embedding_progress{cache_suffix}.json"
    if progress_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        if progress.get("fingerprint") != fingerprint:
            raise RuntimeError(f"Existing embedding cache is for a different input/model: {progress_path}")
        completed = int(progress["completed"])
        if not (partial_embedding_path.exists() or embedding_path.exists()):
            raise RuntimeError("Embedding checkpoint exists but the array is missing")
        embedding_file = embedding_path if embedding_path.exists() else partial_embedding_path
        vectors = np.load(embedding_file, mmap_mode="r+")
    else:
        if embedding_path.exists() or partial_embedding_path.exists():
            raise RuntimeError("Embedding array exists without checkpoint; inspect it before rerunning")
        vectors = np.lib.format.open_memmap(
            partial_embedding_path, mode="w+", dtype="float32", shape=(len(unique_texts), dimension)
        )
        completed = 0
        save_json(progress_path, {"fingerprint": fingerprint, "completed": completed})
    if vectors.shape != (len(unique_texts), dimension):
        raise RuntimeError("Embedding cache has the wrong shape")

    for start in range(completed, len(unique_texts), batch_size):
        stop = min(start + batch_size, len(unique_texts))
        texts = unique_texts[start:stop].tolist()
        vectors[start:stop] = encoder.encode(
            texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False
        ).astype("float32", copy=False)
        vectors.flush()
        save_json(progress_path, {"fingerprint": fingerprint, "completed": stop})
        if stop % 2048 < batch_size or stop == len(unique_texts):
            print(f"Embedded {stop:,}/{len(unique_texts):,} unique narratives", flush=True)
    if partial_embedding_path.exists():
        del vectors
        partial_embedding_path.replace(embedding_path)
        vectors = np.load(embedding_path, mmap_mode="r")

    rng = np.random.default_rng(42)
    assignments: dict[str, tuple[str, str, float]] = {}
    summaries: list[dict] = []
    for record_type in sorted(frame.loc[eligible, "record_type"].dropna().unique()):
        type_mask = frame.loc[eligible_rows, "record_type"].eq(record_type).to_numpy()
        type_positions = np.flatnonzero(type_mask)
        type_rows = eligible_rows[type_positions]
        if len(type_rows) < clusters_per_type * 3:
            print(f"Skipping {record_type}: too few eligible responses", flush=True)
            continue
        years = frame.loc[type_rows, "year"].astype(int).to_numpy()
        fit_positions = balanced_fit_indices(years, min(fit_limit, len(type_rows)), rng)
        training = np.asarray(vectors[codes[type_positions[fit_positions]]], dtype="float32")
        model = MiniBatchKMeans(
            n_clusters=clusters_per_type, batch_size=1024, n_init=3,
            max_iter=100, random_state=42,
        )
        print(f"Fitting {record_type}: {len(fit_positions):,} stratified responses...", flush=True)
        model.fit(training)
        labels_for_fit = model.predict(training)
        training_docs = documents.iloc[type_positions[fit_positions]].tolist()
        vectorizer = TfidfVectorizer(
            lowercase=True, strip_accents="unicode", stop_words="english",
            ngram_range=(1, 2), min_df=3, max_df=0.8, max_features=15000,
            sublinear_tf=True, dtype=np.float32,
        )
        lexical = vectorizer.fit_transform(training_docs)
        terms = np.asarray(vectorizer.get_feature_names_out())
        names = {}
        for topic in range(clusters_per_type):
            member_rows = np.flatnonzero(labels_for_fit == topic)
            weights = np.asarray(lexical[member_rows].mean(axis=0)).ravel()
            best = weights.argsort()[-5:][::-1]
            names[topic] = ", ".join(terms[best])
        counts = np.zeros(clusters_per_type, dtype=int)
        similarities = [[] for _ in range(clusters_per_type)]
        unit_centers = model.cluster_centers_.astype("float32")
        unit_centers /= np.maximum(np.linalg.norm(unit_centers, axis=1, keepdims=True), 1e-12)
        ids = frame.loc[type_rows, "record_id"].astype(str).to_numpy()
        for start in range(0, len(type_positions), 4096):
            stop = min(start + 4096, len(type_positions))
            batch = np.asarray(vectors[codes[type_positions[start:stop]]], dtype="float32")
            labels = model.predict(batch)
            cosine = np.einsum("ij,ij->i", batch, unit_centers[labels])
            for record_id, topic, score in zip(ids[start:stop], labels, cosine):
                topic = int(topic)
                counts[topic] += 1
                similarities[topic].append(float(score))
                assignments[record_id] = (f"{record_type}_{topic:02d}", names[topic], float(score))
        for topic in range(clusters_per_type):
            summaries.append({
                "record_type": record_type,
                "cluster_id": f"{record_type}_{topic:02d}",
                "cluster_label": names[topic],
                "records": int(counts[topic]),
                "fit_sample_records": int(np.sum(labels_for_fit == topic)),
                "mean_cosine_to_centroid": float(np.mean(similarities[topic])) if counts[topic] else np.nan,
                "method": "multilingual MiniLM embeddings + MiniBatchKMeans",
                "model": MODEL_NAME,
                "max_seq_length": max_seq_length,
            })
        print(f"Assigned {record_type}: {len(type_rows):,} responses", flush=True)

    destination = output_dir / "climate_action_risk_opportunity_minilm_clusters.csv.gz"
    temporary = destination.with_name(destination.name + ".partial")
    with gzip.open(temporary, "wt", encoding="utf-8", newline="") as target:
        if trial is None:
            source = gzip.open(input_path, "rt", encoding="utf-8", newline="")
            reader = csv.DictReader(source)
            fields = list(reader.fieldnames or [])
        else:
            source = None
            fields = list(frame.columns)
            reader = frame.astype(object).where(frame.notna(), "").to_dict("records")
        try:
            writer = csv.DictWriter(target, fieldnames=fields + ["cluster_id", "cluster_label", "cosine_to_centroid", "cluster_method"])
            writer.writeheader()
            for row in reader:
                cluster_id, cluster_label, cosine = assignments.get(str(row["record_id"]), ("", "", ""))
                row.update({
                    "cluster_id": cluster_id,
                    "cluster_label": cluster_label,
                    "cosine_to_centroid": f"{cosine:.4f}" if isinstance(cosine, float) else "",
                    "cluster_method": "multilingual MiniLM embeddings + MiniBatchKMeans" if cluster_id else "",
                })
                writer.writerow(row)
        finally:
            if source is not None:
                source.close()
    temporary.replace(destination)
    pd.DataFrame(summaries).to_csv(output_dir / "minilm_cluster_summary.csv", index=False)
    save_json(output_dir / "minilm_run_metadata.json", {
        **fingerprint,
        "eligible_responses": len(documents),
        "assigned_responses": len(assignments),
        "clusters_per_type": clusters_per_type,
        "fit_limit_per_type": fit_limit,
        "algorithm": "multilingual MiniLM embeddings + MiniBatchKMeans",
        "interpretation": "Exploratory semantic grouping; cluster labels are not validated outcomes or causal effects.",
    })
    print(f"Saved {len(assignments):,} semantic assignments: {destination}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", type=int, metavar="ROWS_PER_TYPE_YEAR")
    parser.add_argument("--clusters-per-type", type=int, default=12)
    parser.add_argument("--fit-limit", type=int, default=18_000)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--max-seq-length", type=int, default=256)
    args = parser.parse_args()
    destination = OUTPUT / "minilm_trial" if args.trial is not None else OUTPUT
    run(
        RECORDS, destination, trial=args.trial,
        clusters_per_type=args.clusters_per_type, fit_limit=args.fit_limit,
        batch_size=args.batch_size, max_seq_length=args.max_seq_length,
    )


if __name__ == "__main__":
    main()

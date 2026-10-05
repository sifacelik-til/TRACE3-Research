"""Compare BERTopic, MiniLM/k-means, and TF-IDF/NMF on CDP 2016--2024.

The same year-balanced, exact-text-deduplicated sample and train/test split
is used for each method. MiniLM's maximum sequence length is 256 tokens.
Outputs are exploratory diagnostics, not external topic ground truth.

Example::

    python -m src.cdp_text_clustering.benchmark_cdp_topic_models --per-year 200
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import tempfile
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "8")
os.environ.setdefault("NUMBA_NUM_THREADS", "4")
numba_cache = Path(tempfile.gettempdir()) / "codex_cdp_numba_cache"
numba_cache.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("NUMBA_CACHE_DIR", str(numba_cache))

import torch  # Must precede NumPy and pandas on this Windows installation.
import numpy as np
import pandas as pd

from src.cdp_text_clustering.cluster_cdp_2016_2024_climate_actions import MODEL_NAME, RECORDS, ROOT
from src.cdp_text_clustering.umap_sklearn_compat import patch_topic_model_check_array


def prepare_sample(per_year: int, types: list[str], seed: int) -> pd.DataFrame:
    frame = pd.read_csv(
        RECORDS,
        usecols=["record_id", "record_type", "year", "narrative_for_clustering"],
        dtype={"record_id": "string", "record_type": "string", "year": "Int16", "narrative_for_clustering": "string"},
        low_memory=False,
    )
    frame = frame.loc[
        frame["record_type"].isin(types)
        & frame["narrative_for_clustering"].fillna("").str.len().ge(35)
    ].copy()
    frame = frame.drop_duplicates(["record_type", "narrative_for_clustering"])
    rng = np.random.default_rng(seed)
    parts = []
    for (_, _), group in frame.groupby(["record_type", "year"], sort=True):
        positions = rng.choice(len(group), size=min(per_year, len(group)), replace=False)
        selected = group.iloc[positions].copy()
        selected["split"] = "test"
        train_positions = rng.choice(len(selected), size=max(1, round(0.8 * len(selected))), replace=False)
        selected.iloc[train_positions, selected.columns.get_loc("split")] = "train"
        parts.append(selected)
    sample = pd.concat(parts, ignore_index=True)
    sample = sample.sort_values(["record_type", "year", "record_id"]).reset_index(drop=True)
    sample["narrative_for_clustering"] = sample["narrative_for_clustering"].astype(str)
    return sample


def get_embeddings(sample: pd.DataFrame, output: Path, max_seq_length: int, batch_size: int) -> tuple[np.ndarray, float]:
    from sentence_transformers import SentenceTransformer

    torch.set_num_threads(min(8, os.cpu_count() or 1))
    fingerprint = {
        "model": MODEL_NAME,
        "max_seq_length": max_seq_length,
        "record_ids_sha256": hashlib.sha256("\n".join(sample["record_id"].astype(str)).encode()).hexdigest(),
        "n_records": len(sample),
        "source_size_bytes": RECORDS.stat().st_size,
        "source_mtime_ns": RECORDS.stat().st_mtime_ns,
    }
    embedding_path = output / "sample_embeddings.npy"
    metadata_path = output / "sample_embeddings_metadata.json"
    if embedding_path.exists() and metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata["fingerprint"] != fingerprint:
            raise RuntimeError("Existing embeddings do not match the sample or model settings")
        result = np.load(embedding_path)
        if result.shape != (len(sample), 384):
            raise RuntimeError("Saved embeddings have the wrong shape")
        print(f"Reused {len(result):,} cached {max_seq_length}-token MiniLM embeddings", flush=True)
        return result, float(metadata["seconds_to_encode"])
    if embedding_path.exists() or metadata_path.exists():
        raise RuntimeError("Only one of the embedding cache files exists; inspect before rerunning")
    encoder = SentenceTransformer(MODEL_NAME, local_files_only=True, device="cpu")
    encoder.max_seq_length = max_seq_length

    started = time.perf_counter()
    embeddings = encoder.encode(
        sample["narrative_for_clustering"].tolist(), batch_size=batch_size,
        normalize_embeddings=True, show_progress_bar=False,
    ).astype("float32", copy=False)
    seconds = time.perf_counter() - started
    temporary = embedding_path.with_name(embedding_path.name + ".partial")
    with temporary.open("wb") as stream:
        np.save(stream, embeddings)
    temporary.replace(embedding_path)
    metadata_path.write_text(json.dumps({"fingerprint": fingerprint, "seconds_to_encode": seconds}, indent=2), encoding="utf-8")
    print(f"Encoded {len(sample):,} narratives at 256 tokens in {seconds:.1f} s", flush=True)
    return embeddings, seconds


def centroid_terms(docs: list[str], labels: np.ndarray, n_words: int = 10) -> dict[int, list[str]]:
    from scipy.sparse import csr_matrix, vstack
    from sklearn.feature_extraction.text import CountVectorizer, TfidfTransformer

    vectorizer = CountVectorizer(
        stop_words="english", ngram_range=(1, 1), min_df=2,
        max_df=0.90, max_features=15000, binary=True,
    )
    counts = vectorizer.fit_transform(docs)
    terms = np.asarray(vectorizer.get_feature_names_out())
    topic_ids = [int(topic) for topic in np.unique(labels) if topic != -1]
    class_counts = vstack([csr_matrix(counts[labels == topic].sum(axis=0)) for topic in topic_ids])
    # Distinctive class-level TF-IDF terms make semantic cluster labels more
    # interpretable than raw frequent words, without changing assignments.
    class_scores = TfidfTransformer(norm="l1", use_idf=True, smooth_idf=True).fit_transform(class_counts)
    topics = {}
    for row, topic in enumerate(topic_ids):
        weights = class_scores.getrow(row).toarray().ravel()
        topics[topic] = terms[weights.argsort()[-n_words:][::-1]].tolist()
    return topics


def npmi_coherence(topics: dict[int, list[str]], reference_docs: list[str]) -> float:
    """Mean pairwise NPMI over top words, using the same sampled corpus."""
    from sklearn.feature_extraction.text import CountVectorizer

    words = sorted({word for topic in topics.values() for word in topic})
    if not words:
        return float("nan")
    vocabulary = {word: index for index, word in enumerate(words)}
    # BERTopic may report bigram topic terms. A unigram-only reference
    # vectorizer would assign those terms zero frequency and spuriously -1 NPMI.
    matrix = CountVectorizer(vocabulary=vocabulary, binary=True,
                             ngram_range=(1, 2)).transform(reference_docs)
    document_frequency = np.asarray(matrix.sum(axis=0)).ravel()
    cooccurrence = (matrix.T @ matrix).toarray()
    n_docs = len(reference_docs)
    values = []
    for topic_words in topics.values():
        topic_scores = []
        for i in range(len(topic_words)):
            for j in range(i + 1, len(topic_words)):
                first, second = vocabulary[topic_words[i]], vocabulary[topic_words[j]]
                overlap = float(cooccurrence[first, second])
                if overlap == 0:
                    topic_scores.append(-1.0)
                    continue
                p_pair = overlap / n_docs
                p_first = document_frequency[first] / n_docs
                p_second = document_frequency[second] / n_docs
                topic_scores.append(float(np.log(p_pair / (p_first * p_second)) / -np.log(p_pair)))
        if topic_scores:
            values.append(float(np.mean(topic_scores)))
    return float(np.mean(values)) if values else float("nan")


def evaluate(
    method: str, record_type: str, train_labels: np.ndarray, test_labels: np.ndarray,
    test_embeddings: np.ndarray, test_tfidf, topics: dict[int, list[str]], reference_docs: list[str],
    fit_seconds: float, predict_seconds: float, encoding_seconds: float,
) -> dict:
    from sklearn.metrics import silhouette_score

    train_labels = np.asarray(train_labels, dtype=int)
    test_labels = np.asarray(test_labels, dtype=int)
    assigned = test_labels != -1
    topic_ids = np.unique(train_labels[train_labels != -1])
    test_topic_ids = np.unique(test_labels[assigned])
    silhouette = float("nan")
    lexical_silhouette = float("nan")
    if 2 <= len(test_topic_ids) < int(assigned.sum()):
        silhouette = float(silhouette_score(test_embeddings[assigned], test_labels[assigned], metric="cosine"))
        lexical_silhouette = float(silhouette_score(test_tfidf[assigned], test_labels[assigned], metric="cosine"))
    top_words = [word for topic in topics.values() for word in topic[:10]]
    topic_diversity = len(set(top_words)) / len(top_words) if top_words else float("nan")
    assigned_train = train_labels[train_labels != -1]
    maximum_share = float(pd.Series(assigned_train).value_counts(normalize=True).max()) if len(assigned_train) else float("nan")
    return {
        "record_type": record_type, "method": method,
        "train_records": len(train_labels), "test_records": len(test_labels),
        "topics": len(topic_ids),
        "train_outlier_pct": float(100 * np.mean(train_labels == -1)),
        "test_outlier_pct": float(100 * np.mean(test_labels == -1)),
        "test_assigned": int(assigned.sum()),
        "test_silhouette_cosine": silhouette,
        "test_silhouette_tfidf_cosine": lexical_silhouette,
        "top10_word_diversity": float(topic_diversity),
        "top10_npmi_same_sample": npmi_coherence(topics, reference_docs),
        "largest_train_topic_share": maximum_share,
        "fit_seconds": fit_seconds, "predict_seconds": predict_seconds,
        "shared_minilm_encoding_seconds": encoding_seconds,
    }


def representative_examples(
    method: str, record_type: str, docs: list[str], record_ids: list[str],
    labels: np.ndarray, embeddings: np.ndarray, topics: dict[int, list[str]], limit: int = 3,
) -> list[dict]:
    rows = []
    for topic in topics:
        members = np.flatnonzero(labels == topic)
        if not len(members):
            continue
        center = np.asarray(embeddings[members].mean(axis=0), dtype="float32")
        center /= max(float(np.linalg.norm(center)), 1e-12)
        scores = embeddings[members] @ center
        selected = members[np.argsort(scores)[-limit:][::-1]]
        for rank, index in enumerate(selected, 1):
            rows.append({
                "method": method, "record_type": record_type, "topic_id": int(topic),
                "rank": rank, "record_id": record_ids[index],
                "top_words": topics[topic], "narrative": docs[index][:1200],
            })
    return rows


def run(args: argparse.Namespace) -> Path:
    from bertopic import BERTopic
    from hdbscan import HDBSCAN
    from sklearn.cluster import KMeans
    from sklearn.decomposition import NMF
    from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
    from umap import UMAP

    if patch_topic_model_check_array():
        print("Applied UMAP/HDBSCAN/scikit-learn finite-keyword compatibility shim", flush=True)

    types = args.types
    sample_cache = ROOT / "data" / "outputs" / "cdp_text_clustering" / "cdp_topic_model_benchmark" / f"n{args.per_year}_seq256_{'-'.join(types)}"
    output = sample_cache / f"models_k{args.n_topics}_mcs{args.min_cluster_size}_ms{args.min_samples}"
    output.mkdir(parents=True, exist_ok=True)
    sample = prepare_sample(args.per_year, types, seed=42)
    sample[["record_id", "record_type", "year", "split"]].to_json(output / "sample_manifest.jsonl", orient="records", lines=True)
    embeddings, encoding_seconds = get_embeddings(sample, sample_cache, 256, args.batch_size)
    rows: list[dict] = []
    examples: list[dict] = []
    topic_tables: list[dict] = []
    for record_type in types:
        subset = sample[sample["record_type"].eq(record_type)]
        positions = subset.index.to_numpy()
        docs = subset["narrative_for_clustering"].tolist()
        ids = subset["record_id"].astype(str).tolist()
        typed_embeddings = embeddings[positions]
        train = np.flatnonzero(subset["split"].eq("train").to_numpy())
        test = np.flatnonzero(subset["split"].eq("test").to_numpy())
        train_docs = [docs[index] for index in train]
        test_docs = [docs[index] for index in test]
        reference_docs = docs

        print(f"{record_type}: fitting TF-IDF/NMF on {len(train):,} narratives...", flush=True)
        nmf_vectorizer = TfidfVectorizer(
            stop_words="english", ngram_range=(1, 1), min_df=2,
            max_df=0.9, max_features=15000, sublinear_tf=True,
        )
        started = time.perf_counter()
        x_train = nmf_vectorizer.fit_transform(train_docs)
        nmf = NMF(n_components=args.n_topics, init="nndsvda", max_iter=400, random_state=42)
        train_weights = nmf.fit_transform(x_train)
        fit_seconds = time.perf_counter() - started
        started = time.perf_counter()
        x_test = nmf_vectorizer.transform(test_docs)
        test_weights = nmf.transform(x_test)
        predict_seconds = time.perf_counter() - started
        train_labels = train_weights.argmax(axis=1)
        test_labels = test_weights.argmax(axis=1)
        nmf_words = np.asarray(nmf_vectorizer.get_feature_names_out())
        topics = {int(topic): nmf_words[weights.argsort()[-10:][::-1]].tolist() for topic, weights in enumerate(nmf.components_)}
        rows.append(evaluate("TF-IDF + NMF", record_type, train_labels, test_labels, typed_embeddings[test], x_test, topics, reference_docs, fit_seconds, predict_seconds, 0.0))
        examples.extend(representative_examples("TF-IDF + NMF", record_type, train_docs, [ids[i] for i in train], train_labels, typed_embeddings[train], topics))
        topic_tables.extend({"record_type": record_type, "method": "TF-IDF + NMF", "topic_id": topic, "top_words": words} for topic, words in topics.items())

        print(f"{record_type}: fitting MiniLM/k-means...", flush=True)
        started = time.perf_counter()
        km = KMeans(n_clusters=args.n_topics, n_init=10, random_state=42)
        train_labels = km.fit_predict(typed_embeddings[train])
        fit_seconds = time.perf_counter() - started
        started = time.perf_counter()
        test_labels = km.predict(typed_embeddings[test])
        predict_seconds = time.perf_counter() - started
        topics = centroid_terms(train_docs, train_labels)
        rows.append(evaluate("MiniLM + k-means", record_type, train_labels, test_labels, typed_embeddings[test], x_test, topics, reference_docs, fit_seconds, predict_seconds, encoding_seconds))
        examples.extend(representative_examples("MiniLM + k-means", record_type, train_docs, [ids[i] for i in train], train_labels, typed_embeddings[train], topics))
        topic_tables.extend({"record_type": record_type, "method": "MiniLM + k-means", "topic_id": topic, "top_words": words} for topic, words in topics.items())

        print(f"{record_type}: fitting BERTopic...", flush=True)
        model = BERTopic(
            embedding_model=None,
            umap_model=UMAP(n_neighbors=15, n_components=5, min_dist=0.0, metric="cosine", random_state=42, low_memory=True),
            hdbscan_model=HDBSCAN(min_cluster_size=args.min_cluster_size, min_samples=args.min_samples, prediction_data=True, core_dist_n_jobs=4),
            # BERTopic fits this vectorizer on one aggregated document per
            # discovered topic, so min_df=2 can fail if only one topic forms.
            vectorizer_model=CountVectorizer(stop_words="english", ngram_range=(1, 1), min_df=1, max_df=1.0),
            calculate_probabilities=False, verbose=False,
        )
        started = time.perf_counter()
        train_labels, _ = model.fit_transform(train_docs, embeddings=typed_embeddings[train])
        fit_seconds = time.perf_counter() - started
        started = time.perf_counter()
        test_labels, _ = model.transform(test_docs, embeddings=typed_embeddings[test])
        predict_seconds = time.perf_counter() - started
        topics = {
            int(topic): [word for word, _ in model.get_topic(int(topic))[:10]]
            for topic in model.get_topics() if int(topic) >= 0 and model.get_topic(int(topic))
        }
        rows.append(evaluate("BERTopic", record_type, train_labels, test_labels, typed_embeddings[test], x_test, topics, reference_docs, fit_seconds, predict_seconds, encoding_seconds))
        examples.extend(representative_examples("BERTopic", record_type, train_docs, [ids[i] for i in train], np.asarray(train_labels), typed_embeddings[train], topics))
        topic_tables.extend({"record_type": record_type, "method": "BERTopic", "topic_id": topic, "top_words": words} for topic, words in topics.items())
        model_dir = output / f"bertopic_{record_type}"
        model.save(str(model_dir), serialization="safetensors", save_ctfidf=True)
        print(f"BERTopic {record_type}: {len(topics)} topics, {np.mean(np.asarray(test_labels) == -1):.1%} held-out outliers", flush=True)

    metadata = {
        "source": str(RECORDS), "per_year_per_type": args.per_year,
        "types": types, "n_fixed_topics": args.n_topics,
        "bertopic_min_cluster_size": args.min_cluster_size,
        "bertopic_min_samples": args.min_samples,
        "embedding_model": MODEL_NAME, "max_seq_length": 256,
        "seed": 42, "years": list(range(2016, 2025)),
        "diagnostic_limitations": "No human topic labels. NPMI uses the sampled corpus; silhouette is conditional on non-outliers. Methods have unequal topic counts. MiniLM-space silhouette structurally favors MiniLM-based clustering, while TF-IDF-space silhouette favors lexical clustering.",
        "package_versions": {
            name: importlib.metadata.version(name)
            for name in ["bertopic", "sentence-transformers", "scikit-learn", "umap-learn", "hdbscan", "torch"]
        },
    }
    (output / "benchmark_metrics.json").write_text(json.dumps(rows, indent=2, allow_nan=True), encoding="utf-8")
    pd.DataFrame(rows).to_csv(output / "benchmark_metrics.csv", index=False)
    (output / "topic_terms.json").write_text(json.dumps(topic_tables, indent=2, ensure_ascii=False), encoding="utf-8")
    (output / "representative_examples.json").write_text(json.dumps(examples, indent=2, ensure_ascii=False), encoding="utf-8")
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Saved comparative benchmark: {output}", flush=True)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-year", type=int, default=200)
    parser.add_argument("--types", nargs="+", choices=["initiative", "risk", "opportunity"], default=["initiative", "risk", "opportunity"])
    parser.add_argument("--n-topics", type=int, default=12)
    parser.add_argument("--min-cluster-size", type=int, default=25)
    parser.add_argument("--min-samples", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()

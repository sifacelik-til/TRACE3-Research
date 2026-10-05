"""Bounded, resumable BERTopic grid search on the year-balanced CDP sample.

Uses the existing 256-token MiniLM embeddings and the same held-out split as
benchmark_cdp_topic_models.py. This tunes topic discovery on a sample; it does
not assert that topics are substantively valid or fit all 314,298 records.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import itertools
import json
import os
import tempfile
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "8")
os.environ.setdefault("NUMBA_NUM_THREADS", "4")
os.environ.setdefault("NUMBA_CACHE_DIR", str(Path(tempfile.gettempdir()) / "codex_cdp_numba_cache"))
Path(os.environ["NUMBA_CACHE_DIR"]).mkdir(parents=True, exist_ok=True)

import torch  # Windows DLL initialization must precede NumPy and BERTopic.
import numpy as np
import pandas as pd

from src.cdp_text_clustering.benchmark_cdp_topic_models import get_embeddings, npmi_coherence, prepare_sample
from src.cdp_text_clustering.cluster_cdp_2016_2024_climate_actions import MODEL_NAME, RECORDS, ROOT
from src.cdp_text_clustering.umap_sklearn_compat import patch_topic_model_check_array


DEFAULT_OUTPUT = ROOT / "data/outputs/cdp_text_clustering/cdp_bertopic_grid_2016_2024"
TYPES = ("initiative", "risk", "opportunity")


def topic_words(model) -> dict[int, list[str]]:
    return {
        int(topic): [word for word, _ in model.get_topic(int(topic))[:10]]
        for topic in model.get_topics()
        if int(topic) >= 0 and model.get_topic(int(topic))
    }


def fit_model(docs: list[str], embeddings: np.ndarray, *, neighbors: int,
              cluster_size: int, min_samples: int):
    from bertopic import BERTopic
    from hdbscan import HDBSCAN
    from sklearn.feature_extraction.text import CountVectorizer
    from umap import UMAP

    model = BERTopic(
        embedding_model=None,
        umap_model=UMAP(n_neighbors=neighbors, n_components=5, min_dist=0.0,
                        metric="cosine", random_state=42, low_memory=True),
        hdbscan_model=HDBSCAN(min_cluster_size=cluster_size, min_samples=min_samples,
                             prediction_data=True, core_dist_n_jobs=4),
        vectorizer_model=CountVectorizer(stop_words="english", ngram_range=(1, 2),
                                         min_df=1, max_df=1.0),
        calculate_probabilities=False, verbose=False,
    )
    started = time.perf_counter()
    labels, _ = model.fit_transform(docs, embeddings=embeddings)
    return model, np.asarray(labels, dtype=int), time.perf_counter() - started


def diagnostics(model, train_labels: np.ndarray, test_labels: np.ndarray,
                test_embeddings: np.ndarray, reference_docs: list[str]) -> dict:
    from sklearn.metrics import silhouette_score

    topics = topic_words(model)
    assigned = test_labels != -1
    assigned_topics = np.unique(test_labels[assigned])
    silhouette = float("nan")
    if 2 <= len(assigned_topics) < int(assigned.sum()):
        silhouette = float(silhouette_score(
            test_embeddings[assigned], test_labels[assigned], metric="cosine"))
    words = [word for value in topics.values() for word in value]
    non_outliers = train_labels[train_labels != -1]
    largest_share = (float(pd.Series(non_outliers).value_counts(normalize=True).max())
                     if len(non_outliers) else float("nan"))
    return {
        "topics": len(topics),
        "train_outlier_pct": float(100 * np.mean(train_labels == -1)),
        "test_outlier_pct": float(100 * np.mean(test_labels == -1)),
        "test_assigned": int(assigned.sum()),
        "test_silhouette_cosine": silhouette,
        "top10_npmi_same_sample": npmi_coherence(topics, reference_docs),
        "top10_word_diversity": len(set(words)) / len(words) if words else float("nan"),
        "largest_train_topic_share": largest_share,
    }


def selection_score(row: pd.Series) -> float:
    """Explicit pragmatic score, not a measure of true topic validity."""
    if not 2 <= row["topics"] <= 50 or pd.isna(row["test_silhouette_cosine"]):
        return float("-inf")
    coverage = 1 - row["test_outlier_pct"] / 100
    separation = np.clip((row["test_silhouette_cosine"] + 0.05) / 0.25, 0, 1)
    coherence = np.clip((row["top10_npmi_same_sample"] + 0.1) / 0.4, 0, 1)
    diversity = row["top10_word_diversity"]
    return float(0.40 * coverage + 0.30 * separation +
                 0.20 * coherence + 0.10 * diversity)


def choose_best(frame: pd.DataFrame) -> tuple[pd.Series, str]:
    valid = frame.loc[frame["error"].isna() & frame["selection_score"].notna()].copy()
    valid = valid.loc[np.isfinite(valid["selection_score"])]
    if valid.empty:
        raise RuntimeError("No BERTopic trial produced at least two usable topics")
    for cap, label in ((35, "preferred <=35% held-out outliers"),
                       (60, "relaxed <=60% held-out outliers"),
                       (100, "no feasible outlier cap")):
        eligible = valid.loc[
            valid["topics"].between(5, 40)
            & valid["test_outlier_pct"].le(cap)
            & valid["largest_train_topic_share"].le(0.5)
        ]
        if not eligible.empty:
            best = eligible.sort_values(
                ["selection_score", "test_outlier_pct", "top10_npmi_same_sample"],
                ascending=[False, True, False],
            ).iloc[0]
            return best, label
    best = valid.sort_values("selection_score", ascending=False).iloc[0]
    return best, "all practical constraints relaxed"


def persist_csv(frame: pd.DataFrame, path: Path) -> None:
    pending = path.with_name(path.name + ".partial")
    frame.to_csv(pending, index=False)
    pending.replace(path)


def run(args: argparse.Namespace) -> Path:
    if patch_topic_model_check_array():
        print("Applied installed-library compatibility shim", flush=True)
    torch.set_num_threads(min(8, os.cpu_count() or 1))
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    sample = prepare_sample(args.per_year, list(args.types), seed=42)
    sample_cache = (ROOT / "data/outputs/cdp_text_clustering/cdp_topic_model_benchmark" /
                    f"n{args.per_year}_seq256_{'-'.join(args.types)}")
    embeddings, encoding_seconds = get_embeddings(sample, sample_cache, 256, args.batch_size)
    fingerprint = {
        "source": str(RECORDS), "source_size": RECORDS.stat().st_size,
        "sample_record_sha256": hashlib.sha256(
            "\n".join(sample["record_id"].astype(str)).encode()).hexdigest(),
        "per_year_per_type": args.per_year, "types": list(args.types),
        "neighbors": args.neighbors, "cluster_sizes": args.cluster_sizes,
        "min_samples": args.min_samples, "max_seq_length": 256,
        "encoder": MODEL_NAME, "seed": 42,
    }
    metadata_path = output / "search_metadata.json"
    if metadata_path.exists():
        previous = json.loads(metadata_path.read_text(encoding="utf-8"))
        if previous["fingerprint"] != fingerprint:
            raise RuntimeError("Existing grid output has different sample/settings; use a new output directory")
    else:
        metadata = {
            "fingerprint": fingerprint,
            "shared_embedding_seconds": encoding_seconds,
            "package_versions": {name: importlib.metadata.version(name) for name in
                ("bertopic", "sentence-transformers", "umap-learn", "hdbscan",
                 "scikit-learn", "torch")},
            "selection_rule": "Prefer 5-40 topics, <=35% test outliers, <=50% largest training topic; relax outlier cap to 60%, then constraints if needed. Within tier maximize 0.40 coverage + 0.30 scaled held-out semantic silhouette + 0.20 scaled same-sample NPMI + 0.10 word diversity.",
            "limitations": "Exploratory unsupervised metrics, not expert topic validity. Silhouette excludes outliers; NPMI uses the sampled corpus. Saved models fit only the 80% training sample, not the 314,298-record corpus.",
        }
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    sample[["record_id", "record_type", "year", "split"]].to_json(
        output / "sample_manifest.jsonl", orient="records", lines=True)

    metrics_path = output / "grid_metrics.csv"
    rows = pd.read_csv(metrics_path).to_dict("records") if metrics_path.exists() else []
    completed = {(r["record_type"], int(r["n_neighbors"]),
                  int(r["min_cluster_size"]), int(r["min_samples"])) for r in rows}
    grid = list(itertools.product(args.neighbors, args.cluster_sizes, args.min_samples))
    for record_type in args.types:
        subset = sample[sample["record_type"].eq(record_type)]
        positions = subset.index.to_numpy()
        docs = subset["narrative_for_clustering"].tolist()
        typed_embeddings = embeddings[positions]
        train = np.flatnonzero(subset["split"].eq("train").to_numpy())
        test = np.flatnonzero(subset["split"].eq("test").to_numpy())
        train_docs = [docs[i] for i in train]
        test_docs = [docs[i] for i in test]
        print(f"{record_type}: {len(train)} train / {len(test)} held-out narratives", flush=True)
        for neighbors, cluster_size, min_samples in grid:
            key = (record_type, neighbors, cluster_size, min_samples)
            if key in completed:
                print(f"  Reusing completed {key}", flush=True)
                continue
            result = {
                "record_type": record_type, "n_neighbors": neighbors,
                "min_cluster_size": cluster_size, "min_samples": min_samples,
                "train_records": len(train), "test_records": len(test),
                "error": None,
            }
            try:
                model, train_labels, fit_seconds = fit_model(
                    train_docs, typed_embeddings[train], neighbors=neighbors,
                    cluster_size=cluster_size, min_samples=min_samples)
                started = time.perf_counter()
                test_labels, _ = model.transform(test_docs, embeddings=typed_embeddings[test])
                predict_seconds = time.perf_counter() - started
                result.update(diagnostics(model, train_labels,
                                          np.asarray(test_labels, dtype=int),
                                          typed_embeddings[test], docs))
                result["fit_seconds"] = fit_seconds
                result["predict_seconds"] = predict_seconds
                result["selection_score"] = selection_score(pd.Series(result))
                print(f"  nn={neighbors} mcs={cluster_size} ms={min_samples}: "
                      f"{result['topics']} topics; test outliers "
                      f"{result['test_outlier_pct']:.1f}%; "
                      f"sil={result['test_silhouette_cosine']:.3f}; "
                      f"NPMI={result['top10_npmi_same_sample']:.3f}", flush=True)
            except Exception as exc:
                result["error"] = f"{type(exc).__name__}: {exc}"
                print(f"  FAILED {key}: {result['error']}", flush=True)
            rows.append(result)
            completed.add(key)
            persist_csv(pd.DataFrame(rows), metrics_path)

    metrics = pd.DataFrame(rows)
    selection_path = output / "selected_configs.csv"
    prior_full_refit_topics = {}
    if selection_path.exists():
        previous_selection = pd.read_csv(selection_path)
        if "final_refit_topics" in previous_selection.columns:
            prior_full_refit_topics = dict(zip(
                previous_selection["record_type"],
                previous_selection["final_refit_topics"],
            ))
        elif "all_sample_refit_topics_diagnostic" in previous_selection.columns:
            prior_full_refit_topics = {
                row.record_type: int(row.all_sample_refit_topics_diagnostic)
                for row in previous_selection.itertuples(index=False)
                if pd.notna(row.all_sample_refit_topics_diagnostic)
            }
    if not prior_full_refit_topics:
        for record_type in args.types:
            old_topics = (output / "unstable_full_sample_refits" /
                          record_type / "topics.json")
            if old_topics.exists():
                raw = json.loads(old_topics.read_text(encoding="utf-8"))
                prior_full_refit_topics[record_type] = sum(
                    int(topic) >= 0 for topic in raw["topic_representations"])
    selected = []
    term_rows = []
    for record_type in args.types:
        best, rule = choose_best(metrics.loc[metrics.record_type.eq(record_type)])
        choice = best.to_dict()
        choice["selection_tier"] = rule
        selected.append(choice)
        print(f"Selected {record_type}: nn={int(best.n_neighbors)}, "
              f"mcs={int(best.min_cluster_size)}, ms={int(best.min_samples)} "
              f"({rule})", flush=True)
        subset = sample[sample["record_type"].eq(record_type)]
        docs = subset["narrative_for_clustering"].tolist()
        train = np.flatnonzero(subset["split"].eq("train").to_numpy())
        train_docs = [docs[i] for i in train]
        train_embeddings = embeddings[subset.index.to_numpy()][train]
        model, labels, seconds = fit_model(
            train_docs, train_embeddings,
            neighbors=int(best.n_neighbors), cluster_size=int(best.min_cluster_size),
            min_samples=int(best.min_samples))
        model_dir = output / "best_models" / record_type
        model_dir.parent.mkdir(parents=True, exist_ok=True)
        model.save(str(model_dir), serialization="safetensors", save_ctfidf=True,
                   save_embedding_model=MODEL_NAME)
        for topic, words in topic_words(model).items():
            term_rows.append({"record_type": record_type, "topic_id": topic,
                              "topic_size": int(np.sum(labels == topic)),
                              "top_words": " | ".join(words)})
        choice["saved_model_fit_records"] = len(train_docs)
        choice["saved_model_fit_seconds"] = seconds
        choice["saved_model_topics"] = len(topic_words(model))
        choice["saved_model_train_outlier_pct"] = float(100 * np.mean(labels == -1))
        choice["all_sample_refit_topics_diagnostic"] = prior_full_refit_topics.get(record_type)
    persist_csv(pd.DataFrame(selected), selection_path)
    persist_csv(pd.DataFrame(term_rows), output / "best_topic_terms.csv")
    report = [
        "# BERTopic grid search: CDP climate narratives, 2016–2024",
        "",
        f"Year-balanced sample: {len(sample):,} distinct narratives; 80% train / 20% held out within each type/year. MiniLM max_seq_length=256; cached embeddings reused.",
        f"Grid: n_neighbors={args.neighbors}, min_cluster_size={args.cluster_sizes}, min_samples={args.min_samples}; 5 UMAP dimensions, cosine metric, random seed 42, unigram/bigram topic words.",
        "",
        "Selection gives explicit weight to held-out coverage, semantic separation, same-sample word coherence, and word diversity, subject to practical topic-count/outlier constraints. It is not evidence that topics are substantively correct.",
        "",
        "| Type | Neighbors | Cluster size | Min samples | Held-out outliers | Silhouette* | NPMI | Topics | Selection tier |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in selected:
        report.append(
            f"| {row['record_type']} | {int(row['n_neighbors'])} | "
            f"{int(row['min_cluster_size'])} | {int(row['min_samples'])} | "
            f"{row['test_outlier_pct']:.1f}% | {row['test_silhouette_cosine']:.3f} | "
            f"{row['top10_npmi_same_sample']:.3f} | {int(row['topics'])} | "
            f"{row['selection_tier']} |")
    report.extend([
        "", "*Silhouette is conditional on non-outlier test documents. Higher outlier rates can inflate it.",
        "", "Selected models are fitted on the training split and saved under best_models/. Their held-out diagnostics therefore describe the saved specification. They are not full-corpus assignments.",
        "Inspect best_topic_terms.csv and manually code representative disclosures before using these topics in regressions. CDP text can reproduce questionnaire categories; neither NPMI nor silhouette establishes scientific validity or causal effects.",
    ])
    if prior_full_refit_topics:
        detail = ", ".join(f"{kind}: {count} topics" for kind, count in prior_full_refit_topics.items())
        report.extend(["", "A separate all-sample refit check showed topic-count instability (" +
                       detail + "). The train-fitted models are retained so the selected topics agree with the held-out evaluation. Refit stability must be resolved before full-corpus deployment."])
    (output / "README.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"Saved grid search: {output}", flush=True)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-year", type=int, default=200)
    parser.add_argument("--types", nargs="+", choices=TYPES, default=list(TYPES))
    parser.add_argument("--neighbors", nargs="+", type=int, default=[15, 30])
    parser.add_argument("--cluster-sizes", nargs="+", type=int, default=[15, 25, 40])
    parser.add_argument("--min-samples", nargs="+", type=int, default=[1, 3])
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    run(parser.parse_args())


if __name__ == "__main__":
    main()

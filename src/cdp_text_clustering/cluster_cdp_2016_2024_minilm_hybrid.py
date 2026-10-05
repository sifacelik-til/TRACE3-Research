"""Neural-seeded CDP clustering with a validated fast inference surrogate.

MiniLM embeds a year-balanced sample for each response type and defines
semantic clusters. A TF-IDF linear classifier learns those neural assignments
and labels the remaining records. Output explicitly distinguishes the two
assignment methods. This is not BERTopic, and surrogate assignments are not
equivalent to embedding every record. For all-record neural inference, run
cluster_cdp_2016_2024_minilm.py instead.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import heapq
import json
import os
from pathlib import Path

os.environ.setdefault("LOKY_MAX_CPU_COUNT", "8")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
import torch  # Load before NumPy on Windows to avoid c10.dll errors.
import numpy as np
import pandas as pd

from src.cdp_text_clustering.cluster_cdp_2016_2024_climate_actions import MODEL_NAME, OUTPUT, RECORDS
from src.cdp_text_clustering.cluster_cdp_2016_2024_minilm import balanced_fit_indices, save_json


def write_representative_examples(per_cluster: int = 5) -> Path:
    """Keep the nearest directly embedded narratives for human topic review."""
    clustered = OUTPUT / "climate_action_risk_opportunity_minilm_hybrid_clusters.csv.gz"
    if not clustered.exists():
        raise FileNotFoundError(clustered)
    best: dict[str, list[tuple[float, int, dict]]] = {}
    with gzip.open(clustered, "rt", encoding="utf-8", newline="") as source:
        for position, row in enumerate(csv.DictReader(source)):
            if row["assignment_method"] != "MiniLM embedding":
                continue
            cluster_id = row["cluster_id"]
            selection = best.setdefault(cluster_id, [])
            item = (float(row["assignment_score"]), position, row)
            if len(selection) < per_cluster:
                heapq.heappush(selection, item)
            elif item[0] > selection[0][0]:
                heapq.heapreplace(selection, item)
    fields = [
        "record_id", "year", "record_type", "cluster_id", "cluster_label",
        "assignment_score", "narrative_for_clustering", "source_file",
        "source_sheet", "source_excel_row", "question_row",
    ]
    destination = OUTPUT / "minilm_hybrid_representative_examples.csv"
    with destination.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        for cluster_id in sorted(best):
            for _, _, row in sorted(best[cluster_id], reverse=True):
                writer.writerow({field: row.get(field, "") for field in fields})
    return destination


def run(sample_per_type: int, clusters_per_type: int, max_seq_length: int, batch_size: int) -> None:
    from sentence_transformers import SentenceTransformer
    from sklearn.cluster import MiniBatchKMeans
    from scipy.sparse import csr_matrix, vstack
    from sklearn.feature_extraction.text import CountVectorizer, TfidfTransformer, TfidfVectorizer
    from sklearn.metrics import accuracy_score, f1_score
    from sklearn.model_selection import GroupShuffleSplit
    from sklearn.svm import LinearSVC

    OUTPUT.mkdir(parents=True, exist_ok=True)
    frame = pd.read_csv(
        RECORDS,
        usecols=["record_id", "record_type", "year", "narrative_for_clustering"],
        dtype={"record_id": "string", "record_type": "string", "year": "Int16", "narrative_for_clustering": "string"},
        low_memory=False,
    )
    frame["narrative_for_clustering"] = frame["narrative_for_clustering"].fillna("")
    torch.set_num_threads(min(8, os.cpu_count() or 1))
    encoder = SentenceTransformer(MODEL_NAME, local_files_only=True, device="cpu")
    encoder.max_seq_length = max_seq_length
    rng = np.random.default_rng(42)
    assignments: dict[str, tuple[str, str, str, float]] = {}
    summaries = []
    validations = []
    for record_type in sorted(frame["record_type"].dropna().unique()):
        subset = frame.loc[
            frame["record_type"].eq(record_type)
            & frame["narrative_for_clustering"].str.len().ge(35)
        ].reset_index(drop=True)
        if len(subset) < clusters_per_type * 3:
            continue
        sample_indices = balanced_fit_indices(
            subset["year"].astype(int).to_numpy(), min(sample_per_type, len(subset)), rng
        )
        sampled = subset.iloc[sample_indices].reset_index(drop=True)
        sample_docs = sampled["narrative_for_clustering"].astype(str).tolist()
        print(f"Encoding {record_type}: {len(sample_docs):,} sampled CDP narratives...", flush=True)
        embeddings = encoder.encode(
            sample_docs, batch_size=batch_size, normalize_embeddings=True,
            show_progress_bar=True,
        ).astype("float32", copy=False)
        groups = pd.factorize(sampled["narrative_for_clustering"], sort=False)[0]
        train, test = next(GroupShuffleSplit(test_size=0.2, n_splits=1, random_state=42).split(sampled, groups=groups))
        clusterer = MiniBatchKMeans(
            n_clusters=clusters_per_type, batch_size=1024, n_init=3,
            max_iter=100, random_state=42,
        )
        clusterer.fit(embeddings[train])
        neural_labels = clusterer.predict(embeddings)
        vectorizer = TfidfVectorizer(
            lowercase=True, strip_accents="unicode", stop_words="english",
            ngram_range=(1, 2), min_df=3, max_df=0.85, max_features=30000,
            sublinear_tf=True, dtype=np.float32,
        )
        train_features = vectorizer.fit_transform([sample_docs[i] for i in train])
        classifier = LinearSVC(C=1.0, class_weight="balanced", dual=True, random_state=42)
        classifier.fit(train_features, neural_labels[train])
        test_predictions = classifier.predict(vectorizer.transform([sample_docs[i] for i in test]))
        accuracy = float(accuracy_score(neural_labels[test], test_predictions))
        macro_f1 = float(f1_score(neural_labels[test], test_predictions, average="macro", zero_division=0))
        validations.append({
            "record_type": record_type,
            "training_records": len(train), "holdout_records": len(test),
            "holdout_accuracy": accuracy, "holdout_macro_f1": macro_f1,
            "holdout_split": "GroupShuffleSplit by exact narrative; 20% held out",
            "interpretation": "Agreement of TF-IDF surrogate with neural clusters, not external topic validity",
        })
        print(f"{record_type}: surrogate holdout accuracy={accuracy:.3f}; macro-F1={macro_f1:.3f}", flush=True)

        # Refit the surrogate on all MiniLM-labelled sampled texts.
        sample_features = vectorizer.fit_transform(sample_docs)
        classifier.fit(sample_features, neural_labels)
        label_vectorizer = CountVectorizer(
            lowercase=True, strip_accents="unicode", stop_words="english",
            ngram_range=(1, 1), min_df=3, max_df=0.9,
            max_features=15000, binary=True,
        )
        label_counts = label_vectorizer.fit_transform(sample_docs)
        terms = np.asarray(label_vectorizer.get_feature_names_out())
        class_counts = vstack([
            csr_matrix(label_counts[neural_labels == topic].sum(axis=0))
            for topic in range(clusters_per_type)
        ])
        class_scores = TfidfTransformer(norm="l1", use_idf=True).fit_transform(class_counts)
        names = {}
        for topic in range(clusters_per_type):
            weights = class_scores.getrow(topic).toarray().ravel()
            names[topic] = ", ".join(terms[weights.argsort()[-5:][::-1]])

        sampled_ids = set(sampled["record_id"].astype(str))
        neural_counts = np.zeros(clusters_per_type, dtype=int)
        surrogate_counts = np.zeros(clusters_per_type, dtype=int)
        centers = clusterer.cluster_centers_.astype("float32")
        centers /= np.maximum(np.linalg.norm(centers, axis=1, keepdims=True), 1e-12)
        for row, topic, embedding in zip(sampled.itertuples(index=False), neural_labels, embeddings):
            topic = int(topic)
            neural_counts[topic] += 1
            similarity = float(np.dot(embedding, centers[topic]))
            assignments[str(row.record_id)] = (
                f"{record_type}_{topic:02d}", names[topic], "MiniLM embedding", similarity,
            )
        unsampled = subset.loc[~subset["record_id"].isin(sampled_ids)]
        for start in range(0, len(unsampled), 5000):
            batch = unsampled.iloc[start:start + 5000]
            features = vectorizer.transform(batch["narrative_for_clustering"].astype(str).tolist())
            predicted = classifier.predict(features)
            margins = classifier.decision_function(features)
            confidence = np.max(margins, axis=1)
            for record_id, topic, margin in zip(batch["record_id"].astype(str), predicted, confidence):
                topic = int(topic)
                surrogate_counts[topic] += 1
                assignments[record_id] = (
                    f"{record_type}_{topic:02d}", names[topic], "TF-IDF surrogate of MiniLM clusters", float(margin),
                )
        for topic in range(clusters_per_type):
            summaries.append({
                "record_type": record_type,
                "cluster_id": f"{record_type}_{topic:02d}",
                "cluster_label": names[topic],
                "neural_assignments": int(neural_counts[topic]),
                "surrogate_assignments": int(surrogate_counts[topic]),
                "total_assignments": int(neural_counts[topic] + surrogate_counts[topic]),
                "surrogate_holdout_accuracy": accuracy,
                "surrogate_holdout_macro_f1": macro_f1,
            })
        print(f"Assigned {record_type}: {len(subset):,} responses", flush=True)

    destination = OUTPUT / "climate_action_risk_opportunity_minilm_hybrid_clusters.csv.gz"
    temporary = destination.with_name(destination.name + ".partial")
    with gzip.open(RECORDS, "rt", encoding="utf-8", newline="") as source, gzip.open(
        temporary, "wt", encoding="utf-8", newline=""
    ) as target:
        reader = csv.DictReader(source)
        fields = list(reader.fieldnames or [])
        writer = csv.DictWriter(
            target, fieldnames=fields + ["cluster_id", "cluster_label", "assignment_method", "assignment_score"]
        )
        writer.writeheader()
        for row in reader:
            cluster_id, label, method, score = assignments.get(row["record_id"], ("", "", "", ""))
            row.update({
                "cluster_id": cluster_id,
                "cluster_label": label,
                "assignment_method": method,
                "assignment_score": f"{score:.4f}" if isinstance(score, float) else "",
            })
            writer.writerow(row)
    temporary.replace(destination)
    pd.DataFrame(summaries).to_csv(OUTPUT / "minilm_hybrid_cluster_summary.csv", index=False)
    pd.DataFrame(validations).to_csv(OUTPUT / "minilm_hybrid_validation.csv", index=False)
    save_json(OUTPUT / "minilm_hybrid_metadata.json", {
        "source": str(RECORDS), "model": MODEL_NAME,
        "max_seq_length": max_seq_length, "sample_per_type": sample_per_type,
        "clusters_per_type": clusters_per_type, "assigned_records": len(assignments),
        "algorithm": "MiniLM sampled embeddings + MiniBatchKMeans + validated TF-IDF LinearSVC surrogate",
        "caution": "Surrogate records were not embedded by MiniLM; assignment scores have different meanings by method.",
    })
    print(f"Saved {len(assignments):,} hybrid semantic assignments to {destination}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-per-type", type=int, default=6000)
    parser.add_argument("--clusters-per-type", type=int, default=12)
    parser.add_argument("--max-seq-length", type=int, default=256)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--examples-only", action="store_true", help="Export top directly embedded examples from an existing hybrid result")
    args = parser.parse_args()
    if args.examples_only:
        print(f"Saved representative examples: {write_representative_examples()}")
        return
    run(args.sample_per_type, args.clusters_per_type, args.max_seq_length, args.batch_size)


if __name__ == "__main__":
    main()

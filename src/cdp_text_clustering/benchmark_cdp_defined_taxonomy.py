"""Benchmark predefined CDP topics with supervised, company-grouped validation.

This script uses the manually validated workbook labels. It does not discover
clusters. Embeddings are inputs to a supervised classifier whose outcomes are
the predefined action-family, risk-type, opportunity-type, and engagement-role
labels. Action classes are evaluated separately by nearest validated example
because most fine-grained classes have too few examples to estimate a
multiclass model.
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import normalize


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "data" / "outputs" / "cdp_text_clustering" / "cdp_action_taxonomy_benchmark_20261002"
DEFAULT_OUTPUT = ROOT / "data" / "outputs" / "cdp_text_clustering" / "cdp_defined_taxonomy_benchmark_2020_2022"
MODELS = (
    "minilm", "e5_base", "bge_m3", "qwen3_06b", "gte_multilingual",
    "jina_v3", "e5_large_instruct",
)
TOPIC_NAMES = {
    "reduction": "action_family",
    "risk": "risk_type",
    "opportunity": "opportunity_type",
    "engagement": "engagement_topic",
}


def read_jsonl(path: Path) -> list[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def eligible(row: dict) -> bool:
    return str(row.get("eligibility", "")).casefold() == "yes"


def grouped_predictions(x: np.ndarray, y: np.ndarray, groups: np.ndarray,
                        folds: int) -> tuple[np.ndarray, np.ndarray]:
    predicted = np.empty(len(y), dtype=object)
    supported = np.zeros(len(y), dtype=bool)
    splitter = GroupKFold(n_splits=min(folds, len(set(groups))))
    for train, test in splitter.split(x, y, groups):
        train_labels = set(y[train])
        supported[test] = np.array([label in train_labels for label in y[test]])
        model = LogisticRegression(
            max_iter=3000, class_weight="balanced", solver="lbfgs",
            multi_class="auto", random_state=42,
        ).fit(x[train], y[train])
        predicted[test] = model.predict(x[test])
    return predicted, supported


def classification_metrics(y: np.ndarray, predicted: np.ndarray,
                           supported: np.ndarray) -> dict:
    return {
        "observations": len(y), "classes": len(set(y)),
        "learnable_label_coverage": float(supported.mean()),
        "accuracy": float(accuracy_score(y, predicted)),
        "macro_precision": float(precision_score(y, predicted, average="macro", zero_division=0)),
        "macro_recall": float(recall_score(y, predicted, average="macro", zero_division=0)),
        "macro_f1": float(f1_score(y, predicted, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(y, predicted, average="weighted", zero_division=0)),
        "supported_macro_f1": (
            float(f1_score(y[supported], predicted[supported], average="macro", zero_division=0))
            if supported.any() else None
        ),
    }


def action_class_retrieval(x: np.ndarray, rows: list[dict], folds: int) -> dict:
    x = normalize(x)
    labels = np.array([row["fine_human_label"] for row in rows], dtype=object)
    families = np.array([row["coarse_human_label"] for row in rows], dtype=object)
    groups = np.array([row["company"].casefold() for row in rows], dtype=object)
    predicted = np.empty(len(rows), dtype=object)
    splitter = GroupKFold(n_splits=min(folds, len(set(groups))))
    for train, test in splitter.split(x, labels, groups):
        for position in test:
            candidates = train[families[train] == families[position]]
            if not len(candidates):
                candidates = train
            nearest = candidates[int(np.argmax(x[candidates] @ x[position]))]
            predicted[position] = labels[nearest]
    frequencies = Counter(labels)
    repeated = np.array([frequencies[label] >= 2 for label in labels])
    return {
        "observations": len(labels), "classes": len(set(labels)),
        "classes_with_two_or_more_examples": sum(value >= 2 for value in frequencies.values()),
        "observations_in_repeated_classes": int(repeated.sum()),
        "exact_accuracy_all": float(accuracy_score(labels, predicted)),
        "exact_accuracy_repeated_classes": (
            float(accuracy_score(labels[repeated], predicted[repeated])) if repeated.any() else None
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--models", nargs="+", choices=MODELS, default=list(MODELS))
    parser.add_argument("--start-year", type=int, default=2020)
    parser.add_argument("--end-year", type=int, default=2022)
    parser.add_argument("--folds", type=int, default=5)
    args = parser.parse_args()

    records = read_jsonl(args.input / "span_records.jsonl.gz")
    selected = [
        (index, row) for index, row in enumerate(records)
        if args.start_year <= int(row["year"]) <= args.end_year and eligible(row)
    ]
    args.output.mkdir(parents=True, exist_ok=True)
    metrics, class_metrics = [], []
    for encoder in args.models:
        embeddings = np.load(args.input / "encoders" / encoder / "embeddings.npy")
        for goal in TOPIC_NAMES:
            subset = [(index, row) for index, row in selected if row["goal"] == goal]
            indices = np.array([index for index, _ in subset], dtype=int)
            rows = [row for _, row in subset]
            x = embeddings[indices]
            y = np.array([row["coarse_human_label"] for row in rows], dtype=object)
            groups = np.array([row["company"].casefold() for row in rows], dtype=object)
            predicted, supported = grouped_predictions(x, y, groups, args.folds)
            metrics.append({
                "encoder": encoder, "topic": TOPIC_NAMES[goal],
                **classification_metrics(y, predicted, supported),
            })
            if goal == "reduction":
                class_metrics.append({
                    "encoder": encoder, "topic": "action_class_retrieval",
                    **action_class_retrieval(x, rows, args.folds),
                })

    metric_frame = pd.DataFrame(metrics)
    metric_frame.to_csv(args.output / "topic_classification_metrics.csv", index=False)
    pd.DataFrame(class_metrics).to_csv(args.output / "action_class_retrieval_metrics.csv", index=False)
    family = metric_frame[metric_frame.topic.eq("action_family")]
    winner = family.sort_values(
        ["macro_f1", "learnable_label_coverage", "encoder"],
        ascending=[False, False, True],
    ).iloc[0]
    chosen = str(winner.encoder)
    reduction = [(index, row) for index, row in selected if row["goal"] == "reduction"]
    indices = np.array([index for index, _ in reduction], dtype=int)
    rows = [row for _, row in reduction]
    embeddings = np.load(args.input / "encoders" / chosen / "embeddings.npy")[indices]
    labels = np.array([row["coarse_human_label"] for row in rows], dtype=object)
    classifier = LogisticRegression(
        max_iter=3000, class_weight="balanced", solver="lbfgs",
        multi_class="auto", random_state=42,
    ).fit(embeddings, labels)
    joblib.dump({
        "encoder": chosen, "classifier": classifier,
        "class_names": list(classifier.classes_),
        "training_item_ids": [row["item_id"] for row in rows],
        "years": [args.start_year, args.end_year],
    }, args.output / "action_family_classifier.joblib")
    summary = {
        "years": [args.start_year, args.end_year], "selected_encoder": chosen,
        "selection_metric": "company-grouped five-fold macro F1 for predefined action families",
        "action_family_metrics": winner.to_dict(),
        "interpretation": (
            "Topics are defined by the validation workbook. No clustering or topic discovery is used."
        ),
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2, default=lambda value: value.item()) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, default=lambda value: value.item()))


if __name__ == "__main__":
    main()

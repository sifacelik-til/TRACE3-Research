"""Compare embedding models for predefined CDP text classification, 2020--2022."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score, balanced_accuracy_score, classification_report,
    confusion_matrix, f1_score, matthews_corrcoef, precision_score, recall_score,
)
from sklearn.model_selection import GroupKFold


ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "data" / "outputs" / "cdp_text_clustering" / "cdp_action_taxonomy_benchmark_20261002"
LABELS = ROOT / "data" / "processed" / "cdp_section_datasets" / "cdp_validation_detail_labels.jsonl.gz"
OUTPUT = ROOT / "data" / "outputs" / "cdp_text_clustering" / "cdp_text_classification_benchmark_2020_2022"
MODELS = ("minilm", "e5_base", "bge_m3", "qwen3_06b", "gte_multilingual", "jina_v3", "e5_large_instruct")
DISPLAY = {
    "minilm": "MiniLM", "e5_base": "E5-base", "bge_m3": "BGE-M3",
    "qwen3_06b": "Qwen3-0.6B", "gte_multilingual": "GTE-multilingual",
    "jina_v3": "Jina-v3", "e5_large_instruct": "E5-large-instruct",
}
TASKS = ("reduction", "risk", "opportunity", "engagement")


def read_jsonl(path: Path) -> list[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def norm(value: object) -> str:
    return str(value or "").strip()


def risk_label(row: dict) -> str:
    if norm(row["In-scope risk item?"]).casefold() != "yes":
        return "Not a risk item"
    value = norm(row["Risk type"]).casefold()
    physical, transition = "physical" in value, "transition" in value
    if physical and transition:
        return "Physical and transition"
    if "acute" in value and "chronic" in value:
        return "Acute and chronic physical"
    if "acute" in value:
        return "Acute physical"
    if "chronic" in value:
        return "Chronic physical"
    if "policy" in value or "legal" in value or "regulat" in value:
        return "Policy and legal transition"
    if "market" in value or "portfolio" in value:
        return "Market transition"
    if "technolog" in value:
        return "Technology transition"
    if "reputation" in value:
        return "Reputation transition"
    return "Other or unspecified risk"


def opportunity_label(row: dict) -> str:
    if norm(row["In-scope opportunity item?"]).casefold() != "yes":
        return "Not an opportunity item"
    value = norm(row["Opportunity type"]).casefold()
    hits = []
    for token, label in (
        ("products and services", "Products and services"),
        ("resource efficiency", "Resource efficiency"),
        ("energy source", "Energy source"), ("resilience", "Resilience"),
        ("markets", "Markets"), ("financial", "Financial products and services"),
        ("access to capital", "Access to capital"), ("policy", "Policy incentives"),
    ):
        if token in value:
            hits.append(label)
    hits = list(dict.fromkeys(hits))
    if len(hits) > 1:
        return "Multiple opportunity types"
    return hits[0] if hits else "Other or unspecified opportunity"


def target(section: str, row: dict) -> str:
    if section == "reduction":
        return (
            norm(row["Action family"]) if norm(row["Counts as action"]).casefold() == "yes"
            else "Not a reduction action"
        ) or "Other or unspecified action"
    if section == "risk":
        return risk_label(row)
    if section == "opportunity":
        return opportunity_label(row)
    if section == "engagement":
        return norm(row["Item role"]) or "Other or unspecified engagement"
    raise ValueError(section)


def oof_predict(x: np.ndarray, y: np.ndarray, groups: np.ndarray, folds: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    prediction = np.empty(len(y), dtype=object)
    probability = np.zeros(len(y), dtype=float)
    learnable = np.zeros(len(y), dtype=bool)
    split = GroupKFold(n_splits=min(folds, len(set(groups))))
    for train, test in split.split(x, y, groups):
        seen = set(y[train])
        learnable[test] = [label in seen for label in y[test]]
        model = LogisticRegression(
            max_iter=4000, class_weight="balanced", solver="lbfgs",
            random_state=42,
        ).fit(x[train], y[train])
        prediction[test] = model.predict(x[test])
        probability[test] = model.predict_proba(x[test]).max(axis=1)
    return prediction, probability, learnable


def metric_row(model: str, section: str, y: np.ndarray, prediction: np.ndarray,
               probability: np.ndarray, learnable: np.ndarray) -> dict:
    return {
        "encoder": model, "model": DISPLAY[model], "section": section,
        "observations": len(y), "classes": len(set(y)),
        "learnable_label_coverage": learnable.mean(),
        "accuracy": accuracy_score(y, prediction),
        "macro_precision": precision_score(y, prediction, average="macro", zero_division=0),
        "macro_recall": recall_score(y, prediction, average="macro", zero_division=0),
        "macro_f1": f1_score(y, prediction, average="macro", zero_division=0),
        "weighted_f1": f1_score(y, prediction, average="weighted", zero_division=0),
        "balanced_accuracy": balanced_accuracy_score(y, prediction),
        "matthews_correlation": matthews_corrcoef(y, prediction),
        "mean_max_probability": probability.mean(),
    }


def plot_metric_comparison(metrics: pd.DataFrame, output: Path, tasks: tuple[str, ...]) -> None:
    sns.set_theme(style="whitegrid", context="paper")
    columns = min(2, len(tasks))
    rows = int(np.ceil(len(tasks) / columns))
    fig, axes = plt.subplots(rows, columns, figsize=(7 * columns, 4.2 * rows), sharey=True, squeeze=False)
    order = [DISPLAY[key] for key in MODELS]
    for axis, section in zip(axes.flat, tasks):
        data = metrics[metrics.section.eq(section)].melt(
            id_vars=["model"], value_vars=["accuracy", "macro_f1"],
            var_name="metric", value_name="score",
        )
        sns.barplot(data=data, x="score", y="model", hue="metric", order=order, ax=axis)
        axis.set_title(section.capitalize())
        axis.set_xlim(0, 1)
        axis.set_xlabel("Held-out score")
        axis.set_ylabel("")
        if axis is not axes.flat[0]:
            axis.get_legend().remove()
    for axis in axes.flat[len(tasks):]:
        axis.set_visible(False)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    axes.flat[0].get_legend().remove()
    fig.legend(handles, ["Accuracy", "Macro F1"], loc="lower center", ncol=2, frameon=False)
    fig.tight_layout(rect=(0, .05, 1, 1))
    fig.savefig(output / "model_accuracy_macro_f1.pdf", bbox_inches="tight")
    fig.savefig(output / "model_accuracy_macro_f1.png", dpi=240, bbox_inches="tight")
    plt.close(fig)


def plot_confusions(predictions: pd.DataFrame, winner: str, output: Path, tasks: tuple[str, ...]) -> None:
    sns.set_theme(style="white", context="paper")
    for section in tasks:
        data = predictions[(predictions.encoder == winner) & (predictions.section == section)]
        labels = sorted(set(data.true_label) | set(data.predicted_label))
        matrix = confusion_matrix(data.true_label, data.predicted_label, labels=labels, normalize="true")
        size = max(7, min(14, .55 * len(labels) + 4))
        fig, axis = plt.subplots(figsize=(size, size * .78))
        sns.heatmap(matrix, cmap="Blues", vmin=0, vmax=1, xticklabels=labels,
                    yticklabels=labels, square=True, cbar_kws={"label": "Row proportion"}, ax=axis)
        axis.set_xlabel("Predicted label")
        axis.set_ylabel("Validated label")
        axis.set_title(f"{section.capitalize()}: {DISPLAY[winner]}")
        axis.tick_params(axis="x", rotation=45)
        axis.tick_params(axis="y", rotation=0)
        fig.tight_layout()
        fig.savefig(output / f"confusion_{section}_{winner}.pdf", bbox_inches="tight")
        fig.savefig(output / f"confusion_{section}_{winner}.png", dpi=240, bbox_inches="tight")
        plt.close(fig)


def write_latex_table(metrics: pd.DataFrame, output: Path) -> None:
    frame = metrics[["model", "section", "observations", "classes", "accuracy",
                     "macro_precision", "macro_recall", "macro_f1"]].copy()
    for column in frame.columns[4:]:
        frame[column] = frame[column].map(lambda value: f"{value:.3f}")
    frame.to_latex(
        output / "model_metrics_table.tex", index=False, escape=True,
        column_format="llrrrrrr",
        caption="Company-grouped classification performance by encoder and disclosure section.",
        label="tab:cdp_text_classification_models",
        longtable=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--labels", type=Path, default=LABELS)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--start-year", type=int, default=2020)
    parser.add_argument("--end-year", type=int, default=2022)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--tasks", nargs="+", choices=TASKS, default=TASKS)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    records = read_jsonl(args.input / "span_records.jsonl.gz")
    details = {str(row["Item ID"]): row for row in read_jsonl(args.labels)}
    selected = [
        (index, row, details[str(row["item_id"])])
        for index, row in enumerate(records)
        if args.start_year <= int(row["year"]) <= args.end_year
    ]
    metrics, predictions, classes = [], [], []
    tasks = tuple(args.tasks)
    for model in MODELS:
        embedding = np.load(args.input / "encoders" / model / "embeddings.npy")
        for section in tasks:
            subset = [(index, row, detail) for index, row, detail in selected if row["goal"] == section]
            indices = np.array([index for index, _, _ in subset])
            rows = [row for _, row, _ in subset]
            y = np.array([target(section, detail) for _, _, detail in subset], dtype=object)
            groups = np.array([row["company"].casefold() for row in rows], dtype=object)
            predicted, probability, learnable = oof_predict(embedding[indices], y, groups, args.folds)
            metrics.append(metric_row(model, section, y, predicted, probability, learnable))
            predictions.extend({
                "encoder": model, "model": DISPLAY[model], "section": section,
                "item_id": row["item_id"], "company": row["company"], "year": row["year"],
                "true_label": truth, "predicted_label": guess,
                "max_probability": confidence, "label_seen_in_training_fold": bool(seen),
            } for row, truth, guess, confidence, seen in zip(rows, y, predicted, probability, learnable))
            report = classification_report(y, predicted, output_dict=True, zero_division=0)
            classes.extend({
                "encoder": model, "model": DISPLAY[model], "section": section,
                "class": label, "precision": values["precision"],
                "recall": values["recall"], "f1": values["f1-score"],
                "support": int(values["support"]),
            } for label, values in report.items() if label not in {"accuracy", "macro avg", "weighted avg"})

    metric_frame = pd.DataFrame(metrics)
    prediction_frame = pd.DataFrame(predictions)
    class_frame = pd.DataFrame(classes)
    metric_frame.to_csv(args.output / "model_section_metrics.csv", index=False)
    prediction_frame.to_csv(args.output / "out_of_fold_predictions.csv.gz", index=False, compression="gzip")
    class_frame.to_csv(args.output / "model_class_metrics.csv", index=False)
    ranking = metric_frame.groupby(["encoder", "model"], as_index=False).agg(
        mean_accuracy=("accuracy", "mean"), mean_macro_f1=("macro_f1", "mean"),
        minimum_macro_f1=("macro_f1", "min"), mean_mcc=("matthews_correlation", "mean"),
    ).sort_values(["mean_macro_f1", "minimum_macro_f1"], ascending=False)
    ranking.to_csv(args.output / "model_ranking.csv", index=False)
    winner = str(ranking.iloc[0].encoder)
    plot_metric_comparison(metric_frame, args.output, tasks)
    plot_confusions(prediction_frame, winner, args.output, tasks)
    write_latex_table(metric_frame, args.output)
    summary = {
        "period": [args.start_year, args.end_year], "selected_encoder": winner,
        "tasks": list(tasks),
        "selection_rule": "highest mean macro F1 across the requested classification tasks",
        "ranking": ranking.to_dict("records"),
        "other_labels": {
            "risk": "Not a risk item; Other or unspecified risk",
            "opportunity": "Not an opportunity item; Other or unspecified opportunity",
            "reduction": "Not a reduction action; Other or unspecified action",
            "engagement": "Context, policy, monitoring, response, and engagement are retained as separate roles",
        },
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

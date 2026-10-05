"""Benchmark supervised and hybrid classifiers for CDP reduction actions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, classification_report, f1_score, matthews_corrcoef
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import normalize
from sklearn.svm import LinearSVC

from src.cdp_classification.embeddings import file_digest, read_jsonl


ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "data" / "outputs" / "cdp_text_clustering" / "cdp_reduction_classification_round2_20261005"
LABELS = ROOT / "data" / "processed" / "cdp_section_datasets" / "benchmark_round2" / "cdp_validation_detail_labels_round2.jsonl.gz"
WORKBOOK = ROOT / "data" / "raw" / "CDP" / "cdp_reduction_training_round_2_validated.xlsx"
OUTPUT = ROOT / "data" / "outputs" / "cdp_text_clustering" / "cdp_reduction_hybrid_benchmark_round2_20261005"
MODELS = ("minilm", "e5_base", "bge_m3", "qwen3_06b", "gte_multilingual", "jina_v3", "e5_large_instruct")
DISPLAY = {
    "minilm": "MiniLM", "e5_base": "E5-base", "bge_m3": "BGE-M3",
    "qwen3_06b": "Qwen3-0.6B", "gte_multilingual": "GTE-multilingual",
    "jina_v3": "Jina-v3", "e5_large_instruct": "E5-large-instruct",
}


def clean(value: object) -> str:
    return "" if pd.isna(value) else " ".join(str(value).split())


def make_text(record: dict, detail: dict, structured: dict[str, str]) -> str:
    review = str(record["review_id"])
    parts = [
        "action " + clean(detail.get("Listed measure")),
        "cdp measure " + structured.get(review, ""),
        "industry " + clean(record.get("industry")),
        "evidence " + clean(record.get("original_evidence")),
    ]
    return " [SEP] ".join(part for part in parts if part.split()[-1:] != [""])


def revised_family(record: dict, detail: dict) -> str:
    """Apply the preregistered second-round taxonomy consolidation."""
    family = clean(record.get("coarse_human_label"))
    if family == "Renewable energy generation":
        return "Renewable electricity"
    if family != "Operational energy efficiency":
        return family

    action = clean(detail.get("Action class")).casefold()
    evidence = clean(record.get("original_evidence")).casefold()
    measure = clean(detail.get("Listed measure")).casefold()
    combined = " ".join((action, measure, evidence))
    keyword_groups = (
        ("Transport and mobility", ("fleet", "vehicle", "driving", "logistics", "transport", "travel", "commut")),
        ("IT and digital infrastructure efficiency", ("data center", "data centre", "server", "comput", "digital", "software", " ict ", "information technology")),
        ("Building energy efficiency", ("lighting", " hvac", "building", "office", "store", "warehouse", "insulation", "heating", "ventilation", "air conditioning", "chiller")),
        ("Industrial energy and process efficiency", ("production", "manufactur", "factory", "plant", "machine", "equipment", "motor", "compressed air", "boiler", "steam", "furnace", "pump", "mine", "process")),
        ("Process gases and refrigerants", ("refrigerant", "fugitive", "leakage", "flaring", "venting")),
        ("Renewable electricity", ("battery", "energy storage", "electricity network", "power network", "grid optim")),
    )
    hits = [label for label, keywords in keyword_groups if any(keyword in combined for keyword in keywords)]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        industry = clean(record.get("industry")).casefold()
        if any(token in industry for token in ("transport", "logistics")):
            return "Transport and mobility"
        if any(token in industry for token in ("manufactur", "materials", "food", "power", "fossil", "infrastructure", "mining")):
            return "Industrial energy and process efficiency"
        if any(token in industry for token in ("services", "retail", "hospitality", "health", "apparel", "finance")):
            return "Building energy efficiency"
    return "Other or unclear operational action"


def vectorize(train_text: list[str], test_text: list[str]):
    word = TfidfVectorizer(
        lowercase=True, strip_accents="unicode", sublinear_tf=True,
        ngram_range=(1, 2), min_df=2, max_df=.995, max_features=50000,
    )
    char = TfidfVectorizer(
        analyzer="char_wb", lowercase=True, strip_accents="unicode", sublinear_tf=True,
        ngram_range=(3, 5), min_df=2, max_features=60000,
    )
    train_word, test_word = word.fit_transform(train_text), word.transform(test_text)
    train_char, test_char = char.fit_transform(train_text), char.transform(test_text)
    return hstack([train_word, train_char], format="csr"), hstack([test_word, test_char], format="csr")


def evaluate_configuration(name: str, texts: list[str], y: np.ndarray, groups: np.ndarray,
                           splits: list[tuple[np.ndarray, np.ndarray]], semantic: np.ndarray | None,
                           semantic_weight: float, class_weight: str | None, c_value: float) -> tuple[dict, list[dict]]:
    predictions = np.empty(len(y), dtype=object)
    scores = np.zeros(len(y), dtype=float)
    for train, test in splits:
        x_train, x_test = vectorize([texts[i] for i in train], [texts[i] for i in test])
        if semantic is not None:
            train_sem = csr_matrix(normalize(semantic[train]) * semantic_weight)
            test_sem = csr_matrix(normalize(semantic[test]) * semantic_weight)
            x_train, x_test = hstack([x_train, train_sem], format="csr"), hstack([x_test, test_sem], format="csr")
        model = LinearSVC(C=c_value, class_weight=class_weight, dual="auto", random_state=42)
        model.fit(x_train, y[train])
        predictions[test] = model.predict(x_test)
        decision = model.decision_function(x_test)
        ordered = np.sort(decision, axis=1)
        scores[test] = ordered[:, -1] - ordered[:, -2]
    metric = {
        "configuration": name,
        "observations": len(y), "classes": len(set(y)),
        "accuracy": accuracy_score(y, predictions),
        "macro_f1": f1_score(y, predictions, average="macro", zero_division=0),
        "weighted_f1": f1_score(y, predictions, average="weighted", zero_division=0),
        "matthews_correlation": matthews_corrcoef(y, predictions),
        "mean_decision_margin": scores.mean(),
    }
    rows = [{"configuration": name, "true_label": truth, "predicted_label": guess,
             "decision_margin": margin, "company": company}
            for truth, guess, margin, company in zip(y, predictions, scores, groups)]
    return metric, rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--labels", type=Path, default=LABELS)
    parser.add_argument("--workbook", type=Path, default=WORKBOOK)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--models", nargs="+", choices=MODELS, default=MODELS)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    records = read_jsonl(args.input / "span_records.jsonl.gz")
    details = {str(row["Item ID"]): row for row in read_jsonl(args.labels)}
    sources = pd.read_excel(args.workbook, sheet_name="Source answers", header=2)
    structured = dict(zip(sources["Review ID"].astype(str), sources["Structured CDP measure"].map(clean)))
    texts = [make_text(row, details[str(row["item_id"])], structured) for row in records]
    y = np.array([revised_family(row, details[str(row["item_id"])]) for row in records], dtype=object)
    groups = np.array([str(row["company"]).casefold() for row in records], dtype=object)
    splits = list(GroupKFold(n_splits=min(args.folds, len(set(groups)))).split(np.zeros(len(y)), y, groups))

    configurations: list[tuple[str, np.ndarray | None, float, str | None, float]] = [
        ("TF-IDF SVM", None, 0.0, None, 1.0),
        ("TF-IDF SVM balanced", None, 0.0, "balanced", 1.0),
    ]
    records_hash = file_digest(args.input / "span_records.jsonl.gz")
    for model in args.models:
        manifest_path = args.input / "encoders" / model / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(
                f"Missing {manifest_path}. Run encode-reduction before benchmarking."
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("sample_sha256") != records_hash:
            raise ValueError(
                f"The {model} embeddings were created for a different sample. "
                "Run encode-reduction again."
            )
        semantic = np.load(args.input / "encoders" / model / "embeddings.npy", allow_pickle=False)
        configurations.extend([
            (f"{DISPLAY[model]} hybrid", semantic, 1.0, None, 1.0),
            (f"{DISPLAY[model]} hybrid balanced", semantic, 1.0, "balanced", 1.0),
        ])

    metrics, predictions = [], []
    for name, semantic, weight, class_weight, c_value in configurations:
        metric, rows = evaluate_configuration(
            name, texts, y, groups, splits, semantic, weight, class_weight, c_value,
        )
        metrics.append(metric)
        predictions.extend(rows)
        print(json.dumps(metric))

    metric_frame = pd.DataFrame(metrics).sort_values(["macro_f1", "accuracy"], ascending=False)
    prediction_frame = pd.DataFrame(predictions)
    metric_frame.to_csv(args.output / "hybrid_model_metrics.csv", index=False)
    prediction_frame.to_csv(args.output / "hybrid_oof_predictions.csv.gz", index=False, compression="gzip")
    winner = str(metric_frame.iloc[0].configuration)
    winner_predictions = prediction_frame[prediction_frame.configuration.eq(winner)]
    report = classification_report(
        winner_predictions.true_label, winner_predictions.predicted_label,
        output_dict=True, zero_division=0,
    )
    class_rows = [{"class": label, "precision": values["precision"], "recall": values["recall"],
                   "f1": values["f1-score"], "support": int(values["support"])}
                  for label, values in report.items() if label not in {"accuracy", "macro avg", "weighted avg"}]
    pd.DataFrame(class_rows).to_csv(args.output / "winner_class_metrics.csv", index=False)

    sns.set_theme(style="whitegrid", context="paper")
    plot = metric_frame.sort_values("accuracy", ascending=True)
    fig, axis = plt.subplots(figsize=(9, max(5, .36 * len(plot))))
    sns.scatterplot(data=plot, x="accuracy", y="configuration", size="macro_f1", hue="macro_f1",
                    palette="viridis", sizes=(50, 180), ax=axis)
    axis.axvline(.80, color="#B91C1C", linestyle="--", linewidth=1, label="80% target")
    axis.set_xlim(0, 1)
    axis.set_xlabel("Company-grouped out-of-fold accuracy")
    axis.set_ylabel("")
    axis.legend(loc="lower right", frameon=True)
    fig.tight_layout()
    fig.savefig(args.output / "hybrid_accuracy_comparison.pdf", bbox_inches="tight")
    fig.savefig(args.output / "hybrid_accuracy_comparison.png", dpi=240, bbox_inches="tight")
    plt.close(fig)
    taxonomy_counts = pd.Series(y).value_counts().sort_index().to_dict()
    summary = {"winner": winner, "target_accuracy": .80, "target_met": bool(metric_frame.iloc[0].accuracy >= .80),
               "taxonomy_changes": [
                   "Merged Renewable energy generation into Renewable electricity",
                   "Reassigned Operational energy efficiency using action and evidence keywords",
                   "Retained Other or unclear operational action for ambiguous cases",
               ],
               "class_counts": taxonomy_counts,
               "ranking": metric_frame.to_dict("records")}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

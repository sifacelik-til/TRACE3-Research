"""Evaluate text and embedding classifiers for CDP risk, engagement, and opportunity items."""

from __future__ import annotations

import argparse
import gzip
import inspect
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score, matthews_corrcoef
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import normalize
from sklearn.svm import LinearSVC


ROOT = Path(__file__).resolve().parents[2]
LABELS = ROOT / "data" / "processed" / "cdp_section_datasets" / "cdp_validation_detail_labels.jsonl.gz"
ANSWERS = ROOT / "data" / "processed" / "cdp_section_datasets" / "cdp_validation_answers.jsonl.gz"
OUTPUT = ROOT / "data" / "outputs" / "cdp_other_sections_hybrid_benchmark_2020_2022"
INPUT = OUTPUT
TASKS = ("risk", "engagement", "opportunity")
MODELS = ("minilm", "e5_base", "bge_m3", "qwen3_06b", "gte_multilingual", "jina_v3", "e5_large_instruct")
DISPLAY = {"minilm": "MiniLM", "e5_base": "E5-base", "bge_m3": "BGE-M3", "qwen3_06b": "Qwen3-0.6B",
           "gte_multilingual": "GTE-multilingual", "jina_v3": "Jina-v3", "e5_large_instruct": "E5-large-instruct"}
MODEL_SPECS = {
    "minilm": (ROOT / "data/models/cdp_encoder_competition/minilm/e8f8c211226b894fcb81acc59f3b34ba3efd5f42", "", False, None),
    "e5_base": (ROOT / "data/models/cdp_encoder_competition/e5/d128750597153bb5987e10b1c3493a34e5a4502a", "query: ", False, None),
    "bge_m3": (ROOT / "data/models/cdp_encoder_competition/bge_m3/5617a9f61b028005a4858fdac845db406aefb181", "", False, None),
    "qwen3_06b": (ROOT / "data/models/cdp_encoder_competition/qwen3/97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3", "Instruct: Classify a corporate climate disclosure.\nQuery: ", False, None),
    "gte_multilingual": (ROOT / "data/models/cdp_action_taxonomy/huggingface/models--Alibaba-NLP--gte-multilingual-base/snapshots/9bbca17d9273fd0d03d5725c7a4b0f6b45142062", "", True, None),
    "jina_v3": (ROOT / "data/models/cdp_action_taxonomy/huggingface/models--jinaai--jina-embeddings-v3/snapshots/ab036b023d30b4d1138c4c3bfa9f0c445ab455d6", "", True, "separation"),
    "e5_large_instruct": (ROOT / "data/models/cdp_action_taxonomy/huggingface/models--intfloat--multilingual-e5-large-instruct/snapshots/274baa43b0e13e37fafa6428dbc7938e62e5c439", "Instruct: Classify a corporate climate disclosure.\nQuery: ", False, None),
}


def read_jsonl(path: Path) -> list[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def clean(value: object) -> str:
    return "" if pd.isna(value) else " ".join(str(value).split())


def norm(value: object) -> str:
    return str(value or "").strip()


def risk_label(row: dict) -> str:
    if norm(row["In-scope risk item?"]).casefold() != "yes": return "Not a risk item"
    value = norm(row["Risk type"]).casefold()
    if "physical" in value and "transition" in value: return "Physical and transition"
    if "acute" in value and "chronic" in value: return "Acute and chronic physical"
    if "acute" in value: return "Acute physical"
    if "chronic" in value: return "Chronic physical"
    if "policy" in value or "legal" in value or "regulat" in value: return "Policy and legal transition"
    if "market" in value or "portfolio" in value: return "Market transition"
    if "technolog" in value: return "Technology transition"
    if "reputation" in value: return "Reputation transition"
    return "Other or unspecified risk"


def opportunity_label(row: dict) -> str:
    if norm(row["In-scope opportunity item?"]).casefold() != "yes": return "Not an opportunity item"
    value, hits = norm(row["Opportunity type"]).casefold(), []
    for token, label in (("products and services", "Products and services"), ("resource efficiency", "Resource efficiency"),
                         ("energy source", "Energy source"), ("resilience", "Resilience"), ("markets", "Markets"),
                         ("financial", "Financial products and services"), ("access to capital", "Access to capital"),
                         ("policy", "Policy incentives")):
        if token in value: hits.append(label)
    hits = list(dict.fromkeys(hits))
    return "Multiple opportunity types" if len(hits) > 1 else hits[0] if hits else "Other or unspecified opportunity"


def target(section: str, row: dict) -> str:
    if section == "risk": return risk_label(row)
    if section == "opportunity": return opportunity_label(row)
    if section == "engagement": return norm(row["Item role"]) or "Other or unspecified engagement"
    raise ValueError(section)


def vectorize(train_text: list[str], test_text: list[str]):
    word = TfidfVectorizer(lowercase=True, strip_accents="unicode", sublinear_tf=True, ngram_range=(1, 2), min_df=2, max_features=50000)
    char = TfidfVectorizer(analyzer="char_wb", lowercase=True, strip_accents="unicode", sublinear_tf=True, ngram_range=(3, 5), min_df=2, max_features=60000)
    train_word, test_word = word.fit_transform(train_text), word.transform(test_text)
    train_char, test_char = char.fit_transform(train_text), char.transform(test_text)
    return hstack([train_word, train_char], format="csr"), hstack([test_word, test_char], format="csr")


def evaluate_configuration(name: str, texts: list[str], y: np.ndarray, groups: np.ndarray,
                           splits: list[tuple[np.ndarray, np.ndarray]], semantic: np.ndarray | None,
                           semantic_weight: float, class_weight: str | None, c_value: float):
    prediction, margins = np.empty(len(y), dtype=object), np.zeros(len(y))
    for train, test in splits:
        x_train, x_test = vectorize([texts[i] for i in train], [texts[i] for i in test])
        if semantic is not None:
            x_train = hstack([x_train, csr_matrix(normalize(semantic[train]) * semantic_weight)], format="csr")
            x_test = hstack([x_test, csr_matrix(normalize(semantic[test]) * semantic_weight)], format="csr")
        model = LinearSVC(C=c_value, class_weight=class_weight, dual="auto", random_state=42).fit(x_train, y[train])
        prediction[test] = model.predict(x_test)
        decision = model.decision_function(x_test)
        ordered = np.sort(decision, axis=1)
        margins[test] = ordered[:, -1] - ordered[:, -2]
    metric = {"configuration": name, "observations": len(y), "classes": len(set(y)),
              "accuracy": accuracy_score(y, prediction), "macro_f1": f1_score(y, prediction, average="macro", zero_division=0),
              "weighted_f1": f1_score(y, prediction, average="weighted", zero_division=0),
              "matthews_correlation": matthews_corrcoef(y, prediction), "mean_decision_margin": margins.mean()}
    rows = [{"configuration": name, "true_label": truth, "predicted_label": guess, "decision_margin": margin, "company": company}
            for truth, guess, margin, company in zip(y, prediction, margins, groups)]
    return metric, rows


def feature_text(record: dict) -> str:
    return " [SEP] ".join((
        "industry " + clean(record.get("industry")),
        "source field " + clean(record.get("source_field")),
        "evidence " + clean(record.get("original_evidence")),
        "context " + clean(record.get("source_context")),
    ))


def prepare_records(labels_path: Path, start_year: int, end_year: int) -> list[dict]:
    answers = {str(row["review_id"]): row for row in read_jsonl(ANSWERS)}
    rows = []
    for detail in read_jsonl(labels_path):
        if detail["section"] not in TASKS or not start_year <= int(detail["Year"]) <= end_year:
            continue
        answer = answers[str(detail["Review ID"])]
        evidence, source = str(detail["Evidence excerpt"]), str(answer["source_text"])
        position = source.find(evidence)
        context = source[max(0, position - 220):position + len(evidence) + 220] if position >= 0 else evidence
        rows.append({"item_id": detail["Item ID"], "goal": detail["section"], "industry": detail["Industry"],
                     "company": detail["Company"], "year": int(detail["Year"]), "source_field": detail["Source field"],
                     "original_evidence": evidence, "source_context": context})
    return rows


def ensure_embeddings(records: list[dict], output: Path) -> dict[str, np.ndarray]:
    from sentence_transformers import SentenceTransformer
    import torch
    texts = [feature_text(row) for row in records]
    result = {}
    for key in MODELS:
        folder = output / "encoders" / key
        matrix_path = folder / "embeddings.npy"
        if matrix_path.exists():
            matrix = np.load(matrix_path, allow_pickle=False)
            if len(matrix) == len(records):
                result[key] = matrix
                continue
        path, prompt, trust_remote_code, task = MODEL_SPECS[key]
        if not (path / "config.json").exists():
            raise FileNotFoundError(f"Local model is missing: {path}")
        folder.mkdir(parents=True, exist_ok=True)
        model = SentenceTransformer(str(path), device="cpu", local_files_only=True,
                                    trust_remote_code=trust_remote_code, model_kwargs={"torch_dtype": torch.float32})
        kwargs = {"batch_size": 16, "normalize_embeddings": True, "convert_to_numpy": True, "show_progress_bar": True}
        if task:
            signature = inspect.signature(model.encode).parameters
            module_kwargs = getattr(model, "module_kwargs", None) or {}
            if "task" in signature or (any(p.kind == inspect.Parameter.VAR_KEYWORD for p in signature.values()) and any("task" in v for v in module_kwargs.values())):
                kwargs["task"] = task
        matrix = model.encode([prompt + text for text in texts], **kwargs).astype("float32")
        np.save(matrix_path, matrix)
        result[key] = matrix
        del model
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--labels", type=Path, default=LABELS)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--start-year", type=int, default=2020)
    parser.add_argument("--end-year", type=int, default=2022)
    parser.add_argument("--folds", type=int, default=5)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    records_path = args.input / "span_records.jsonl.gz"
    if records_path.exists():
        all_records = read_jsonl(records_path)
    else:
        all_records = prepare_records(args.labels, args.start_year, args.end_year)
        args.input.mkdir(parents=True, exist_ok=True)
        with gzip.open(records_path, "wt", encoding="utf-8") as stream:
            for row in all_records:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    details = {str(row["Item ID"]): row for row in read_jsonl(args.labels)}
    embeddings = ensure_embeddings(all_records, args.input)
    all_embeddings = np.hstack([embeddings[model] for model in MODELS])
    metrics, predictions, class_metrics = [], [], []

    for section in TASKS:
        indices = np.array([
            index for index, row in enumerate(all_records)
            if row["goal"] == section and args.start_year <= int(row["year"]) <= args.end_year
        ])
        records = [all_records[index] for index in indices]
        texts = [feature_text(row) for row in records]
        y = np.array([target(section, details[str(row["item_id"])]) for row in records], dtype=object)
        groups = np.array([str(row["company"]).casefold() for row in records], dtype=object)
        splits = list(GroupKFold(n_splits=min(args.folds, len(set(groups)))).split(np.zeros(len(y)), y, groups))
        configurations = [("TF-IDF SVM balanced", None, 1.0)]
        configurations += [(f"{DISPLAY[model]} hybrid", embeddings[model][indices], 1.0) for model in MODELS]
        configurations.append(("All-encoder hybrid", all_embeddings[indices], 4.0))

        section_rows = []
        for name, semantic, weight in configurations:
            metric, rows = evaluate_configuration(
                name, texts, y, groups, splits, semantic, weight, "balanced", 1.0,
            )
            metric["section"] = section
            metrics.append(metric)
            for row, record in zip(rows, records):
                row.update({"section": section, "item_id": record["item_id"], "year": record["year"]})
            predictions.extend(rows)
            section_rows.append(metric)
            print(json.dumps(metric))

        winner = max(section_rows, key=lambda row: (row["macro_f1"], row["accuracy"]))["configuration"]
        winner_rows = [row for row in predictions if row["section"] == section and row["configuration"] == winner]
        report = classification_report(
            [row["true_label"] for row in winner_rows], [row["predicted_label"] for row in winner_rows],
            output_dict=True, zero_division=0,
        )
        class_metrics.extend({
            "section": section, "configuration": winner, "class": label,
            "precision": values["precision"], "recall": values["recall"],
            "f1": values["f1-score"], "support": int(values["support"]),
        } for label, values in report.items() if label not in {"accuracy", "macro avg", "weighted avg"})

        labels = sorted(set(row["true_label"] for row in winner_rows) | set(row["predicted_label"] for row in winner_rows))
        matrix = confusion_matrix(
            [row["true_label"] for row in winner_rows], [row["predicted_label"] for row in winner_rows],
            labels=labels, normalize="true",
        )
        fig, axis = plt.subplots(figsize=(max(8, .65 * len(labels) + 4), max(6, .5 * len(labels) + 3)))
        sns.heatmap(matrix, cmap="Blues", vmin=0, vmax=1, xticklabels=labels, yticklabels=labels,
                    cbar_kws={"label": "Row proportion"}, ax=axis)
        axis.set_title(f"{section.capitalize()}: {winner}")
        axis.set_xlabel("Predicted label")
        axis.set_ylabel("Validated label")
        axis.tick_params(axis="x", rotation=45)
        axis.tick_params(axis="y", rotation=0)
        fig.tight_layout()
        fig.savefig(args.output / f"confusion_{section}.pdf", bbox_inches="tight")
        fig.savefig(args.output / f"confusion_{section}.png", dpi=220, bbox_inches="tight")
        plt.close(fig)

    metric_frame = pd.DataFrame(metrics)
    prediction_frame = pd.DataFrame(predictions)
    class_frame = pd.DataFrame(class_metrics)
    metric_frame.to_csv(args.output / "model_section_metrics.csv", index=False)
    prediction_frame.to_csv(args.output / "out_of_fold_predictions.csv.gz", index=False, compression="gzip")
    class_frame.to_csv(args.output / "winner_class_metrics.csv", index=False)
    winners = metric_frame.sort_values(["section", "macro_f1", "accuracy"], ascending=[True, False, False]).groupby("section").head(1)
    winners.to_csv(args.output / "section_winners.csv", index=False)

    sns.set_theme(style="whitegrid", context="paper")
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharex=True)
    for axis, section in zip(axes, TASKS):
        plot = metric_frame[metric_frame.section.eq(section)].sort_values("accuracy")
        sns.scatterplot(data=plot, x="accuracy", y="configuration", size="macro_f1", hue="macro_f1",
                        palette="viridis", sizes=(50, 180), ax=axis)
        axis.set_title(section.capitalize())
        axis.set_xlim(0, 1)
        axis.set_xlabel("Out-of-fold accuracy")
        axis.set_ylabel("")
        axis.get_legend().remove()
    fig.tight_layout()
    fig.savefig(args.output / "section_model_comparison.pdf", bbox_inches="tight")
    fig.savefig(args.output / "section_model_comparison.png", dpi=240, bbox_inches="tight")
    plt.close(fig)
    summary = {"period": [args.start_year, args.end_year], "folds": args.folds,
               "grouping": "company", "winners": winners.to_dict("records")}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

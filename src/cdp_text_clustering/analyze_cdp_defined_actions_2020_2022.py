"""Classify and summarize all CDP initiative rows for 2020--2022."""

from __future__ import annotations

import argparse
import gzip
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "processed" / "cdp_section_datasets"
DEFAULT_OUTPUT = ROOT / "data" / "outputs" / "cdp_text_clustering" / "cdp_defined_action_analysis_2020_2022"

CATEGORY_TO_FAMILY = {
    "Energy efficiency in buildings": "Building energy efficiency",
    "Energy efficiency in production processes": "Industrial energy and process efficiency",
    "Low-carbon energy consumption": "Renewable electricity",
    "Low-carbon energy generation": "Renewable electricity",
    "Transportation": "Transport and mobility",
    "Company policy or behavioral change": "Planning, governance and finance",
    "Waste reduction and material circularity": "Products, materials and waste",
    "Fugitive emissions reductions": "Process gases and refrigerants",
    "Non-energy industrial process emissions reductions": "Industrial energy and process efficiency",
}

KEYWORD_FAMILIES = (
    (r"data.?cent(?:er|re)|server|telecom|network equipment|digital infrastructure|ict\b|it equipment", "IT and digital infrastructure efficiency"),
    (r"dedicated budget|allocate(?:d)? a budget|climate investment|transition plan|internal carbon", "Planning, governance and finance"),
    (r"(?:factory|production|manufactur|industrial|plant).{0,80}(?:lighting|hvac|heating|cooling|electricity|energy efficiency|equipment)|(?:lighting|hvac|heating|cooling).{0,80}(?:factory|production|manufactur|industrial|plant)", "Industrial energy and process efficiency"),
    (r"carbon capture|ccs|ccu", "Carbon capture"),
    (r"refriger|methane|sf6|fugitive|leak", "Process gases and refrigerants"),
    (r"supplier|customer engagement|employee engagement|incentive", "Engagement and incentives"),
    (r"recycl|reuse|waste|circular|material", "Products, materials and waste"),
    (r"solar|wind|hydro|geothermal|renewable|green electricity|low.carbon electricity", "Renewable electricity"),
    (r"fleet|vehicle|travel|commut|transport|ship|logistic", "Transport and mobility"),
    (r"lighting|hvac|heating|cooling|insulation|building|bems", "Building energy efficiency"),
    (r"process|equipment|machine|compressed air|motor|waste heat|automation", "Industrial energy and process efficiency"),
    (r"measure|monitor|meter|data analy", "Measurement and monitoring"),
    (r"policy|procurement|purchasing|budget|target|planning", "Planning, governance and finance"),
)


def clean(value: object) -> str:
    return "" if pd.isna(value) else re.sub(r"\s+", " ", str(value)).strip()


def classify_family(row: pd.Series) -> tuple[str, str]:
    category = clean(row.initiative_category)
    combined = " ".join(
        clean(row.get(field)) for field in ("initiative_type", "initiative_details")
    ).casefold()
    # Specific text signals override broad questionnaire categories. This is
    # needed for categories such as building efficiency that may contain a
    # data-centre or production-site intervention.
    for pattern, family in KEYWORD_FAMILIES[:3]:
        if re.search(pattern, combined, flags=re.IGNORECASE):
            return family, "text_rule"
    if category in CATEGORY_TO_FAMILY and category != "Company policy or behavioral change":
        return CATEGORY_TO_FAMILY[category], "reported_category"
    for pattern, family in KEYWORD_FAMILIES[3:]:
        if re.search(pattern, combined, flags=re.IGNORECASE):
            return family, "text_rule"
    if category in CATEGORY_TO_FAMILY:
        return CATEGORY_TO_FAMILY[category], "reported_category"
    return "Unclassified", "insufficient_information"


def classify_action_class(value: object) -> tuple[str, str]:
    raw = clean(value)
    if not raw:
        return "Unclassified", ""
    match = re.match(r"Other, please specify\s*:\s*(.+)", raw, flags=re.IGNORECASE)
    if match:
        return "Other specified", match.group(1).strip()
    if raw.casefold() == "other, please specify":
        return "Other specified", ""
    return raw, raw


def read_labels(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def benchmark_against_workbook(initiatives: pd.DataFrame, labels_path: Path,
                               output: Path) -> dict:
    labels = [
        row for row in read_labels(labels_path)
        if row["section"] == "reduction" and row["Counts as action"] == "Yes"
        and 2020 <= int(row["Year"]) <= 2022
    ]
    matches = []
    for label in labels:
        candidates = initiatives[
            initiatives.year.eq(int(label["Year"]))
            & initiatives.company_name.astype(str).str.casefold().eq(str(label["Company"]).casefold())
        ]
        evidence = clean(label["Evidence excerpt"]).casefold()
        exact_answer = candidates[
            candidates.initiative_details.fillna("").astype(str).str.casefold().str.contains(
                re.escape(evidence), regex=True
            )
        ] if evidence else candidates.iloc[0:0]
        if len(exact_answer) == 1:
            source = exact_answer.iloc[0]
            matches.append({
                "item_id": label["Item ID"], "year": int(label["Year"]),
                "company": label["Company"], "gold_action_family": label["Action family"],
                "gold_action_class": label["Action class"],
                "predicted_action_family": source.action_family,
                "predicted_action_class": source.action_class,
                "record_id": source.record_id,
            })
    frame = pd.DataFrame(matches)
    frame.to_csv(output / "workbook_benchmark_matches.csv", index=False)
    if frame.empty:
        return {"validated_items": len(labels), "matched_items": 0}
    gold, predicted = frame.gold_action_family, frame.predicted_action_family
    return {
        "validated_items": len(labels), "matched_items": len(frame),
        "match_coverage": len(frame) / len(labels),
        "action_family_accuracy": accuracy_score(gold, predicted),
        "action_family_macro_precision": precision_score(gold, predicted, average="macro", zero_division=0),
        "action_family_macro_recall": recall_score(gold, predicted, average="macro", zero_division=0),
        "action_family_macro_f1": f1_score(gold, predicted, average="macro", zero_division=0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DATA / "cdp_targets_performance_2016_2025.csv")
    parser.add_argument("--labels", type=Path, default=DATA / "cdp_validation_detail_labels.jsonl.gz")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    parts = []
    for chunk in pd.read_csv(args.input, chunksize=50_000, low_memory=False):
        parts.append(chunk[chunk.year.between(2020, 2022) & chunk.record_type.eq("initiative")])
    frame = pd.concat(parts, ignore_index=True)
    classified = frame.apply(classify_family, axis=1, result_type="expand")
    frame[["action_family", "family_source"]] = classified
    classes = frame.initiative_type.map(classify_action_class)
    frame["action_class"] = classes.map(lambda value: value[0])
    frame["action_class_detail"] = classes.map(lambda value: value[1])
    frame.to_csv(args.output / "cdp_actions_2020_2022_classified.csv.gz", index=False, compression="gzip")

    by_year = frame.groupby(["year", "action_family"], dropna=False).size().rename("initiatives").reset_index()
    by_year["year_share"] = by_year.initiatives / by_year.groupby("year").initiatives.transform("sum")
    by_year.to_csv(args.output / "action_family_by_year.csv", index=False)
    by_sector = frame.groupby(["primary_sector", "action_family"], dropna=False).size().rename("initiatives").reset_index()
    by_sector.to_csv(args.output / "action_family_by_sector.csv", index=False)
    by_class = frame.groupby(["action_family", "action_class"], dropna=False).size().rename("initiatives").reset_index()
    by_class.sort_values(["action_family", "initiatives"], ascending=[True, False]).to_csv(
        args.output / "action_classes_by_family.csv", index=False
    )

    benchmark = benchmark_against_workbook(frame, args.labels, args.output)
    summary = {
        "period": "2020--2022", "initiative_rows": len(frame),
        "companies": int(frame.cdp_account_number.nunique()),
        "classified_share": float(frame.action_family.ne("Unclassified").mean()),
        "reported_category_share": float(frame.family_source.eq("reported_category").mean()),
        "text_rule_share": float(frame.family_source.eq("text_rule").mean()),
        "unclassified_share": float(frame.family_source.eq("insufficient_information").mean()),
        "benchmark": benchmark,
        "family_counts": frame.action_family.value_counts().to_dict(),
    }
    (args.output / "analysis_summary.json").write_text(
        json.dumps(summary, indent=2, default=lambda value: value.item()) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, default=lambda value: value.item()))


if __name__ == "__main__":
    main()

"""Create a balanced CDP reduction-initiative sample for human coding."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "processed" / "cdp_section_datasets" / "cdp_targets_performance_2016_2025.csv"
VALIDATION = ROOT / "data" / "processed" / "cdp_section_datasets" / "cdp_classification_all_details.xlsx"
OUTPUT = ROOT / "data" / "processed" / "cdp_section_datasets" / "reduction_training_round_2.json"

COLUMNS = [
    "Review ID", "Item ID", "Item number", "Industry", "Company", "Year",
    "Source field", "Listed measure", "Action class", "Action family", "Item role",
    "Implementation stage", "Targeted emission scope", "Counterparty", "Evidence excerpt",
    "Coding notes", "Review status", "Source answer cell", "Counts as action",
]


def text(value: object) -> str:
    return "" if pd.isna(value) else str(value).strip()


def compact_measure(row: pd.Series) -> str:
    category, kind = text(row.initiative_category), text(row.initiative_type)
    if category and kind and category.casefold() != kind.casefold():
        return f"{category}: {kind}"
    return kind or category or "Unspecified initiative"


def balanced_sample(frame: pd.DataFrame, per_category: int, seed: int) -> pd.DataFrame:
    frame = frame.copy()
    frame["sample_category"] = frame.initiative_category.fillna("Missing category")
    frame["sample_industry"] = frame.primary_industry.fillna(frame.primary_sector).fillna("Unknown")
    frame["detail_key"] = frame.initiative_details.fillna("").str.casefold().str.replace(r"\s+", " ", regex=True).str.strip()
    frame = frame[frame.detail_key.str.len().ge(20)].drop_duplicates(["company_name", "detail_key"])
    rng = frame.sample(frac=1, random_state=seed)
    chosen = []
    for _, category_rows in rng.groupby("sample_category", sort=True):
        # Round-robin selection prevents large industries from dominating a category.
        groups = [group.to_dict("records") for _, group in category_rows.groupby("sample_industry", sort=True)]
        category_chosen = 0
        while groups and category_chosen < per_category:
            progressed = False
            for group in list(groups):
                if category_chosen >= per_category:
                    break
                if group:
                    chosen.append(group.pop(0))
                    category_chosen += 1
                    progressed = True
                if not group:
                    groups.remove(group)
            if not progressed:
                break
    return pd.DataFrame(chosen)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--validation", type=Path, default=VALIDATION)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--start-year", type=int, default=2020)
    parser.add_argument("--end-year", type=int, default=2022)
    parser.add_argument("--per-category", type=int, default=50)
    parser.add_argument("--seed", type=int, default=20261002)
    args = parser.parse_args()

    usecols = [
        "record_id", "year", "company_name", "primary_sector", "primary_industry",
        "record_type", "question_code", "initiative_category", "initiative_type",
        "initiative_details", "initiative_stage", "scopes",
    ]
    data = pd.read_csv(args.source, usecols=usecols, low_memory=False)
    data = data[data.year.between(args.start_year, args.end_year) & data.record_type.eq("initiative")].copy()

    # Avoid presenting descriptions that have already been coded in the original workbook.
    existing = pd.read_excel(args.validation, sheet_name="Reduction actions", header=2)
    used = set(existing["Evidence excerpt"].dropna().astype(str).str.casefold().str.replace(r"\s+", " ", regex=True).str.strip())
    key = data.initiative_details.fillna("").str.casefold().str.replace(r"\s+", " ", regex=True).str.strip()
    data = data[~key.isin(used)]
    sample = balanced_sample(data, args.per_category, args.seed).reset_index(drop=True)

    rows = []
    for number, row in sample.iterrows():
        review_id = f"RED2-{number + 1:04d}"
        rows.append({
            "Review ID": review_id,
            "Item ID": f"{review_id}-A01",
            "Item number": 1,
            "Industry": text(row.sample_industry),
            "Company": text(row.company_name),
            "Year": int(row.year),
            "Source field": "initiative_details",
            "Listed measure": compact_measure(row),
            "Action class": "",
            "Action family": "",
            "Item role": "",
            "Implementation stage": text(row.initiative_stage),
            "Targeted emission scope": text(row.scopes),
            "Counterparty": "",
            "Evidence excerpt": text(row.initiative_details),
            "Coding notes": "",
            "Review status": "Not reviewed",
            "Source answer cell": text(row.record_id),
            "Counts as action": "",
            "CDP initiative category": text(row.initiative_category),
            "CDP initiative type": text(row.initiative_type),
        })

    payload = {
        "title": "Reduction classification training round 2",
        "period": [args.start_year, args.end_year],
        "rows": rows,
        "columns": COLUMNS,
        "sample_counts": sample.sample_category.value_counts().sort_index().to_dict(),
        "instructions": [
            "Code each row using the same definitions as the original Reduction actions sheet.",
            "Use the evidence excerpt as the primary evidence. The listed measure contains the structured CDP category and type.",
            "Set Counts as action to Yes only when the text identifies a concrete reduction action or enabling intervention.",
            "Use Review status to mark Complete, Needs discussion, or Exclude.",
            "Do not infer implementation, scope, or counterparties when the text does not support them.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"rows": len(rows), "categories": payload["sample_counts"], "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()

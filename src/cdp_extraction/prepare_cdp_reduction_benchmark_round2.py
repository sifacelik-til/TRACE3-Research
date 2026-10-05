"""Merge the validated reduction round with the original CDP benchmark labels."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "processed" / "cdp_section_datasets"
DEFAULT_WORKBOOK = ROOT / "data" / "raw" / "CDP" / "cdp_reduction_training_round_2_validated.xlsx"
DEFAULT_OUTPUT = DATA / "benchmark_round2"


def read_jsonl(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def value(row: pd.Series, column: str) -> str:
    item = row.get(column, "")
    return "" if pd.isna(item) else str(item).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    original_answers = read_jsonl(DATA / "cdp_validation_answers.jsonl.gz")
    original_labels = read_jsonl(DATA / "cdp_validation_detail_labels.jsonl.gz")
    sources = pd.read_excel(args.workbook, sheet_name="Source answers", header=2)
    actions = pd.read_excel(args.workbook, sheet_name="Reduction actions", header=2)

    eligible = actions[
        actions["Training eligible"].astype(str).str.casefold().eq("yes")
        & actions["Counts as action"].astype(str).str.casefold().eq("yes")
        & actions["Review status"].astype(str).str.casefold().eq("complete")
    ].copy()
    source_by_review = sources.set_index("Review ID", drop=False)

    answer_ids = {str(row["review_id"]) for row in original_answers}
    label_ids = {str(row["Item ID"]) for row in original_labels}
    added_answers = []
    for review_id in eligible["Review ID"].astype(str).drop_duplicates():
        if review_id in answer_ids:
            raise ValueError(f"Duplicate review ID: {review_id}")
        row = source_by_review.loc[review_id]
        added_answers.append({
            "review_id": review_id,
            "field_id": value(row, "Source record ID"),
            "section": "reduction",
            "company": value(row, "Company"),
            "industry": value(row, "Industry"),
            "year": int(row["Year"]),
            "source_field": value(row, "Source field"),
            "source_text": value(row, "Complete source text"),
        })

    added_labels = []
    for _, row in eligible.iterrows():
        item_id = value(row, "Item ID")
        if item_id in label_ids:
            raise ValueError(f"Duplicate item ID: {item_id}")
        review_id = value(row, "Review ID")
        source_text = value(source_by_review.loc[review_id], "Complete source text")
        evidence = value(row, "Evidence excerpt")
        if evidence not in source_text:
            raise ValueError(f"Evidence is not verbatim for {item_id}")
        added_labels.append({
            "section": "reduction",
            "Review ID": review_id,
            "Item ID": item_id,
            "Item number": int(row["Item number"]),
            "Industry": value(row, "Industry"),
            "Company": value(row, "Company"),
            "Year": int(row["Year"]),
            "Source field": value(row, "Source field"),
            "Listed measure": value(row, "Listed measure"),
            "Action class": value(row, "Action class"),
            "Action family": value(row, "Action family"),
            "Item role": value(row, "Item role"),
            "Implementation stage": value(row, "Implementation stage"),
            "Targeted emission scope": value(row, "Targeted emission scope"),
            "Counterparty": value(row, "Counterparty"),
            "Evidence excerpt": evidence,
            "Coding notes": value(row, "Coding notes"),
            "Review status": value(row, "Review status"),
            "Source answer cell": value(row, "Source answer cell"),
            "Counts as action": "Yes",
        })

    answers_path = args.output / "cdp_validation_answers_round2.jsonl.gz"
    labels_path = args.output / "cdp_validation_detail_labels_round2.jsonl.gz"
    write_jsonl(answers_path, original_answers + added_answers)
    write_jsonl(labels_path, original_labels + added_labels)
    summary = {
        "original_answers": len(original_answers),
        "added_answers": len(added_answers),
        "original_labels": len(original_labels),
        "added_reduction_labels": len(added_labels),
        "added_companies": int(eligible["Company"].nunique()),
        "added_action_families": int(eligible["Action family"].nunique()),
        "answers": str(answers_path),
        "labels": str(labels_path),
    }
    (args.output / "merge_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

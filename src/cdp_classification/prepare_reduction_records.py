"""Prepare validated reduction-action records for the supervised benchmark."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

from src.cdp_classification.embeddings import clean_classification_text, file_digest, read_jsonl


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "processed" / "cdp_section_datasets"
ANSWERS = DATA / "benchmark_round2" / "cdp_validation_answers_round2.jsonl.gz"
LABELS = DATA / "benchmark_round2" / "cdp_validation_detail_labels_round2.jsonl.gz"
OUTPUT = ROOT / "data" / "outputs" / "cdp_text_clustering" / "cdp_reduction_classification_round2_20261005"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answers", type=Path, default=ANSWERS)
    parser.add_argument("--labels", type=Path, default=LABELS)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--start-year", type=int, default=2020)
    parser.add_argument("--end-year", type=int, default=2022)
    args = parser.parse_args()

    answers = {str(row["review_id"]): row for row in read_jsonl(args.answers)}
    records = []
    for item in read_jsonl(args.labels):
        if item.get("section") != "reduction":
            continue
        year = int(item["Year"])
        if not args.start_year <= year <= args.end_year:
            continue
        if str(item.get("Counts as action", "")).strip().casefold() != "yes":
            continue
        review_id = str(item["Review ID"])
        answer = answers[review_id]
        evidence = str(item["Evidence excerpt"]).strip()
        source_text = str(answer["source_text"])
        if evidence not in source_text:
            raise ValueError(f"Evidence is not verbatim for {item['Item ID']}")
        measure = str(item.get("Listed measure", "")).strip()
        feature_text = f"Action: {measure}. Evidence: {evidence}" if measure else evidence
        company = str(item["Company"])
        records.append({
            "item_id": str(item["Item ID"]),
            "review_id": review_id,
            "goal": "reduction",
            "industry": str(item.get("Industry", "")),
            "company": company,
            "year": year,
            "source_field": str(item.get("Source field", "")),
            "original_evidence": evidence,
            "classification_text": clean_classification_text(feature_text, company),
            "fine_human_label": str(item.get("Action class", "")),
            "coarse_human_label": str(item.get("Action family", "")),
            "implementation_or_horizon": str(item.get("Implementation stage", "")),
        })

    args.output.mkdir(parents=True, exist_ok=True)
    target = args.output / "span_records.jsonl.gz"
    with gzip.open(target, "wt", encoding="utf-8") as stream:
        for row in records:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {
        "period": [args.start_year, args.end_year],
        "records": len(records),
        "companies": len({row["company"].casefold() for row in records}),
        "classes": len({row["coarse_human_label"] for row in records}),
        "records_sha256": file_digest(target),
        "feature_text": "validated listed measure plus item-level evidence excerpt",
    }
    (args.output / "data_manifest.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

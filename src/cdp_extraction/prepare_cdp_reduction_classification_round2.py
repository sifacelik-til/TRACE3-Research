"""Build the 2020--2022 reduction-only classification records for benchmark round 2."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

from src.cdp_text_clustering.benchmark_cdp_action_taxonomy import clean_clustering_text, file_digest, read_jsonl


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "outputs" / "cdp_text_clustering" / "cdp_action_taxonomy_benchmark_round2_20261005"
LABELS = ROOT / "data" / "processed" / "cdp_section_datasets" / "benchmark_round2" / "cdp_validation_detail_labels_round2.jsonl.gz"
OUTPUT = ROOT / "data" / "outputs" / "cdp_text_clustering" / "cdp_reduction_classification_round2_20261005"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--labels", type=Path, default=LABELS)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--start-year", type=int, default=2020)
    parser.add_argument("--end-year", type=int, default=2022)
    args = parser.parse_args()

    labels = {str(row["Item ID"]): row for row in read_jsonl(args.labels)}
    records = []
    for row in read_jsonl(args.source / "span_records.jsonl.gz"):
        if row["goal"] != "reduction" or not args.start_year <= int(row["year"]) <= args.end_year:
            continue
        detail = labels[str(row["item_id"])]
        measure = str(detail.get("Listed measure", "")).strip()
        evidence = str(row["original_evidence"]).strip()
        classification_text = f"Action: {measure}. Evidence: {evidence}" if measure else evidence
        row["clustering_text"] = clean_clustering_text(classification_text, str(row["company"]))
        records.append(row)

    args.output.mkdir(parents=True, exist_ok=True)
    target = args.output / "span_records.jsonl.gz"
    with gzip.open(target, "wt", encoding="utf-8") as stream:
        for row in records:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {
        "period": [args.start_year, args.end_year],
        "records": len(records),
        "companies": len({str(row["company"]).casefold() for row in records}),
        "classes": len({row["coarse_human_label"] for row in records}),
        "records_sha256": file_digest(target),
        "feature_text": "validated listed measure plus item-level evidence excerpt",
    }
    (args.output / "data_manifest.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

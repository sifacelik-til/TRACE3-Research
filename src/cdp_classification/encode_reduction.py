"""Encode the validated reduction-action records with the local models."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.cdp_classification.embeddings import DEFAULT_MODELS, MODEL_SPECS, encode_model, read_jsonl


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "data" / "outputs" / "cdp_text_clustering" / "cdp_reduction_classification_round2_20261005"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--models", nargs="+", choices=sorted(MODEL_SPECS), default=DEFAULT_MODELS)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    records = read_jsonl(args.output / "span_records.jsonl.gz")
    for model in args.models:
        encode_model(model, records, args.output, batch_size=args.batch_size, device=args.device, offline=args.offline)


if __name__ == "__main__":
    main()

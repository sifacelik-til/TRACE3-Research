"""Score two independent coders' review of the CDP clustering sample."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from sklearn.metrics import cohen_kappa_score, precision_recall_fscore_support


FIELDS = (
    "same_operational_action",
    "label_fit",
    "multiple_actions",
    "implementation_not_intention",
    "action_label",
)


def clean(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.casefold()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.input.with_name("human_validation_metrics.json")
    frame = pd.read_csv(args.input)
    results = []
    for field in FIELDS:
        first, second = clean(frame[f"coder1_{field}"]), clean(frame[f"coder2_{field}"])
        mask = first.ne("") & second.ne("")
        if not mask.any():
            results.append({"field": field, "n": 0, "raw_agreement": None, "cohens_kappa": None})
            continue
        results.append({
            "field": field, "n": int(mask.sum()),
            "raw_agreement": float((first[mask] == second[mask]).mean()),
            "cohens_kappa": float(cohen_kappa_score(first[mask], second[mask])),
        })

    # Workbook labels are the external reference for the model's cluster label.
    truth = clean(frame["coarse_human_label"] if "coarse_human_label" in frame else frame["cluster_label"])
    predicted = clean(frame["cluster_label"])
    mask = truth.ne("") & predicted.ne("")
    precision, recall, f1, _ = precision_recall_fscore_support(
        truth[mask], predicted[mask], average="macro", zero_division=0,
    )
    payload = {
        "rows": len(frame), "coder_agreement": results,
        "cluster_label_against_workbook": {
            "n": int(mask.sum()), "macro_precision": float(precision),
            "macro_recall": float(recall), "macro_f1": float(f1),
        },
    }
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    pd.DataFrame(results).to_csv(output.with_suffix(".csv"), index=False)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()

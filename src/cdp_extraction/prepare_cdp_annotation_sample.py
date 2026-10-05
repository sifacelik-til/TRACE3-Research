"""Draw a reproducible human-coding sample from the CDP lexical clusters.

The lexical cluster is a sampling/audit cue, not a human label. Source files are
read-only. Run from the repository root with the project's Python environment.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data/processed/cdp_2016_2024_climate_actions"
OUTPUT_DIR = ROOT / "data/outputs/cdp_extraction/cdp_annotation_2016_2024"
LEXICAL = SOURCE_DIR / "climate_action_risk_opportunity_lexical_clusters.csv.gz"
ENRICHED = SOURCE_DIR / "climate_action_risk_opportunity_records_with_currency.csv.gz"
SEED = 20260929
PER_TYPE = 110
PER_LEXICAL_GROUP = 5
TYPES = ("initiative", "risk", "opportunity")

SOURCE_COLUMNS = [
    "record_id", "record_type", "year", "cdp_account_number", "organization",
    "country", "question_id", "question_row", "source_file", "source_sheet",
    "source_excel_row", "initiative_category_reported", "initiative_type_reported",
    "source_or_driver_reported", "reported_outcome_text", "response_strategy_reported",
    "financial_impact_description", "narrative_for_clustering", "cluster_id",
    "cluster_label", "emissions_boundary_reported", "timeframe_reported",
    "value_chain_position_reported", "estimated_annual_emissions_impact_tco2e",
]


def normalized_text(values: pd.Series) -> pd.Series:
    return values.fillna("").astype(str).str.casefold().str.replace(r"\s+", " ", regex=True).str.strip()


def choose_one(pool: pd.DataFrame, used_ids: set[str], year_counts: dict[int, int], rng: np.random.Generator) -> pd.Series | None:
    available = pool.loc[~pool["record_id"].isin(used_ids)]
    if available.empty:
        return None
    years = available["year"].unique()
    lowest = min(year_counts[int(year)] for year in years)
    candidate_years = [int(year) for year in years if year_counts[int(year)] == lowest]
    year = int(rng.choice(candidate_years))
    candidates = available.loc[available["year"].eq(year)]
    return candidates.iloc[int(rng.integers(0, len(candidates)))]


def draw_sample(frame: pd.DataFrame, seed: int, per_type: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    chosen: list[dict] = []
    for record_type in TYPES:
        subset = frame.loc[frame["record_type"].eq(record_type)]
        years = sorted(int(year) for year in subset["year"].unique())
        year_counts = {year: 0 for year in years}
        used_ids: set[str] = set()
        groups = sorted(subset["sampling_cluster"].unique())

        # Seed every lexical group, including unassigned rows. Favor years with
        # fewer examples without using cluster labels as target labels.
        for group in groups:
            pool = subset.loc[subset["sampling_cluster"].eq(group)]
            for _ in range(PER_LEXICAL_GROUP):
                row = choose_one(pool, used_ids, year_counts, rng)
                if row is None:
                    break
                chosen.append({"record_id": row["record_id"], "sampling_reason": "lexical_group_coverage"})
                used_ids.add(row["record_id"])
                year_counts[int(row["year"])] += 1

        if len(used_ids) > per_type:
            raise ValueError(f"Per-type target {per_type} is too small for lexical coverage")
        while len(used_ids) < per_type:
            row = choose_one(subset, used_ids, year_counts, rng)
            if row is None:
                raise ValueError(f"Insufficient unique narratives for {record_type}")
            chosen.append({"record_id": row["record_id"], "sampling_reason": "year_balance"})
            used_ids.add(row["record_id"])
            year_counts[int(row["year"])] += 1

    selection = pd.DataFrame(chosen)
    result = selection.merge(frame, on="record_id", how="left", validate="one_to_one")
    assert len(result) == per_type * len(TYPES)
    assert result["record_id"].is_unique
    assert not result["narrative_for_clustering"].isna().any()
    return result.sort_values(["record_type", "year", "record_id"]).reset_index(drop=True)


def read_enrichment(selected_ids: set[str]) -> pd.DataFrame:
    fields = ["record_id", "initiative_comment_reported", "reporting_currency_iso"]
    chunks = []
    for chunk in pd.read_csv(ENRICHED, usecols=fields, chunksize=50_000, low_memory=False):
        found = chunk.loc[chunk["record_id"].isin(selected_ids)]
        if not found.empty:
            chunks.append(found)
    result = pd.concat(chunks, ignore_index=True)
    if result["record_id"].duplicated().any():
        raise ValueError("Enriched records contain duplicate selected record IDs")
    return result


def excel_safe(value: object) -> object:
    """Keep externally supplied text from executing as a formula in Excel."""
    if not isinstance(value, str):
        return value
    if re.match(r"^\s*[=+@]", value) or re.match(r"^\s*-[^\d\s]", value):
        return "'" + value
    return value


def prepare(seed: int = SEED, per_type: int = PER_TYPE) -> tuple[Path, Path]:
    if not LEXICAL.exists() or not ENRICHED.exists():
        raise FileNotFoundError("The lexical and enriched CDP extracts must exist")
    frame = pd.read_csv(LEXICAL, usecols=SOURCE_COLUMNS, low_memory=False)
    frame = frame.loc[frame["record_type"].isin(TYPES) & frame["year"].between(2016, 2024)].copy()
    frame["year"] = frame["year"].astype(int)
    frame["narrative_for_clustering"] = frame["narrative_for_clustering"].fillna("")
    frame["narrative_characters"] = frame["narrative_for_clustering"].str.len()
    frame = frame.loc[frame["narrative_characters"].gt(0)].copy()
    frame["sampling_cluster"] = frame["cluster_id"].fillna("unassigned")
    frame["normalized_narrative"] = normalized_text(frame["narrative_for_clustering"])
    # Deduplicate *within response type* to avoid coding identical boilerplate
    # repeatedly. Shuffle first so the retained source record is not always
    # the earliest disclosure year or lowest CDP account number.
    frame = frame.sample(frac=1, random_state=seed).drop_duplicates(
        ["record_type", "normalized_narrative"], keep="first"
    ).drop(columns="normalized_narrative")
    selected = draw_sample(frame, seed=seed, per_type=per_type)
    selected = selected.merge(read_enrichment(set(selected["record_id"])), on="record_id", how="left", validate="one_to_one")
    if selected["reporting_currency_iso"].isna().all():
        raise ValueError("Currency enrichment failed for all selected records")

    group_sizes = pd.read_csv(SOURCE_DIR / "lexical_cluster_summary.csv", usecols=["cluster_id", "records"])
    selected = selected.merge(group_sizes.rename(columns={"records": "lexical_cluster_records"}),
                              on="cluster_id", how="left", validate="many_to_one")
    selected.insert(0, "annotation_id", [f"CDP-{i:04d}" for i in range(1, len(selected) + 1)])
    for field in ["human_primary_label", "human_secondary_labels", "human_evidence_excerpt",
                  "human_coding_notes", "human_ambiguity_flag", "second_coder_primary_label",
                  "adjudicated_primary_label", "lexical_fit_review"]:
        selected[field] = ""

    order = [
        "annotation_id", "record_id", "record_type", "year", "cdp_account_number",
        "organization", "country", "question_id", "initiative_category_reported",
        "initiative_type_reported", "source_or_driver_reported", "reported_outcome_text",
        "financial_impact_description", "response_strategy_reported", "initiative_comment_reported",
        "narrative_for_clustering", "narrative_characters", "human_primary_label",
        "human_secondary_labels", "human_evidence_excerpt", "human_coding_notes",
        "human_ambiguity_flag", "second_coder_primary_label", "adjudicated_primary_label",
        "sampling_reason", "sampling_cluster", "cluster_id", "cluster_label",
        "lexical_cluster_records", "lexical_fit_review", "emissions_boundary_reported",
        "timeframe_reported", "value_chain_position_reported", "reporting_currency_iso",
        "estimated_annual_emissions_impact_tco2e", "source_file", "source_sheet",
        "source_excel_row", "question_row",
    ]
    output = selected[order].copy()
    for column in output.columns:
        if pd.api.types.is_string_dtype(output[column]) or pd.api.types.is_object_dtype(output[column]):
            output[column] = output[column].map(excel_safe)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sample_path = OUTPUT_DIR / "cdp_annotation_sample.csv"
    output.to_csv(sample_path, index=False, encoding="utf-8-sig")

    summary = output.groupby(["record_type", "year"], as_index=False).agg(
        sampled_records=("record_id", "size"),
        distinct_accounts=("cdp_account_number", "nunique"),
        lexical_groups=("sampling_cluster", "nunique"),
    )
    summary_path = OUTPUT_DIR / "sample_balance.csv"
    summary.to_csv(summary_path, index=False)
    return sample_path, summary_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--per-type", type=int, default=PER_TYPE)
    args = parser.parse_args()
    sample_file, summary_file = prepare(seed=args.seed, per_type=args.per_type)
    print(f"Annotation sample: {sample_file}")
    print(f"Balance summary: {summary_file}")

"""Count firms observed repeatedly in the three- and four-source samples.

From the project root::

    python -m src.dataset_readers.company_panel_persistence

The first run builds a filtered 2016--2025 company-year membership cache using
the same rules as plot_company_year_venn.py. Later runs reuse it. Pass --refresh
to rebuild the cache after changing source data or filters.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from src.dataset_readers.plot_company_year_venn import OUTPUT_DIR, SOURCES, load_members  # noqa: E402


YEARS = tuple(range(2016, 2026))
WINDOWS = (
    (2016, 2024),
    (2016, 2025),
    (2020, 2025),
    (2019, 2024),
    (2019, 2025),
)
PRESENCE_PATH = OUTPUT_DIR / "company_year_source_presence_2016_2025.csv.gz"
SUMMARY_PATH = OUTPUT_DIR / "company_panel_persistence_summary.csv"
DETAIL_PATH = OUTPUT_DIR / "company_panel_persistence_by_firm.csv.gz"
AMBIGUOUS_PATH = OUTPUT_DIR / "ambiguous_factset_id_matches_2016_2025.csv"


def build_presence() -> pd.DataFrame:
    sets, factset_ids = load_members(years=YEARS, return_factset_ids=True)
    by_firm_year = defaultdict(lambda: {source.lower(): False for source in SOURCES})
    ambiguous = []

    for item in sets["FactSet"]:
        entity_ids = factset_ids.get(item, set())
        if len(entity_ids) != 1:
            ambiguous.append({
                "year": item[0],
                "name_key": item[1],
                "factset_entity_ids": "|".join(sorted(entity_ids)),
                "number_of_factset_ids": len(entity_ids),
            })
            continue
        entity_id = next(iter(entity_ids))
        flags = by_firm_year[(entity_id, item[0])]
        for source in SOURCES:
            flags[source.lower()] |= item in sets[source]

    presence = pd.DataFrame(
        [
            {"factset_entity_id": entity_id, "year": year, **flags}
            for (entity_id, year), flags in by_firm_year.items()
        ]
    )
    if presence.empty:
        raise RuntimeError("No unambiguous FactSet company-years were matched.")
    presence["cdp_trucost_factset"] = (
        presence["cdp"] & presence["trucost"] & presence["factset"]
    )
    presence["cdp_trucost_factset_lseg"] = (
        presence["cdp_trucost_factset"] & presence["lseg"]
    )
    presence = presence.sort_values(["factset_entity_id", "year"]).reset_index(drop=True)
    ambiguous_frame = pd.DataFrame(
        ambiguous,
        columns=["year", "name_key", "factset_entity_ids", "number_of_factset_ids"],
    )
    if not ambiguous_frame.empty:
        ambiguous_frame = ambiguous_frame.sort_values(["year", "name_key"])
    ambiguous_frame.to_csv(AMBIGUOUS_PATH, index=False)
    presence.to_csv(PRESENCE_PATH, index=False, compression="gzip")
    print(
        f"Saved {len(presence):,} FactSet company-years; "
        f"excluded {len(ambiguous):,} ambiguous name/ISIN matches."
    )
    return presence


def summarize(presence: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    outcomes = ("cdp_trucost_factset", "cdp_trucost_factset_lseg")
    details = []
    summary = []
    for start, end in WINDOWS:
        years = set(range(start, end + 1))
        window = f"{start}-{end}"
        selected = presence.loc[presence["year"].between(start, end)]
        grouped = selected.groupby("factset_entity_id", sort=False)
        window_rows = []
        for entity_id, firm in grouped:
            outcome_years = {
                outcome: sorted(set(firm.loc[firm[outcome], "year"].astype(int)))
                for outcome in outcomes
            }
            window_rows.append({
                "window": window,
                "factset_entity_id": entity_id,
                "years_in_window": len(years),
                "cdp_trucost_factset_years": len(outcome_years[outcomes[0]]),
                "cdp_trucost_factset_missing_years": "|".join(
                    str(year) for year in sorted(years - set(outcome_years[outcomes[0]]))
                ),
                "cdp_trucost_factset_lseg_years": len(outcome_years[outcomes[1]]),
                "cdp_trucost_factset_lseg_missing_years": "|".join(
                    str(year) for year in sorted(years - set(outcome_years[outcomes[1]]))
                ),
            })
        window_details = pd.DataFrame(window_rows)
        details.append(window_details)
        for allowed_missing in (0, 1, 2):
            minimum_years = len(years) - allowed_missing
            summary.append({
                "window": window,
                "coverage_rule": (
                    "Every year" if allowed_missing == 0
                    else f"At most {allowed_missing} missing year"
                    + ("s" if allowed_missing != 1 else "")
                ),
                "years_in_window": len(years),
                "allowed_missing_years": allowed_missing,
                "minimum_years_present": minimum_years,
                "CDP_Trucost_FactSet_companies": int(
                    window_details["cdp_trucost_factset_years"].ge(minimum_years).sum()
                ),
                "CDP_Trucost_FactSet_LSEG_companies": int(
                    window_details["cdp_trucost_factset_lseg_years"].ge(minimum_years).sum()
                ),
            })
    return pd.DataFrame(summary), pd.concat(details, ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="Rescan sources and rebuild company-year cache")
    args = parser.parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.refresh or not PRESENCE_PATH.exists():
        presence = build_presence()
    else:
        presence = pd.read_csv(
            PRESENCE_PATH,
            compression="gzip",
            dtype={
                "factset_entity_id": "string",
                **{source.lower(): "boolean" for source in SOURCES},
                "cdp_trucost_factset": "boolean",
                "cdp_trucost_factset_lseg": "boolean",
            },
        )
    for column in ("cdp_trucost_factset", "cdp_trucost_factset_lseg"):
        if column not in presence:
            raise KeyError(f"The cached membership file lacks {column}; rerun with --refresh.")
    summary, details = summarize(presence)
    summary.to_csv(SUMMARY_PATH, index=False)
    details.to_csv(DETAIL_PATH, index=False, compression="gzip")
    print(summary.to_string(index=False))
    print(f"Saved summary: {SUMMARY_PATH}")
    print(f"Saved firm-level coverage: {DETAIL_PATH}")


if __name__ == "__main__":
    main()

"""Create company-year state variables and yearly revenue statistics."""

from pathlib import Path
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from data_engine.common_companies_by_year import find_common_companies


OUTPUT_FILE = PROJECT_ROOT / "data/processed/mdp_state_variables_by_year.xlsx"
STATE_YEARS = range(2022, 2023)

STATE_COLUMNS = [
    "year",
    "organization",
    "isin",
    "trucost_company_id",
    "lseg_instrument",
    "factset_entity_id",
    "current_emissions",
    "emissions_intensity",
    "revenue",
    "esg_score",
    "carbon_price_internal",
    "energy_mix_renewable_pct",
    "target_ambition",
    "target_coverage",
    "verification_status",
    "policy_adoption",
    "cdp_emissions",
    "cdp_target",
    "cdp_renewable_pct",
    "num_suppliers",
    "suppliers_with_targets_pct",
    "suppliers_disclosing_pct",
    "suppliers_emissions",
    "suppliers_emissions_intensity",
    "suppliers_renewable_pct",
    "suppliers_engagement_level",
    "suppliers_high_emission_pct",
    "suppliers_diversification",
    "suppliers_geographic_risk",
    "suppliers_contract_length",
]


def find_column(
    df: pd.DataFrame, candidates: list[str], required: bool = True
) -> str | None:
    lookup = {str(column).strip().casefold(): column for column in df.columns}
    for candidate in candidates:
        column = lookup.get(candidate.casefold())
        if column is not None:
            return column
    if required:
        raise KeyError(
            f"None of {candidates} were found. Available columns: "
            f"{list(df.columns)}"
        )
    return None


def load_company_states() -> pd.DataFrame:
    companies = find_common_companies(years=STATE_YEARS)
    year_column = find_column(companies, ["year", "fiscalyear", "fiscal_year"])
    name_column = find_column(
        companies,
        ["trucost_name", "trucost_companyname", "organization"],
    )
    revenue_column = find_column(
        companies,
        ["revenue", "trucost_revenue", "di_319522", "Trucost Total Revenue"],
    )

    rename_columns = {
        year_column: "year",
        name_column: "organization",
    }
    if revenue_column != "revenue":
        rename_columns[revenue_column] = "revenue"
    states = companies.rename(columns=rename_columns)
    states["year"] = pd.to_numeric(states["year"], errors="coerce")
    numeric_columns = [
        "current_emissions",
        "emissions_intensity",
        "revenue",
        "esg_score",
        "carbon_price_internal",
        "energy_mix_renewable_pct",
        "target_coverage",
        "policy_adoption",
        "cdp_emissions",
        "cdp_renewable_pct",
        "num_suppliers",
        "suppliers_with_targets_pct",
        "suppliers_disclosing_pct",
        "suppliers_emissions",
        "suppliers_emissions_intensity",
        "suppliers_renewable_pct",
        "suppliers_high_emission_pct",
        "suppliers_diversification",
        "suppliers_geographic_risk",
        "suppliers_contract_length",
    ]
    for column in numeric_columns:
        if column in states.columns:
            states[column] = pd.to_numeric(states[column], errors="coerce")
    states = states.dropna(subset=["year"])
    states["year"] = states["year"].astype(int)

    for column in STATE_COLUMNS:
        if column not in states.columns:
            states[column] = pd.NA

    return (
        states[STATE_COLUMNS]
        .drop_duplicates(["year", "isin"])
        .sort_values(["year", "organization", "isin"], na_position="last")
        .reset_index(drop=True)
    )


def calculate_yearly_statistics(states: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year, group in states.groupby("year", sort=True):
        revenue = group["revenue"].dropna()
        rows.append(
            {
                "year": year,
                "company_states": len(group),
                "companies_with_revenue": revenue.count(),
                "companies_without_revenue": group["revenue"].isna().sum(),
                "revenue_coverage_pct": (
                    revenue.count() / len(group) * 100 if len(group) else 0
                ),
                "revenue_total": revenue.sum(),
                "revenue_mean": revenue.mean(),
                "revenue_median": revenue.median(),
                "revenue_std": revenue.std(),
                "revenue_min": revenue.min(),
                "revenue_q1": revenue.quantile(0.25),
                "revenue_q3": revenue.quantile(0.75),
                "revenue_max": revenue.max(),
            }
        )
    return pd.DataFrame(rows)


def write_yearly_document(
    states: pd.DataFrame, statistics: pd.DataFrame
) -> None:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        statistics.to_excel(writer, sheet_name="yearly_statistics", index=False)
        states.to_excel(writer, sheet_name="all_states", index=False)
        for year, group in states.groupby("year", sort=True):
            group.to_excel(writer, sheet_name=str(year), index=False)


def main() -> None:
    states = load_company_states()
    statistics = calculate_yearly_statistics(states)
    write_yearly_document(states, statistics)
    print(statistics.to_string(index=False))
    print(f"\nSaved {len(states):,} company-year states to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

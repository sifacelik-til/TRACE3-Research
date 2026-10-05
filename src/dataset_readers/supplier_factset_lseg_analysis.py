"""Build supplier metrics from the matched panel, FactSet, and LSEG.

The analysis intentionally uses no questionnaire or disclosure source. FactSet
defines Tier-1 supplier relationships and supplier sectors. FactSet's
REVENUE_PCT is retained as a relationship-importance proxy, not procurement
spend. LSEG supplies ESG and policy fields through FactSet entity-to-ISIN
mapping. Trucost emissions come only from the supplied matched panel.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PANEL_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "trucost_lseg_factset_matched_2015_2025.csv.gz"
)
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT / "data" / "processed" / "supplier_factset_lseg"
)
FACTSET_ROOT = PROJECT_ROOT / "data" / "raw" / "FactSet"
RELATIONSHIP_PATH = (
    FACTSET_ROOT
    / "ent_supply_chain_v1_full_3856"
    / "ent_scr_relationships.txt"
)
ENTITY_PATH = (
    FACTSET_ROOT / "sym_entity_v1_full_12328" / "sym_entity.txt"
)
ENTITY_SECTOR_PATH = (
    FACTSET_ROOT
    / "sym_entity_v1_full_12328"
    / "sym_entity_sector.txt"
)
INDUSTRY_MAP_PATH = (
    FACTSET_ROOT
    / "ref_hub_v2_full_3565"
    / "factset_industry_map.txt"
)
SECTOR_MAP_PATH = (
    FACTSET_ROOT
    / "ref_hub_v2_full_3565"
    / "factset_sector_map.txt"
)
COUNTRY_MAP_PATH = (
    FACTSET_ROOT / "ref_hub_v2_full_3565" / "country_map.txt"
)
REGION_MAP_PATH = (
    FACTSET_ROOT / "ref_hub_v2_full_3565" / "region_map.txt"
)
SECURITY_ENTITY_PATH = (
    FACTSET_ROOT
    / "ent_supply_chain_hub_v1_full_3858"
    / "ent_scr_sec_entity.txt"
)
ISIN_PATH = (
    FACTSET_ROOT / "sym_isin_v1_full_11256" / "sym_isin.txt"
)
LSEG_PATH = PROJECT_ROOT / "data" / "raw" / "LSEG" / "lseg_full_universe.csv"

CHUNK_SIZE = 100_000
UNCLASSIFIED = "Not Classified"
LSEG_POLICY_COLUMNS = {
    "Policy Emissions": "policy_emissions",
    "Policy Energy Efficiency": "policy_energy_efficiency",
    "Policy Environmental Supply Chain": "policy_environmental_supply_chain",
    "Policy Sustainable Packaging": "policy_sustainable_packaging",
    "Renewable/Clean Energy Products": "policy_clean_energy",
    "Take-back and Recycling Initiatives": "take_back_recycling",
    "Hybrid Vehicles": "hybrid_vehicles",
    "Eco-Design Products": "eco_design",
    "CSR Sustainability Reporting": "sustainability_reporting",
    "Targets Energy Efficiency": "target_energy_efficiency",
    "Transition Plan Offsets": "transition_plan_offsets",
    "Internal Carbon Pricing": "internal_carbon_policy",
    "Environmental Supply Chain Monitoring": (
        "environmental_supply_chain_monitoring"
    ),
    "Environmental Supply Chain Management": (
        "environmental_supply_chain_management"
    ),
    "Environmental Materials Sourcing": "environmental_materials_sourcing",
    "ISO 14000 or EMS": "iso_14000_or_ems",
}
PANEL_SUPPLIER_COLUMNS = [
    "trucost_company_id",
    "trucost_name",
    "scope_1_emissions",
    "scope_2_emissions",
    "scope_2_location_based_emissions",
    "scope_2_market_based_emissions",
]


def clean_identifier(values: pd.Series) -> pd.Series:
    return values.astype("string").str.strip().str.strip('"')


def normalize_isin(values: pd.Series) -> pd.Series:
    return (
        values.astype("string")
        .str.upper()
        .str.replace(r"[^A-Z0-9]", "", regex=True)
    )


def first_present(values: pd.Series) -> object:
    present = values.dropna()
    if present.empty:
        return pd.NA
    strings = present.astype("string").str.strip()
    strings = strings[strings.ne("")]
    return strings.iloc[0] if not strings.empty else pd.NA


def nullable_max(values: pd.Series) -> object:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return numeric.max() if not numeric.empty else pd.NA


def binary_values(values: pd.Series) -> pd.Series:
    normalized = values.astype("string").str.strip().str.casefold()
    result = pd.Series(pd.NA, index=values.index, dtype="Int64")
    result.loc[normalized.isin({"yes", "true", "1", "y"})] = 1
    result.loc[normalized.isin({"no", "false", "0", "n"})] = 0
    return result


def read_panel(panel_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    policy_outputs = list(LSEG_POLICY_COLUMNS.values())
    usecols = [
        "year",
        "isin",
        "factset_entity_id",
        "factset_name",
        "lseg_name",
        "lseg_instrument",
        *PANEL_SUPPLIER_COLUMNS,
        *policy_outputs,
    ]
    header = pd.read_csv(panel_path, compression="gzip", nrows=0)
    missing = set(usecols).difference(header.columns)
    if missing:
        raise ValueError(
            f"{panel_path} is missing required columns: {sorted(missing)}"
        )

    panel = pd.read_csv(
        panel_path,
        compression="gzip",
        usecols=usecols,
        low_memory=False,
    )
    panel["year"] = pd.to_numeric(panel["year"], errors="coerce").astype("Int64")
    panel["factset_entity_id"] = clean_identifier(
        panel["factset_entity_id"]
    )
    panel = panel[
        panel["year"].notna()
        & panel["factset_entity_id"].notna()
        & panel["factset_entity_id"].ne("")
    ].copy()
    panel["year"] = panel["year"].astype(int)

    company_rows = []
    for (year, company_id), group in panel.groupby(
        ["year", "factset_entity_id"], sort=False
    ):
        company_rows.append(
            {
                "year": year,
                "company_id": company_id,
                "company_name": first_present(group["factset_name"]),
                "company_isins": " | ".join(
                    sorted(
                        set(
                            normalize_isin(group["isin"])
                            .dropna()
                            .loc[lambda value: value.ne("")]
                        )
                    )
                ),
            }
        )
    companies = pd.DataFrame(company_rows)

    supplier_rows = []
    for (year, supplier_id), group in panel.groupby(
        ["year", "factset_entity_id"], sort=False
    ):
        row: dict[str, object] = {
            "year": year,
            "supplier_id": supplier_id,
            "supplier_in_trucost": group["trucost_company_id"].notna().any(),
            "supplier_trucost_name": first_present(group["trucost_name"]),
        }
        for column in PANEL_SUPPLIER_COLUMNS[2:]:
            row[f"supplier_trucost_{column}"] = pd.to_numeric(
                group[column], errors="coerce"
            ).median()
        supplier_rows.append(row)
    supplier_trucost = pd.DataFrame(supplier_rows)
    return companies, supplier_trucost


def load_active_relationships(companies: pd.DataFrame) -> pd.DataFrame:
    company_years = companies[["company_id", "year"]].drop_duplicates()
    company_ids = set(company_years["company_id"])
    usecols = [
        "REL_TYPE",
        "SOURCE_FACTSET_ENTITY_ID",
        "TARGET_FACTSET_ENTITY_ID",
        "START_DATE",
        "END_DATE",
        "REVENUE_PCT",
    ]
    parts = []
    reader = pd.read_csv(
        RELATIONSHIP_PATH,
        sep="|",
        usecols=usecols,
        dtype=str,
        encoding="latin-1",
        chunksize=CHUNK_SIZE,
        low_memory=False,
    )
    for chunk in reader:
        chunk["REL_TYPE"] = clean_identifier(chunk["REL_TYPE"]).str.upper()
        chunk["TARGET_FACTSET_ENTITY_ID"] = clean_identifier(
            chunk["TARGET_FACTSET_ENTITY_ID"]
        )
        chunk = chunk[
            chunk["REL_TYPE"].eq("SUPPLIER")
            & chunk["TARGET_FACTSET_ENTITY_ID"].isin(company_ids)
        ].copy()
        if chunk.empty:
            continue
        chunk = chunk.rename(
            columns={
                "SOURCE_FACTSET_ENTITY_ID": "supplier_id",
                "TARGET_FACTSET_ENTITY_ID": "company_id",
                "START_DATE": "relationship_start",
                "END_DATE": "relationship_end",
                "REVENUE_PCT": "relationship_revenue_pct",
            }
        )
        chunk["supplier_id"] = clean_identifier(chunk["supplier_id"])
        chunk = chunk[chunk["supplier_id"].ne("")]
        chunk["relationship_start"] = pd.to_datetime(
            chunk["relationship_start"], errors="coerce"
        )
        chunk["relationship_end"] = pd.to_datetime(
            chunk["relationship_end"], errors="coerce"
        )
        chunk["relationship_revenue_pct"] = pd.to_numeric(
            chunk["relationship_revenue_pct"], errors="coerce"
        )
        chunk.loc[
            chunk["relationship_revenue_pct"].le(0),
            "relationship_revenue_pct",
        ] = np.nan

        expanded = chunk.merge(company_years, on="company_id", how="inner")
        year_start = pd.to_datetime(expanded["year"].astype(str) + "-01-01")
        year_end = pd.to_datetime(expanded["year"].astype(str) + "-12-31")
        expanded = expanded[
            (
                expanded["relationship_start"].isna()
                | expanded["relationship_start"].le(year_end)
            )
            & (
                expanded["relationship_end"].isna()
                | expanded["relationship_end"].ge(year_start)
            )
        ].copy()
        if not expanded.empty:
            parts.append(expanded)

    if not parts:
        return pd.DataFrame()
    relationships = pd.concat(parts, ignore_index=True)
    relationships["contract_length_years"] = (
        relationships["relationship_end"]
        - relationships["relationship_start"]
    ).dt.total_seconds().div(365.25 * 24 * 60 * 60)
    relationships.loc[
        relationships["contract_length_years"].lt(0),
        "contract_length_years",
    ] = np.nan
    return (
        relationships.sort_values(
            ["year", "company_id", "supplier_id", "relationship_start"],
            ascending=[True, True, True, False],
            na_position="last",
        )
        .drop_duplicates(["year", "company_id", "supplier_id"], keep="first")
        .reset_index(drop=True)
    )


def load_supplier_attributes(supplier_ids: set[str]) -> pd.DataFrame:
    attribute_parts = []
    for chunk in pd.read_csv(
        ENTITY_PATH,
        sep="|",
        usecols=[
            "FACTSET_ENTITY_ID",
            "ENTITY_PROPER_NAME",
            "ISO_COUNTRY",
            "ENTITY_TYPE",
        ],
        dtype=str,
        encoding="latin-1",
        chunksize=CHUNK_SIZE,
        low_memory=False,
    ):
        chunk["FACTSET_ENTITY_ID"] = clean_identifier(
            chunk["FACTSET_ENTITY_ID"]
        )
        selected = chunk[chunk["FACTSET_ENTITY_ID"].isin(supplier_ids)].copy()
        if not selected.empty:
            attribute_parts.append(selected)
    attributes = (
        pd.concat(attribute_parts, ignore_index=True)
        if attribute_parts
        else pd.DataFrame(columns=["FACTSET_ENTITY_ID"])
    )
    attributes = attributes.drop_duplicates("FACTSET_ENTITY_ID", keep="first")

    sector_parts = []
    for chunk in pd.read_csv(
        ENTITY_SECTOR_PATH,
        sep="|",
        usecols=["FACTSET_ENTITY_ID", "INDUSTRY_CODE", "SECTOR_CODE"],
        dtype=str,
        encoding="latin-1",
        chunksize=CHUNK_SIZE,
        low_memory=False,
    ):
        chunk["FACTSET_ENTITY_ID"] = clean_identifier(
            chunk["FACTSET_ENTITY_ID"]
        )
        selected = chunk[chunk["FACTSET_ENTITY_ID"].isin(supplier_ids)].copy()
        if not selected.empty:
            sector_parts.append(selected)
    sectors = (
        pd.concat(sector_parts, ignore_index=True)
        if sector_parts
        else pd.DataFrame(columns=["FACTSET_ENTITY_ID"])
    )
    sectors = sectors.drop_duplicates("FACTSET_ENTITY_ID", keep="first")

    industry_map = pd.read_csv(
        INDUSTRY_MAP_PATH,
        sep="|",
        dtype=str,
        encoding="latin-1",
        low_memory=False,
    ).rename(
        columns={
            "FACTSET_INDUSTRY_CODE": "INDUSTRY_CODE",
            "FACTSET_INDUSTRY_DESC": "supplier_industry",
        }
    )
    sector_map = pd.read_csv(
        SECTOR_MAP_PATH,
        sep="|",
        dtype=str,
        encoding="latin-1",
        low_memory=False,
    ).rename(
        columns={
            "FACTSET_SECTOR_CODE": "SECTOR_CODE",
            "FACTSET_SECTOR_DESC": "supplier_sector",
        }
    )
    country_map = pd.read_csv(
        COUNTRY_MAP_PATH,
        sep="|",
        dtype=str,
        encoding="latin-1",
        low_memory=False,
    ).rename(columns={"COUNTRY_DESC": "supplier_country_name"})
    region_map = pd.read_csv(
        REGION_MAP_PATH,
        sep="|",
        dtype=str,
        encoding="latin-1",
        low_memory=False,
    ).rename(columns={"REGION_DESC": "supplier_region"})
    output = attributes.merge(sectors, on="FACTSET_ENTITY_ID", how="outer")
    output = output.merge(
        industry_map[["INDUSTRY_CODE", "supplier_industry"]],
        on="INDUSTRY_CODE",
        how="left",
    )
    output = output.merge(
        sector_map[["SECTOR_CODE", "supplier_sector"]],
        on="SECTOR_CODE",
        how="left",
    )
    output = output.merge(
        country_map[
            ["ISO_COUNTRY", "supplier_country_name", "REGION_CODE"]
        ],
        on="ISO_COUNTRY",
        how="left",
    )
    output = output.merge(
        region_map[["REGION_CODE", "supplier_region"]],
        on="REGION_CODE",
        how="left",
    )
    return output.rename(
        columns={
            "FACTSET_ENTITY_ID": "supplier_id",
            "ENTITY_PROPER_NAME": "supplier_name",
            "ISO_COUNTRY": "supplier_country",
            "ENTITY_TYPE": "supplier_entity_type",
            "INDUSTRY_CODE": "supplier_industry_code",
            "SECTOR_CODE": "supplier_sector_code",
            "REGION_CODE": "supplier_region_code",
        }
    )


def load_supplier_isins(supplier_ids: set[str]) -> pd.DataFrame:
    security_entities = pd.read_csv(
        SECURITY_ENTITY_PATH,
        sep="|",
        dtype=str,
        encoding="latin-1",
        low_memory=False,
    )
    security_entities["FACTSET_ENTITY_ID"] = clean_identifier(
        security_entities["FACTSET_ENTITY_ID"]
    )
    security_entities = security_entities[
        security_entities["FACTSET_ENTITY_ID"].isin(supplier_ids)
    ].copy()
    if security_entities.empty:
        return pd.DataFrame(columns=["supplier_id", "supplier_isin"])

    isins = pd.read_csv(
        ISIN_PATH,
        sep="|",
        dtype=str,
        encoding="latin-1",
        low_memory=False,
    )
    mapped = security_entities.merge(isins, on="FSYM_ID", how="inner")
    mapped["ISIN"] = normalize_isin(mapped["ISIN"])
    return (
        mapped[
            mapped["ISIN"].str.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", na=False)
        ][["FACTSET_ENTITY_ID", "ISIN"]]
        .rename(
            columns={
                "FACTSET_ENTITY_ID": "supplier_id",
                "ISIN": "supplier_isin",
            }
        )
        .drop_duplicates()
    )


def load_supplier_lseg(
    supplier_isins: pd.DataFrame, years: set[int]
) -> pd.DataFrame:
    if supplier_isins.empty:
        return pd.DataFrame(columns=["year", "supplier_id"])
    wanted_isins = set(supplier_isins["supplier_isin"])
    header = pd.read_csv(LSEG_PATH, nrows=0)
    esg_columns = [
        column for column in ["ESG Score", "LSEG ESG Score"]
        if column in header.columns
    ]
    usecols = [
        "FiscalYear",
        "ISIN",
        "Instrument",
        "Company Common Name",
        *esg_columns,
        *LSEG_POLICY_COLUMNS,
    ]
    parts = []
    for chunk in pd.read_csv(
        LSEG_PATH,
        usecols=usecols,
        chunksize=CHUNK_SIZE,
        low_memory=False,
    ):
        chunk["year"] = pd.to_numeric(
            chunk["FiscalYear"], errors="coerce"
        ).astype("Int64")
        chunk["supplier_isin"] = normalize_isin(chunk["ISIN"])
        chunk = chunk[
            chunk["year"].isin(years)
            & chunk["supplier_isin"].isin(wanted_isins)
        ].copy()
        if chunk.empty:
            continue
        esg = pd.Series(np.nan, index=chunk.index)
        for column in esg_columns:
            esg = esg.fillna(pd.to_numeric(chunk[column], errors="coerce"))
        chunk["supplier_esg_score"] = esg
        for source, output in LSEG_POLICY_COLUMNS.items():
            chunk[output] = binary_values(chunk[source])
        parts.append(
            chunk[
                [
                    "year",
                    "supplier_isin",
                    "Company Common Name",
                    "Instrument",
                    "supplier_esg_score",
                    *LSEG_POLICY_COLUMNS.values(),
                ]
            ]
        )
    if not parts:
        return pd.DataFrame(columns=["year", "supplier_id"])

    lseg = pd.concat(parts, ignore_index=True).merge(
        supplier_isins, on="supplier_isin", how="inner"
    )
    aggregation: dict[str, object] = {
        "supplier_isin": lambda values: " | ".join(
            sorted(set(values.dropna().astype(str)))
        ),
        "Company Common Name": first_present,
        "Instrument": lambda values: " | ".join(
            sorted(set(values.dropna().astype(str)))
        ),
        "supplier_esg_score": "median",
    }
    aggregation.update(
        {column: nullable_max for column in LSEG_POLICY_COLUMNS.values()}
    )
    output = (
        lseg.groupby(["year", "supplier_id"], as_index=False)
        .agg(aggregation)
        .rename(
            columns={
                "Company Common Name": "supplier_lseg_name",
                "Instrument": "supplier_lseg_instruments",
            }
        )
    )
    output["supplier_in_lseg"] = True
    return output


def build_sector_composition(detail: pd.DataFrame) -> pd.DataFrame:
    work = detail.copy()
    work["supplier_sector"] = work["supplier_sector"].fillna(UNCLASSIFIED)
    total = work.groupby(["year", "company_id"])["supplier_id"].transform(
        "nunique"
    )
    composition = (
        work.groupby(
            ["year", "company_id", "supplier_sector"], as_index=False
        )
        .agg(
            supplier_count=("supplier_id", "nunique"),
            relationship_revenue_proxy_sum=(
                "relationship_revenue_pct",
                "sum",
            ),
        )
    )
    totals = (
        work[["year", "company_id"]]
        .assign(total_tier_1_suppliers=total)
        .drop_duplicates(["year", "company_id"])
    )
    composition = composition.merge(
        totals, on=["year", "company_id"], how="left"
    )
    composition["supplier_count_pct"] = (
        100
        * composition["supplier_count"]
        / composition["total_tier_1_suppliers"]
    )
    revenue_totals = composition.groupby(
        ["year", "company_id"]
    )["relationship_revenue_proxy_sum"].transform("sum")
    composition["supplier_revenue_proxy_pct"] = np.where(
        revenue_totals.gt(0),
        100
        * composition["relationship_revenue_proxy_sum"]
        / revenue_totals,
        np.nan,
    )
    return composition


def build_category_composition(
    detail: pd.DataFrame, column: str, output_column: str
) -> pd.DataFrame:
    work = detail[["year", "company_id", "supplier_id", column]].copy()
    work[column] = work[column].fillna(UNCLASSIFIED)
    composition = (
        work.groupby(["year", "company_id", column], as_index=False)
        .agg(supplier_count=("supplier_id", "nunique"))
        .rename(columns={column: output_column})
    )
    totals = composition.groupby(
        ["year", "company_id"]
    )["supplier_count"].transform("sum")
    composition["supplier_count_pct"] = (
        100 * composition["supplier_count"] / totals
    )
    return composition


def category_profile(
    group: pd.DataFrame, column: str, limit: int = 5
) -> tuple[object, float, str]:
    counts = (
        group.assign(
            _category=group[column].fillna(UNCLASSIFIED).astype(str)
        )
        .groupby("_category")["supplier_id"]
        .nunique()
        .sort_values(ascending=False)
    )
    if counts.empty:
        return pd.NA, np.nan, ""
    total = counts.sum()
    dominant = counts.index[0]
    dominant_pct = 100 * counts.iloc[0] / total
    profile = "; ".join(
        f"{category}: {100 * count / total:.1f}%"
        for category, count in counts.head(limit).items()
    )
    return dominant, dominant_pct, profile


def build_policy_summary(detail: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (year, company_id), group in detail.groupby(
        ["year", "company_id"], sort=False
    ):
        total = group["supplier_id"].nunique()
        for policy in LSEG_POLICY_COLUMNS.values():
            observed = pd.to_numeric(group[policy], errors="coerce").notna()
            adopted = pd.to_numeric(
                group.loc[observed, policy], errors="coerce"
            ).eq(1)
            observed_count = int(observed.sum())
            adopted_count = int(adopted.sum())
            rows.append(
                {
                    "year": year,
                    "company_id": company_id,
                    "policy": policy,
                    "tier_1_supplier_count": total,
                    "suppliers_with_policy_observed": observed_count,
                    "suppliers_adopting_policy": adopted_count,
                    "adoption_pct_among_observed": (
                        100 * adopted_count / observed_count
                        if observed_count
                        else np.nan
                    ),
                    "adoption_pct_of_all_tier_1_suppliers": (
                        100 * adopted_count / total if total else np.nan
                    ),
                }
            )
    return pd.DataFrame(rows)


def build_company_summary(detail: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (year, company_id), group in detail.groupby(
        ["year", "company_id"], sort=False
    ):
        supplier_count = group["supplier_id"].nunique()
        lseg_count = int(group["supplier_in_lseg"].fillna(False).sum())
        trucost_count = int(group["supplier_in_trucost"].fillna(False).sum())
        revenue_observed = group["relationship_revenue_pct"].notna().sum()
        dominant_sector, dominant_sector_pct, sector_profile = (
            category_profile(group, "supplier_sector")
        )
        dominant_industry, dominant_industry_pct, industry_profile = (
            category_profile(group, "supplier_industry")
        )
        dominant_country, dominant_country_pct, country_profile = (
            category_profile(group, "supplier_country_name")
        )
        dominant_region, dominant_region_pct, region_profile = (
            category_profile(group, "supplier_region")
        )
        dominant_entity_type, dominant_entity_type_pct, entity_type_profile = (
            category_profile(group, "supplier_entity_type")
        )
        row: dict[str, object] = {
            "year": year,
            "company_id": company_id,
            "number_of_tier_1_suppliers": supplier_count,
            "number_of_supplier_sectors": group["supplier_sector"].nunique(
                dropna=True
            ),
            "suppliers_with_sector_count": group[
                "supplier_sector"
            ].notna().sum(),
            "number_of_supplier_industries": group[
                "supplier_industry"
            ].nunique(dropna=True),
            "number_of_supplier_countries": group[
                "supplier_country"
            ].nunique(dropna=True),
            "number_of_supplier_regions": group[
                "supplier_region"
            ].nunique(dropna=True),
            "suppliers_with_country_count": group[
                "supplier_country"
            ].notna().sum(),
            "suppliers_with_region_count": group[
                "supplier_region"
            ].notna().sum(),
            "dominant_supplier_sector": dominant_sector,
            "dominant_supplier_sector_pct": dominant_sector_pct,
            "supplier_sector_profile_top5": sector_profile,
            "dominant_supplier_industry": dominant_industry,
            "dominant_supplier_industry_pct": dominant_industry_pct,
            "supplier_industry_profile_top5": industry_profile,
            "dominant_supplier_country": dominant_country,
            "dominant_supplier_country_pct": dominant_country_pct,
            "supplier_country_profile_top5": country_profile,
            "dominant_supplier_region": dominant_region,
            "dominant_supplier_region_pct": dominant_region_pct,
            "supplier_region_profile": region_profile,
            "dominant_supplier_entity_type": dominant_entity_type,
            "dominant_supplier_entity_type_pct": dominant_entity_type_pct,
            "supplier_entity_type_profile": entity_type_profile,
            "suppliers_in_lseg_count": lseg_count,
            "suppliers_in_lseg_pct": (
                100 * lseg_count / supplier_count
                if supplier_count
                else np.nan
            ),
            "suppliers_with_esg_score_count": group[
                "supplier_esg_score"
            ].notna().sum(),
            "supplier_esg_score_mean": group["supplier_esg_score"].mean(),
            "supplier_esg_score_median": group["supplier_esg_score"].median(),
            "suppliers_in_trucost_count": trucost_count,
            "suppliers_in_trucost_pct": (
                100 * trucost_count / supplier_count
                if supplier_count
                else np.nan
            ),
            "suppliers_with_revenue_proxy_count": revenue_observed,
            "supplier_revenue_proxy_coverage_pct": (
                100 * revenue_observed / supplier_count
                if supplier_count
                else np.nan
            ),
            "average_supplier_contract_duration_years": group[
                "contract_length_years"
            ].mean(),
        }
        for metric in [
            "supplier_trucost_scope_1_emissions",
            "supplier_trucost_scope_2_emissions",
            "supplier_trucost_scope_2_location_based_emissions",
            "supplier_trucost_scope_2_market_based_emissions",
        ]:
            values = pd.to_numeric(group[metric], errors="coerce")
            row[f"{metric}_observed_count"] = values.notna().sum()
            row[f"{metric}_sum"] = values.sum(min_count=1)
            row[f"{metric}_mean"] = values.mean()
            row[f"{metric}_median"] = values.median()
        rows.append(row)
    return pd.DataFrame(rows)


def build_year_summary(detail: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year, group in detail.groupby("year", sort=True):
        unique_suppliers = group.drop_duplicates("supplier_id")
        rows.append(
            {
                "year": year,
                "companies_with_factset_suppliers": group[
                    "company_id"
                ].nunique(),
                "company_supplier_relationships": len(group),
                "unique_tier_1_suppliers": unique_suppliers[
                    "supplier_id"
                ].nunique(),
                "unique_suppliers_in_lseg": unique_suppliers[
                    "supplier_in_lseg"
                ].fillna(False).sum(),
                "unique_suppliers_in_trucost": unique_suppliers[
                    "supplier_in_trucost"
                ].fillna(False).sum(),
                "supplier_esg_score_mean": unique_suppliers[
                    "supplier_esg_score"
                ].mean(),
                "supplier_esg_score_median": unique_suppliers[
                    "supplier_esg_score"
                ].median(),
            }
        )
    return pd.DataFrame(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze Tier-1 suppliers using only the matched panel, FactSet, "
            "and LSEG."
        )
    )
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for path in [
        args.panel,
        RELATIONSHIP_PATH,
        ENTITY_PATH,
        ENTITY_SECTOR_PATH,
        INDUSTRY_MAP_PATH,
        SECTOR_MAP_PATH,
        COUNTRY_MAP_PATH,
        REGION_MAP_PATH,
        SECURITY_ENTITY_PATH,
        ISIN_PATH,
        LSEG_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(path)

    print("Reading matched company panel...")
    companies, supplier_trucost = read_panel(args.panel)
    print("Reading active FactSet supplier relationships...")
    detail = load_active_relationships(companies)
    if detail.empty:
        raise ValueError("No active supplier relationships matched the panel.")

    supplier_ids = set(detail["supplier_id"])
    years = set(detail["year"].astype(int))
    print(f"Enriching {len(supplier_ids):,} unique FactSet suppliers...")
    attributes = load_supplier_attributes(supplier_ids)
    supplier_isins = load_supplier_isins(supplier_ids)
    print("Reading supplier ESG and policies from LSEG...")
    supplier_lseg = load_supplier_lseg(supplier_isins, years)

    detail = detail.merge(attributes, on="supplier_id", how="left")
    detail = detail.merge(
        supplier_lseg, on=["year", "supplier_id"], how="left"
    )
    detail = detail.merge(
        supplier_trucost, on=["year", "supplier_id"], how="left"
    )
    detail["supplier_in_lseg"] = detail["supplier_in_lseg"].fillna(False)
    detail["supplier_in_trucost"] = detail[
        "supplier_in_trucost"
    ].fillna(False)
    detail = detail.merge(companies, on=["year", "company_id"], how="left")

    company_summary = build_company_summary(detail).merge(
        companies, on=["year", "company_id"], how="left"
    )
    sector_composition = build_sector_composition(detail).merge(
        companies, on=["year", "company_id"], how="left"
    )
    industry_composition = build_category_composition(
        detail, "supplier_industry", "supplier_industry"
    ).merge(companies, on=["year", "company_id"], how="left")
    country_composition = build_category_composition(
        detail, "supplier_country_name", "supplier_country"
    ).merge(companies, on=["year", "company_id"], how="left")
    region_composition = build_category_composition(
        detail, "supplier_region", "supplier_region"
    ).merge(companies, on=["year", "company_id"], how="left")
    entity_type_composition = build_category_composition(
        detail, "supplier_entity_type", "supplier_entity_type"
    ).merge(companies, on=["year", "company_id"], how="left")
    policy_summary = build_policy_summary(detail).merge(
        companies, on=["year", "company_id"], how="left"
    )
    policy_wide = policy_summary.pivot(
        index=["year", "company_id"],
        columns="policy",
        values="adoption_pct_among_observed",
    ).add_prefix("suppliers_").add_suffix("_adoption_pct")
    policy_wide.columns.name = None
    company_summary = company_summary.merge(
        policy_wide.reset_index(), on=["year", "company_id"], how="left"
    )
    year_summary = build_year_summary(detail)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    detail.to_csv(
        args.output_dir / "company_year_supplier_detail.csv.gz",
        index=False,
        compression="gzip",
    )
    company_summary.to_csv(
        args.output_dir / "company_year_supplier_summary.csv", index=False
    )
    sector_composition.to_csv(
        args.output_dir / "company_year_supplier_sector_composition.csv",
        index=False,
    )
    industry_composition.to_csv(
        args.output_dir / "company_year_supplier_industry_composition.csv",
        index=False,
    )
    country_composition.to_csv(
        args.output_dir / "company_year_supplier_country_composition.csv",
        index=False,
    )
    region_composition.to_csv(
        args.output_dir / "company_year_supplier_region_composition.csv",
        index=False,
    )
    entity_type_composition.to_csv(
        args.output_dir / "company_year_supplier_entity_type_composition.csv",
        index=False,
    )
    policy_summary.to_csv(
        args.output_dir / "company_year_supplier_policy_summary.csv",
        index=False,
    )
    year_summary.to_csv(
        args.output_dir / "supplier_coverage_by_year.csv", index=False
    )
    print(
        f"Saved {len(detail):,} company-year-supplier rows for "
        f"{company_summary['company_id'].nunique():,} companies to "
        f"{args.output_dir}"
    )


if __name__ == "__main__":
    main()

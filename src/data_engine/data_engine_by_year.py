from pathlib import Path
import argparse
import csv
import re
from tempfile import TemporaryDirectory
import unicodedata

import pandas as pd
import pyreadstat
from rapidfuzz import fuzz, process
from typing import Optional

try:
    from .cdp_read import (
        extract_many_from_2024_parquet,
        extract_many_from_legacy_xlsx,
        parse_year_file,
    )
except ImportError:
    from cdp_read import (
        extract_many_from_2024_parquet,
        extract_many_from_legacy_xlsx,
        parse_year_file,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TRUCOST_RAW_PATH = (
    PROJECT_ROOT
    / "data/raw/Trucost (Access through WRDS)/trucost_2026_new.dta"
)
LSEG_RAW_PATH = PROJECT_ROOT / "data/raw/LSEG/lseg_full_universe.csv"
FACTSET_RAW_PATH = (
    PROJECT_ROOT / "data/raw/FactSet/sym_entity_v1_full_12328/sym_entity.txt"
)
FACTSET_RELATIONSHIP_PATH = (
    PROJECT_ROOT
    / "data/raw/FactSet/ent_supply_chain_v1_full_3856/ent_scr_relationships.txt"
)
FACTSET_SECTOR_PATH = (
    PROJECT_ROOT
    / "data/raw/FactSet/sym_entity_v1_full_12328/sym_entity_sector.txt"
)
# CDP_FACTSET_BRIDGE_PATH = (

CDP_RAW_ROOT = PROJECT_ROOT / "data/raw/CDP"
OUTPUT_PATH = PROJECT_ROOT / "data/processed/common_companies_by.csv"

LSEG_FUZZY_THRESHOLD = 85.0
FACTSET_FUZZY_THRESHOLD = 85.0
CDP_FUZZY_THRESHOLD = 85.0
WIDE_CSV_CHUNK_SIZE = 250
STATA_CHUNK_SIZE = 5_000
YEAR_CHUNK_SIZE = 250
FACTSET_CHUNK_SIZE = 50_000
FUZZY_CACHE_SIZE = 250_000
HIGH_CARBON_RISK_COUNTRIES = {
    "CN",
    "ID",
    "IN",
    "KZ",
    "MN",
    "PL",
    "VN",
    "ZA",
}

TOKEN_MAP = {
    "co": "company",
    "corp": "corporation",
    "ltd": "limited",
}
BLOCK_STOP_WORDS = {
    "and",
    "company",
    "corporation",
    "group",
    "holding",
    "holdings",
    "inc",
    "incorporated",
    "limited",
    "llc",
    "plc",
    "sa",
    "the",
}


def find_column(
    df: pd.DataFrame, candidates: list[str], required: bool = True
) -> str | None:
    lookup = {str(column).strip().casefold(): column for column in df.columns}
    for candidate in candidates:
        if candidate.casefold() in lookup:
            return lookup[candidate.casefold()]
    if required:
        raise KeyError(
            f"None of {candidates} were found. Available columns: {list(df.columns)}"
        )
    return None


def find_columns(df: pd.DataFrame, candidates: list[str]) -> list[str]:
    lookup = {str(column).strip().casefold(): column for column in df.columns}
    return [
        lookup[candidate.casefold()]
        for candidate in candidates
        if candidate.casefold() in lookup
    ]


def normalize_name(value: object) -> str:
    if pd.isna(value):
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = text.encode("ascii", "ignore").decode("ascii").casefold()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(TOKEN_MAP.get(token, token) for token in text.split())


def normalize_isin(value: object) -> str:
    if pd.isna(value):
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def is_valid_isin(isin: str) -> bool:
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", isin):
        return False

    digits = "".join(
        str(ord(character) - 55) if character.isalpha() else character
        for character in isin
    )
    total = 0
    for index, digit in enumerate(reversed(digits)):
        number = int(digit)
        if index % 2 == 1:
            number *= 2
        total += number // 10 + number % 10
    return total % 10 == 0


def blocking_keys(name_key: object) -> tuple[str, ...]:
    name_key = normalize_name(name_key)
    if not name_key:
        return ()
    tokens = {
        token
        for token in name_key.split()
        if len(token) >= 4 and token not in BLOCK_STOP_WORDS
    }
    if not tokens:
        tokens = {token for token in name_key.split() if len(token) >= 3}
    return tuple(sorted({token[:4] for token in tokens}))


def read_selected_csv(
    path: Path,
    columns: list[str],
    sep: str = ",",
    encoding: str | None = None,
) -> pd.DataFrame:
    parts = []
    options = {
        "sep": sep,
        "usecols": columns,
        "dtype": str,
        "chunksize": WIDE_CSV_CHUNK_SIZE,
        "low_memory": False,
    }
    if encoding:
        options["encoding"] = encoding

    try:
        for chunk in pd.read_csv(path, **options):
            parts.append(chunk)
    except UnicodeDecodeError:
        if encoding:
            raise
        options["encoding"] = "latin-1"
        parts.clear()
        for chunk in pd.read_csv(path, **options):
            parts.append(chunk)

    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=columns)


def read_selected_stata(path: Path, columns: list[str]):
    return (
        chunk
        for chunk, _ in pyreadstat.read_file_in_chunks(
            pyreadstat.read_dta,
            str(path),
            usecols=columns,
            apply_value_formats=False,
            formats_as_category=False,
            user_missing=False,
            chunksize=STATA_CHUNK_SIZE,
        )
    )


def numeric_column(
    chunk: pd.DataFrame, column: str | None
) -> pd.Series:
    if column is None:
        return pd.Series(float("nan"), index=chunk.index)
    return pd.to_numeric(chunk[column], errors="coerce")


def coalesce_numeric_columns(
    chunk: pd.DataFrame, columns: list[str]
) -> pd.Series:
    if not columns:
        return pd.Series(float("nan"), index=chunk.index)
    values = pd.concat(
        [numeric_column(chunk, column) for column in columns],
        axis=1,
    )
    return values.bfill(axis=1).iloc[:, 0]


def sum_numeric_columns(
    chunk: pd.DataFrame, columns: list[str]
) -> pd.Series:
    if not columns:
        return pd.Series(float("nan"), index=chunk.index)
    return pd.concat(
        [numeric_column(chunk, column) for column in columns],
        axis=1,
    ).sum(axis=1, min_count=1)


def binary_column(
    chunk: pd.DataFrame, column: str | None
) -> pd.Series:
    if column is None:
        return pd.Series(pd.NA, index=chunk.index, dtype="Int64")
    values = chunk[column].astype("string").str.strip().str.casefold()
    result = pd.Series(pd.NA, index=chunk.index, dtype="Int64")
    result[values.isin({"yes", "true", "1", "y"})] = 1
    result[values.isin({"no", "false", "0", "n"})] = 0
    return result


def iter_lseg(
    requested_years: set[int] | None = None,
):
    lseg_header = pd.read_csv(LSEG_RAW_PATH, nrows=0)
    lseg_year = find_column(lseg_header, ["FiscalYear", "fiscal_year", "year"])
    lseg_name = find_column(
        lseg_header, ["Company Common Name", "company_name", "companyname"]
    )
    lseg_sector = find_column(
        lseg_header, ["NAICS International Industry Name", "NAICS Sector Name"]
    )
    lseg_isin = find_column(lseg_header, ["ISIN", "isin"])
    lseg_instrument = find_column(
        lseg_header, ["Instrument", "instrument", "RIC"], required=False
    )
    # Financials
    revenue_columns = find_columns(
        lseg_header, ["Revenue", "Total Revenue", "EU Taxonomy Total Revenue Amount"]
    )
    inventory_turnover_columns = find_columns(
        lseg_header, ["Inventory Turnover"]
    )
    number_of_employees_columns = find_columns(
        lseg_header, ["Number of Employees"]
    )
    gross_profit_columns = find_columns(
        lseg_header, ["Gross Profit"]
    )
    operating_profit_columns = find_columns(
        lseg_header, ["Operating Profit"]
    )
    # ESG and policies
    esg_columns = find_columns(
        lseg_header, ["ESG Score", "LSEG ESG Score"]
    )
    policy_emissions_columns = find_columns(
        lseg_header, ["Policy Emissions"]
    )
    carbon_price_columns = find_columns(
        lseg_header,
        ["Internal Carbon Pricing", "Internal Carbon Price per Tonne"],
    )
    renewable_total_columns = find_columns(
        lseg_header,
        ["Energy Use Total", "Total Renewable Energy", "Renewable Energy Use"],
    )
    renewable_component_columns = find_columns(
        lseg_header,
        [
            "Renewable Energy Purchased",
            "Renewable Energy Produced",
            "Electricity Produced from Other Renewables",
        ],
    )
    energy_use_columns = find_columns(
        lseg_header,
        ["Energy Use Total", "Total Energy Use from Properties"],
    )
    target_ambition_column = find_column(
        lseg_header, ["Emissions Target Type"], required=False
    )
    target_coverage_columns = find_columns(
        lseg_header,
        ["Long Term Set 1 Percentage of GHG Emission Covered by Target"],
    )
    verification_column = find_column(
        lseg_header, ["CSR Sustainability External Audit"], required=False
    )
    policy_columns = [
        find_column(lseg_header, [name], required=False)
        for name in [
            "Climate Policy Statement",
            "Policy Emissions",
            "Policy Energy Efficiency",
            "Resource Reduction Policy",
            "Policy Environmental Supply Chain",
            "Policy Sustainable Packaging",
            "Renewable/Clean Energy Products",
            "Take-back and Recycling Initiatives",
            "Hybrid Vehicles",
            "Percentage of Green Products",
            "Environmental Products",
            "Eco-Design Products",
            "CSR Sustainability Reporting",
            "Targets Energy Efficiency",
            "Transition Plan Offsets",
            "Internal Carbon Pricing",
            "Climate Change Risks and Opportunities Strategy",
            "Supplier Environmental Commitment",
            "Supplier Environmental Policy Communication",
            "Supplier Environmental Policy Training",
            "Supplier Environmental Risk Assessment",
            "Environmental Supply Chain Management",
            "Environmental Supply Chain Monitoring",
            "Env Supply Chain Partnership Termination",
            "Environmental Materials Sourcing",
            "ISO 14000 or EMS",
        ]
    ]

    lseg_columns = list(
        dict.fromkeys(
            column
            for column in [
                lseg_year,
                lseg_sector,
                lseg_name,
                lseg_isin,
                lseg_instrument,
                *revenue_columns,
                *inventory_turnover_columns,
                *number_of_employees_columns,
                *gross_profit_columns,
                *operating_profit_columns,
                *esg_columns,
                *policy_emissions_columns,
                *carbon_price_columns,
                *renewable_total_columns,
                *renewable_component_columns,
                *energy_use_columns,
                target_ambition_column,
                *target_coverage_columns,
                verification_column,
                *policy_columns,
            ]
            if column
        )
    )
    records = []
    with LSEG_RAW_PATH.open(
        "r", encoding="utf-8-sig", errors="replace", newline=""
    ) as source:
        reader = csv.DictReader(source)
        for row in reader:
            if requested_years is not None:
                row_year = pd.to_numeric(row.get(lseg_year), errors="coerce")
                if pd.isna(row_year) or int(row_year) not in requested_years:
                    continue
            records.append({column: row.get(column) for column in lseg_columns})
            if len(records) < WIDE_CSV_CHUNK_SIZE:
                continue
            chunk = pd.DataFrame.from_records(records, columns=lseg_columns)
            records.clear()
            yield transform_lseg_chunk(
                chunk,
                lseg_year,
                lseg_sector,
                lseg_name,
                lseg_isin,
                lseg_instrument,
                revenue_columns,
                esg_columns,
                carbon_price_columns,
                renewable_total_columns,
                renewable_component_columns,
                energy_use_columns,
                target_ambition_column,
                target_coverage_columns,
                verification_column,
                policy_columns,
            )

        if records:
            chunk = pd.DataFrame.from_records(records, columns=lseg_columns)
            yield transform_lseg_chunk(
                chunk,
                lseg_year,
                lseg_sector,
                lseg_name,
                lseg_isin,
                lseg_instrument,
                revenue_columns,
                esg_columns,
                carbon_price_columns,
                renewable_total_columns,
                renewable_component_columns,
                energy_use_columns,
                target_ambition_column,
                target_coverage_columns,
                verification_column,
                policy_columns,
            )


def transform_lseg_chunk(
    chunk: pd.DataFrame,
    lseg_year: str,
    lseg_sector: str,
    lseg_name: str,
    lseg_isin: str,
    lseg_instrument: str | None,
    revenue_columns: list[str],
    esg_columns: list[str],
    carbon_price_columns: list[str],
    renewable_total_columns: list[str],
    renewable_component_columns: list[str],
    energy_use_columns: list[str],
    target_ambition_column: str | None,
    target_coverage_columns: list[str],
    verification_column: str | None,
    policy_columns: list[str | None],
) -> pd.DataFrame:
    # Existing logic for renewable_pct, policy_adoption, etc.
    renewable_energy = coalesce_numeric_columns(
        chunk, renewable_total_columns
    ).fillna(sum_numeric_columns(chunk, renewable_component_columns))
    total_energy = coalesce_numeric_columns(chunk, energy_use_columns)
    renewable_pct = renewable_energy.div(total_energy).mul(100)
    renewable_pct = renewable_pct.where(total_energy > 0)

    policy_flags = [
        binary_column(chunk, column)
        for column in policy_columns
        if column is not None
    ]
    policy_adoption = (
        pd.concat(policy_flags, axis=1).sum(axis=1, min_count=1)
        if policy_flags
        else pd.Series(pd.NA, index=chunk.index, dtype="Int64")
    )

    # Extract all requested LSEG columns
    lseg = pd.DataFrame(
        {
            "year": pd.to_numeric(chunk[lseg_year], errors="coerce"),
            "lseg_instrument": (
                chunk[lseg_instrument].astype("string")
                if lseg_instrument
                else pd.NA
            ),
            "lseg_name": chunk[lseg_name].astype("string").str.strip(),
            "lseg_isin": chunk[lseg_isin].map(normalize_isin),
            "lseg_sector": chunk[lseg_sector].astype("string").str.strip() if lseg_sector else pd.NA,
            "lseg_revenue": coalesce_numeric_columns(chunk, revenue_columns),
            "inventory_turnover": coalesce_numeric_columns(chunk, find_columns(chunk, ["Inventory Turnover"])),
            "number_of_employees": coalesce_numeric_columns(chunk, find_columns(chunk, ["Number of Employees"])),
            "gross_profit": coalesce_numeric_columns(chunk, find_columns(chunk, ["Gross Profit"])),
            "operating_profit": coalesce_numeric_columns(chunk, find_columns(chunk, ["Operating Profit"])),
            "esg_score": coalesce_numeric_columns(chunk, esg_columns),
            "policy_emissions": binary_column(chunk, find_column(chunk, ["Policy Emissions"], required=False)),
            "carbon_price_internal": coalesce_numeric_columns(
                chunk, carbon_price_columns
            ),
            "energy_mix_renewable_pct": renewable_pct,
            "target_ambition": (
                chunk[target_ambition_column].astype("string").str.strip()
                if target_ambition_column
                else pd.NA
            ),
            "target_coverage": coalesce_numeric_columns(
                chunk, target_coverage_columns
            ),
            "verification_status": binary_column(
                chunk, verification_column
            ),
            "policy_adoption": policy_adoption,
        }
    )
    lseg["lseg_name_key"] = lseg["lseg_name"].map(normalize_name)
    lseg = lseg.dropna(subset=["year"])
    lseg["year"] = lseg["year"].astype(int)
    lseg = lseg[
        (lseg["lseg_name_key"] != "") & (lseg["lseg_isin"] != "")
    ].drop_duplicates(
        ["year", "lseg_name_key", "lseg_isin", "lseg_instrument"]
    )
    return lseg

def iter_trucost(
    requested_years: set[int] | None = None,
) -> pd.DataFrame:
    header = pd.DataFrame(
        columns=pd.io.stata.StataReader(
            TRUCOST_RAW_PATH, convert_categoricals=False
        ).variable_labels()
    )
    year_column = find_column(header, ["fiscalyear", "fiscal_year", "year"])
    name_column = find_column(
        header, ["companyname", "company_name", "company name"]
    )
    isin_column = find_column(header, ["isin"], required=False)
    id_column = find_column(
        header,
        ["companyid", "company_id", "institutionid"],
        required=False,
    )
    revenue_column = find_column(
        header,
        ["di_319522", "trucost_revenue", "total_revenue"],
    )
    # Emissions columns
    scope_1_column = find_column(header, ["di_319413"])  # Scope 1
    scope_2_column = find_column(header, ["di_319414"])  # Scope 2
    scope_3_upstream_column = find_column(header, ["di_319415"])  # Scope 3 Upstream
    scope_3_downstream_column = find_column(header, ["di_326737"])  # Scope 3 Downstream
    # Intensity columns (optional, if needed)
    scope_1_intensity_column = find_column(header, ["di_319407"], required=False)
    scope_2_intensity_column = find_column(header, ["di_319408"], required=False)
    scope_3_upstream_intensity_column = find_column(header, ["di_319409"], required=False)
    scope_3_downstream_intensity_column = find_column(header, ["di_326738"], required=False)

    columns = list(
        dict.fromkeys(
            column
            for column in [
                year_column,
                name_column,
                isin_column,
                id_column,
                revenue_column,
                scope_1_column,
                scope_2_column,
                scope_3_upstream_column,
                scope_3_downstream_column,
                scope_1_intensity_column,
                scope_2_intensity_column,
                scope_3_upstream_intensity_column,
                scope_3_downstream_intensity_column,
            ]
            if column
        )
    )

    for chunk in read_selected_stata(TRUCOST_RAW_PATH, columns):
        if requested_years is not None:
            chunk_years = pd.to_numeric(chunk[year_column], errors="coerce")
            chunk = chunk[chunk_years.isin(requested_years)].copy()
            if chunk.empty:
                continue

        # Extract emissions separately
        scope_1_emissions = numeric_column(chunk, scope_1_column)
        scope_2_emissions = numeric_column(chunk, scope_2_column)
        scope_3_upstream_emissions = numeric_column(chunk, scope_3_upstream_column)
        scope_3_downstream_emissions = numeric_column(chunk, scope_3_downstream_column)

        # Total emissions (optional)
        current_emissions = pd.concat(
            [scope_1_emissions, scope_2_emissions, scope_3_upstream_emissions, scope_3_downstream_emissions],
            axis=1,
        ).sum(axis=1, min_count=1)

        # Revenue
        revenue = pd.to_numeric(chunk[revenue_column], errors="coerce")

        # Emissions intensity (total / revenue)
        emissions_intensity = current_emissions.div(revenue).where(revenue > 0)

        # Intensity from direct columns (fallback)
        source_emissions_intensity = pd.concat(
            [
                numeric_column(chunk, col)
                for col in [
                    scope_1_intensity_column,
                    scope_2_intensity_column,
                    scope_3_upstream_intensity_column,
                    scope_3_downstream_intensity_column,
                ]
                if col
            ],
            axis=1,
        ).sum(axis=1, min_count=1)
        emissions_intensity = emissions_intensity.fillna(source_emissions_intensity)

        trucost = pd.DataFrame(
            {
                "year": pd.to_numeric(chunk[year_column], errors="coerce"),
                "trucost_company_id": (
                    chunk[id_column].astype("string") if id_column else pd.NA
                ),
                "trucost_name": chunk[name_column].astype("string").str.strip(),
                "trucost_isin": (
                    chunk[isin_column].map(normalize_isin) if isin_column else ""
                ),
                "trucost_revenue": revenue,
                # Separate emissions columns
                "scope_1_emissions": scope_1_emissions,
                "scope_2_emissions": scope_2_emissions,
                "scope_3_upstream_emissions": scope_3_upstream_emissions,
                "scope_3_downstream_emissions": scope_3_downstream_emissions,
                "current_emissions": current_emissions,
                "emissions_intensity": emissions_intensity,
                "suppliers_emissions": scope_3_upstream_emissions,  # Scope 3 upstream = suppliers
                "suppliers_emissions_intensity": numeric_column(
                    chunk, scope_3_upstream_intensity_column
                ),
            }
        )
        trucost["trucost_name_key"] = trucost["trucost_name"].map(normalize_name)
        trucost = trucost.dropna(subset=["year"])
        trucost["year"] = trucost["year"].astype(int)
        trucost = trucost[trucost["trucost_name_key"] != ""].drop_duplicates(
            ["year", "trucost_company_id", "trucost_name_key", "trucost_isin"]
        )
        trucost = trucost.reset_index(drop=True)
        trucost["trucost_row_id"] = trucost.index
        yield trucost

def match_trucost_to_lseg(
    trucost: pd.DataFrame,
    lseg: pd.DataFrame,
    lseg_names_by_block: dict[int, dict[str, list[str]]] | None = None,
    fuzzy_cache: dict[tuple[int, str], tuple[str, float] | None] | None = None,
) -> pd.DataFrame:
    matched_parts = []
    matched_ids: set[int] = set()

    with_isin = trucost[trucost["trucost_isin"] != ""]
    if not with_isin.empty:
        isin_matches = with_isin.merge(
            lseg,
            left_on=["year", "trucost_isin"],
            right_on=["year", "lseg_isin"],
            how="inner",
        )
        if not isin_matches.empty:
            isin_matches["lseg_match_method"] = "year+isin"
            isin_matches["lseg_name_score"] = isin_matches.apply(
                lambda row: fuzz.WRatio(
                    row["trucost_name_key"], row["lseg_name_key"]
                ),
                axis=1,
            )
            matched_parts.append(isin_matches)
            matched_ids.update(isin_matches["trucost_row_id"].astype(int))

    unresolved = trucost[~trucost["trucost_row_id"].isin(matched_ids)].copy()
    exact_name_matches = unresolved.merge(
        lseg,
        left_on=["year", "trucost_name_key"],
        right_on=["year", "lseg_name_key"],
        how="inner",
    )
    if not exact_name_matches.empty:
        exact_name_matches["lseg_match_method"] = "year+normalized_name"
        exact_name_matches["lseg_name_score"] = 100.0
        matched_parts.append(exact_name_matches)
        exact_ids = set(exact_name_matches["trucost_row_id"].astype(int))
        unresolved = unresolved[
            ~unresolved["trucost_row_id"].isin(exact_ids)
        ].copy()

    if lseg_names_by_block is None:
        lseg_names_by_block = {}
        for year, names in (
            lseg[["year", "lseg_name_key"]]
            .drop_duplicates()
            .groupby("year")["lseg_name_key"]
        ):
            blocks: dict[str, list[str]] = {}
            for name in names:
                for key in blocking_keys(name):
                    blocks.setdefault(key, []).append(name)
            lseg_names_by_block[int(year)] = blocks

    name_matches = []
    for year, group in unresolved.groupby("year", sort=True):
        choices_by_block = lseg_names_by_block.get(year, {})
        if not choices_by_block:
            continue
        for row in group.itertuples(index=False):
            cache_key = (int(year), row.trucost_name_key)
            if fuzzy_cache is not None and cache_key in fuzzy_cache:
                cached_result = fuzzy_cache[cache_key]
                if cached_result is None:
                    continue
                matched_name, score = cached_result
                name_matches.append(
                    {
                        "trucost_row_id": row.trucost_row_id,
                        "year": year,
                        "lseg_name_key": matched_name,
                        "lseg_match_method": (
                            "year+normalized_name"
                            if score == 100
                            else "year+fuzzy_name"
                        ),
                        "lseg_name_score": score,
                    }
                )
                continue

            choices = list(
                {
                    choice
                    for key in blocking_keys(row.trucost_name_key)
                    for choice in choices_by_block.get(key, [])
                }
            )
            if not choices:
                if fuzzy_cache is not None:
                    fuzzy_cache[cache_key] = None
                continue
            result = process.extractOne(
                row.trucost_name_key,
                choices,
                scorer=fuzz.WRatio,
                score_cutoff=LSEG_FUZZY_THRESHOLD,
            )
            if result is not None:
                matched_name, score, _ = result
                if fuzzy_cache is not None:
                    fuzzy_cache[cache_key] = (matched_name, float(score))
                name_matches.append(
                    {
                        "trucost_row_id": row.trucost_row_id,
                        "year": year,
                        "lseg_name_key": matched_name,
                        "lseg_match_method": (
                            "year+normalized_name"
                            if score == 100
                            else "year+fuzzy_name"
                        ),
                        "lseg_name_score": float(score),
                    }
                )
            elif fuzzy_cache is not None:
                fuzzy_cache[cache_key] = None

            if fuzzy_cache is not None and len(fuzzy_cache) > FUZZY_CACHE_SIZE:
                fuzzy_cache.clear()

    if name_matches:
        mapping = pd.DataFrame(name_matches)
        fuzzy_matches = (
            unresolved.merge(mapping, on=["trucost_row_id", "year"], how="inner")
            .merge(lseg, on=["year", "lseg_name_key"], how="inner")
        )
        matched_parts.append(fuzzy_matches)

    if not matched_parts:
        return pd.DataFrame()
    return pd.concat(matched_parts, ignore_index=True, sort=False)


def match_factset_names(common: pd.DataFrame) -> pd.DataFrame:
    company_aliases = common[
        ["lseg_name_key", "trucost_name_key"]
    ].drop_duplicates()
    targets = sorted(
        (set(company_aliases["lseg_name_key"]) | set(company_aliases["trucost_name_key"]))
        - {""}
    )
    target_set = set(targets)
    target_blocks: dict[str, list[str]] = {}
    for target in targets:
        for key in blocking_keys(target):
            target_blocks.setdefault(key, []).append(target)

    best: dict[str, tuple[float, str, str]] = {}
    exact_targets: set[str] = set()
    header = pd.read_csv(
        FACTSET_RAW_PATH, sep="|", nrows=0, encoding="latin-1"
    )
    entity_id_col = find_column(
        header, ["FACTSET_ENTITY_ID", "factset_entity_id"]
    )
    entity_name_col = find_column(
        header, ["ENTITY_PROPER_NAME", "entity_name", "company_name"]
    )

    reader = pd.read_csv(
        FACTSET_RAW_PATH,
        sep="|",
        usecols=[entity_id_col, entity_name_col],
        dtype=str,
        chunksize=FACTSET_CHUNK_SIZE,
        encoding="latin-1",
        low_memory=False,
    )
    for chunk_number, chunk in enumerate(reader, start=1):
        chunk = chunk.dropna(subset=[entity_name_col])
        chunk["factset_name"] = chunk[entity_name_col].str.strip()
        chunk["factset_name_key"] = chunk["factset_name"].map(normalize_name)
        chunk = chunk[chunk["factset_name_key"] != ""].drop_duplicates(
            "factset_name_key"
        )

        exact = chunk[chunk["factset_name_key"].isin(target_set)]
        for row in exact.itertuples(index=False):
            best[row.factset_name_key] = (
                100.0,
                str(getattr(row, entity_id_col)),
                row.factset_name,
            )
            exact_targets.add(row.factset_name_key)

        unresolved = target_set.difference(exact_targets)
        if unresolved:
            choices_by_block: dict[str, list[tuple[str, str, str]]] = {}
            for row in chunk.itertuples(index=False):
                for key in blocking_keys(row.factset_name_key):
                    if key in target_blocks:
                        choices_by_block.setdefault(key, []).append(
                            (
                                row.factset_name_key,
                                str(getattr(row, entity_id_col)),
                                row.factset_name,
                            )
                        )

            for key, choices_with_data in choices_by_block.items():
                choices = [item[0] for item in choices_with_data]
                choice_data = {
                    item[0]: (item[1], item[2]) for item in choices_with_data
                }
                for target in target_blocks[key]:
                    if target not in unresolved:
                        continue
                    result = process.extractOne(
                        target,
                        choices,
                        scorer=fuzz.WRatio,
                        score_cutoff=FACTSET_FUZZY_THRESHOLD,
                    )
                    if result is None:
                        continue
                    matched_name, score, _ = result
                    if score > best.get(target, (0.0, "", ""))[0]:
                        entity_id, entity_name = choice_data[matched_name]
                        best[target] = (float(score), entity_id, entity_name)

        if chunk_number % 20 == 0:
            print(
                f"Scanned {chunk_number * FACTSET_CHUNK_SIZE:,} FactSet rows; "
                f"matched {len(best):,}/{len(targets):,} names"
            )

    matches = []
    for row in company_aliases.itertuples(index=False):
        aliases = {row.lseg_name_key, row.trucost_name_key} - {""}
        candidates = [best[alias] for alias in aliases if alias in best]
        if not candidates:
            continue
        score, entity_id, entity_name = max(candidates, key=lambda item: item[0])
        if score >= FACTSET_FUZZY_THRESHOLD:
            matches.append(
                {
                    "lseg_name_key": row.lseg_name_key,
                    "trucost_name_key": row.trucost_name_key,
                    "factset_name_score": score,
                    "factset_entity_id": entity_id,
                    "factset_name": entity_name,
                }
            )
    matches = pd.DataFrame(matches)
    if matches.empty:
        return common.iloc[0:0].copy()
    return common.merge(
        matches,
        on=["lseg_name_key", "trucost_name_key"],
        how="inner",
    )

def load_lseg_supplier_policies(
    supplier_ids: set[str],
    years: set[int],
    lseg_path: Path = LSEG_RAW_PATH,
) -> pd.DataFrame:
    """
    Load LSEG policy data for suppliers (using factset_entity_id or ISIN).

    Args:
        supplier_ids: Set of FactSet entity IDs for suppliers.
        years: Set of years to filter.
        lseg_path: Path to LSEG data.

    Returns:
        DataFrame with supplier policies (e.g., Policy Emissions, Renewable Energy Use).
    """
    # Define policy columns to extract
    policy_columns = [
        "Policy Emissions",
        "Policy Energy Efficiency",
        "Renewable Energy Use",
        "Internal Carbon Pricing",
        "Climate Policy Statement",
        "Targets Energy Efficiency",
        "Transition Plan Offsets",
    ]

    # Read LSEG data in chunks
    lseg_header = pd.read_csv(lseg_path, nrows=0)
    lseg_year = find_column(lseg_header, ["FiscalYear", "fiscal_year", "year"])
    lseg_isin = find_column(lseg_header, ["ISIN", "isin"])
    lseg_name = find_column(lseg_header, ["Company Common Name", "company_name"])
    lseg_instrument = find_column(lseg_header, ["Instrument", "instrument"], required=False)

    # Find all policy columns
    lseg_policy_columns = find_columns(lseg_header, policy_columns)

    # Read LSEG data
    lseg_columns = list(
        dict.fromkeys(
            column
            for column in [
                lseg_year,
                lseg_isin,
                lseg_name,
                lseg_instrument,
                *lseg_policy_columns,
            ]
            if column
        )
    )

    # Read in chunks
    parts = []
    with lseg_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as source:
        reader = csv.DictReader(source)
        for row in reader:
            row_year = pd.to_numeric(row.get(lseg_year), errors="coerce")
            if pd.isna(row_year) or int(row_year) not in years:
                continue
            parts.append({col: row.get(col) for col in lseg_columns})
            if len(parts) >= WIDE_CSV_CHUNK_SIZE:
                chunk = pd.DataFrame.from_records(parts, columns=lseg_columns)
                parts.clear()
                yield chunk
        if parts:
            chunk = pd.DataFrame.from_records(parts, columns=lseg_columns)
            yield chunk

def get_supplier_policies_from_lseg(
    relationships: pd.DataFrame,
    lseg_path: Path = LSEG_RAW_PATH,
) -> pd.DataFrame:
    """
    Match suppliers to LSEG data and extract their policies.

    Args:
        relationships: DataFrame with supplier_id and year (from FactSet).
        lseg_path: Path to LSEG data.

    Returns:
        DataFrame with supplier policies merged into relationships.
    """
    if relationships.empty:
        return relationships

    # Get unique supplier IDs and years
    supplier_ids = set(relationships["supplier_id"].dropna().unique())
    years = set(relationships["year"].dropna().unique())

    # Load LSEG data for suppliers
    lseg_supplier_data = []
    for chunk in load_lseg_supplier_policies(supplier_ids, years, lseg_path):
        # Normalize ISIN and name for matching
        chunk["lseg_isin"] = chunk["lseg_isin"].map(normalize_isin)
        chunk["lseg_name_key"] = chunk["lseg_name"].map(normalize_name)
        lseg_supplier_data.append(chunk)

    if not lseg_supplier_data:
        return relationships

    lseg_suppliers = pd.concat(lseg_supplier_data, ignore_index=True)

    # Match suppliers to LSEG using ISIN (if available)
    # Note: This assumes supplier_id in FactSet can be matched to LSEG ISIN or name.
    # If you have a direct mapping (e.g., factset_entity_id -> LSEG ISIN), use that.
    # Otherwise, use fuzzy matching on names.

    # Try matching by ISIN first
    relationships_with_isin = relationships[relationships["supplier_id"].isin(lseg_suppliers["lseg_isin"])]
    if not relationships_with_isin.empty:
        relationships = relationships.merge(
            lseg_suppliers,
            left_on=["supplier_id"],
            right_on=["lseg_isin"],
            how="left",
        )

    # For remaining suppliers, try fuzzy matching on names
    unresolved = relationships[relationships["lseg_name"].isna()]
    if not unresolved.empty:
        # Create a mapping of supplier_id to lseg_name_key
        supplier_name_mappings = {}
        for supplier_id in unresolved["supplier_id"].unique():
            # Get supplier name from FactSet (you may need to load this separately)
            # For now, assume supplier_id is a name or can be mapped to a name.
            # This is a placeholder; you may need to adjust based on your data.
            supplier_name = supplier_id  # Replace with actual name lookup
            supplier_name_mappings[supplier_id] = normalize_name(supplier_name)

        # Fuzzy match to LSEG names
        lseg_name_blocks = {}
        for name in lseg_suppliers["lseg_name_key"].drop_duplicates():
            for key in blocking_keys(name):
                lseg_name_blocks.setdefault(key, []).append(name)

        matches = []
        for supplier_id, supplier_name_key in supplier_name_mappings.items():
            choices = list(
                {
                    choice
                    for key in blocking_keys(supplier_name_key)
                    for choice in lseg_name_blocks.get(key, [])
                }
            )
            if not choices:
                continue
            result = process.extractOne(
                supplier_name_key,
                choices,
                scorer=fuzz.WRatio,
                score_cutoff=LSEG_FUZZY_THRESHOLD,
            )
            if result is not None:
                matched_name, score, _ = result
                matches.append(
                    {
                        "supplier_id": supplier_id,
                        "lseg_name_key": matched_name,
                        "lseg_name_score": score,
                    }
                )

        if matches:
            match_df = pd.DataFrame(matches)
            matched_lseg = lseg_suppliers.merge(
                match_df,
                left_on="lseg_name_key",
                right_on="lseg_name_key",
                how="inner",
            )
            unresolved = unresolved.merge(
                matched_lseg,
                left_on="supplier_id",
                right_on="supplier_id",
                how="left",
            )

    # Extract policy columns for suppliers
    policy_columns = [
        "Policy Emissions",
        "Policy Energy Efficiency",
        "Renewable Energy Use",
        "Internal Carbon Pricing",
        "Climate Policy Statement",
    ]

    for col in policy_columns:
        if col in unresolved.columns:
            unresolved[f"supplier_{col.lower().replace(' ', '_')}"] = binary_column(
                unresolved, col
            )

    return unresolved
def load_factset_supplier_relationships(
    company_ids: set[str], years: set[int]
) -> pd.DataFrame:
    columns = [
        "REL_TYPE",
        "SOURCE_FACTSET_ENTITY_ID",
        "TARGET_FACTSET_ENTITY_ID",
        "START_DATE",
        "END_DATE",
        "REVENUE_PCT",
    ]
    parts = []
    reader = pd.read_csv(
        FACTSET_RELATIONSHIP_PATH,
        sep="|",
        usecols=columns,
        dtype=str,
        chunksize=FACTSET_CHUNK_SIZE,
        encoding="latin-1",
        low_memory=False,
    )
    for chunk in reader:
        chunk["REL_TYPE"] = chunk["REL_TYPE"].fillna("").str.strip().str.upper()
        chunk["TARGET_FACTSET_ENTITY_ID"] = (
            chunk["TARGET_FACTSET_ENTITY_ID"].fillna("").str.strip()
        )
        chunk = chunk[
            chunk["REL_TYPE"].eq("SUPPLIER")
            & chunk["TARGET_FACTSET_ENTITY_ID"].isin(company_ids)
        ].copy()
        if not chunk.empty:
            parts.append(chunk)

    output_columns = [
        "year",
        "company_id",
        "supplier_id",
        "relationship_start",
        "relationship_end",
        "revenue_pct",
        "contract_length_years",
    ]
    if not parts:
        return pd.DataFrame(columns=output_columns)

    relationships = pd.concat(parts, ignore_index=True)
    relationships = relationships.rename(
        columns={
            "SOURCE_FACTSET_ENTITY_ID": "supplier_id",
            "TARGET_FACTSET_ENTITY_ID": "company_id",
            "START_DATE": "relationship_start",
            "END_DATE": "relationship_end",
            "REVENUE_PCT": "revenue_pct",
        }
    )
    relationships["supplier_id"] = (
        relationships["supplier_id"].fillna("").str.strip()
    )
    relationships = relationships[relationships["supplier_id"] != ""]
    relationships["relationship_start"] = pd.to_datetime(
        relationships["relationship_start"], errors="coerce"
    )
    relationships["relationship_end"] = pd.to_datetime(
        relationships["relationship_end"], errors="coerce"
    )
    relationships["revenue_pct"] = pd.to_numeric(
        relationships["revenue_pct"], errors="coerce"
    )

    yearly_parts = []
    for year in sorted(years):
        year_start = pd.Timestamp(year=year, month=1, day=1)
        year_end = pd.Timestamp(year=year, month=12, day=31, hour=23, minute=59)
        active = relationships[
            (
                relationships["relationship_start"].isna()
                | relationships["relationship_start"].le(year_end)
            )
            & (
                relationships["relationship_end"].isna()
                | relationships["relationship_end"].ge(year_start)
            )
        ].copy()
        if active.empty:
            continue
        active["year"] = year
        active["contract_length_years"] = (
            active["relationship_end"]
            - active["relationship_start"]
        ).dt.total_seconds().div(365.25 * 24 * 60 * 60)
        active.loc[
            active["contract_length_years"] < 0, "contract_length_years"
        ] = pd.NA
        yearly_parts.append(active)

    if not yearly_parts:
        return pd.DataFrame(columns=output_columns)
    return (
        pd.concat(yearly_parts, ignore_index=True)
        .sort_values(
            ["year", "company_id", "supplier_id", "relationship_start"],
            ascending=[True, True, True, False],
            na_position="last",
        )
        .drop_duplicates(["year", "company_id", "supplier_id"])
    )


def load_factset_entity_attributes(
    supplier_ids: set[str],
) -> pd.DataFrame:
    attributes: dict[str, dict[str, object]] = {}
    entity_reader = pd.read_csv(
        FACTSET_RAW_PATH,
        sep="|",
        usecols=["FACTSET_ENTITY_ID", "ISO_COUNTRY"],
        dtype=str,
        chunksize=FACTSET_CHUNK_SIZE,
        encoding="latin-1",
        low_memory=False,
    )
    for chunk in entity_reader:
        selected = chunk[chunk["FACTSET_ENTITY_ID"].isin(supplier_ids)]
        for row in selected.itertuples(index=False):
            attributes.setdefault(row.FACTSET_ENTITY_ID, {})["supplier_country"] = (
                row.ISO_COUNTRY
            )

    sector_reader = pd.read_csv(
        FACTSET_SECTOR_PATH,
        sep="|",
        usecols=["FACTSET_ENTITY_ID", "INDUSTRY_CODE"],
        dtype=str,
        chunksize=FACTSET_CHUNK_SIZE,
        encoding="latin-1",
        low_memory=False,
    )
    for chunk in sector_reader:
        selected = chunk[chunk["FACTSET_ENTITY_ID"].isin(supplier_ids)]
        for row in selected.itertuples(index=False):
            attributes.setdefault(row.FACTSET_ENTITY_ID, {})[
                "supplier_industry_code"
            ] = row.INDUSTRY_CODE

    rows = [
        {"supplier_id": supplier_id, **values}
        for supplier_id, values in attributes.items()
    ]
    return pd.DataFrame(
        rows,
        columns=["supplier_id", "supplier_country", "supplier_industry_code"],
    )


def read_cdp_company_year(
    path: Path,
    usecols: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Read CDP raw files (CSV or Excel) and return a cleaned DataFrame with:
    - Year, organization name, ISIN, emissions, targets, renewable energy %.
    - Normalized name keys for fuzzy matching.
    - Handles missing columns gracefully.

    Args:
        path: Path to the CDP file (CSV or Excel).
        usecols: Optional list of columns to read (for efficiency).

    Returns:
        DataFrame with CDP data, normalized for matching.
    """
    if not path.exists():
        raise FileNotFoundError(f"CDP file not found: {path}")

    # Read file (CSV or Excel)
    if path.suffix.casefold() in {".xlsx", ".xls"}:
        source = pd.read_excel(path, usecols=usecols) if usecols else pd.read_excel(path)
    else:
        source = pd.read_csv(path, usecols=usecols, low_memory=False) if usecols else pd.read_csv(path, low_memory=False)

    # Find columns dynamically
    year_column = find_column(source, ["year", "reporting_year", "fiscal_year"])
    name_column = find_column(
        source,
        [
            "organization_name",
            "organisation_name",
            "disclosing_organization",
            "cdp_org_name",
            "company_name",
        ],
    )
    isin_column = find_column(source, ["isin", "cdp_isin", "ISIN"], required=False)
    emissions_column = find_column(
        source,
        ["total_emissions", "cdp_emissions", "ghg_emissions"],
        required=False,
    )
    target_column = find_column(
        source,
        ["emissions_target", "cdp_target", "target_year"],
        required=False,
    )
    renewable_column = find_column(
        source,
        ["renewable_energy_pct", "cdp_renewable_pct", "renewable_pct"],
        required=False,
    )
    factset_entity_id_column = find_column(
        source,
        ["factset_entity_id", "factset_id"],
        required=False,
    )

    # Extract and clean data
    cdp = pd.DataFrame(
        {
            "year": pd.to_numeric(source[year_column], errors="coerce"),
            "cdp_org_name": source[name_column].astype("string").str.strip(),
            "cdp_isin": (
                source[isin_column].map(normalize_isin)
                if isin_column
                else ""
            ),
            "cdp_emissions": numeric_column(source, emissions_column),
            "cdp_target": (
                source[target_column].astype("string").str.strip()
                if target_column
                else pd.NA
            ),
            "cdp_renewable_pct": numeric_column(source, renewable_column),
            "factset_entity_id": (
                source[factset_entity_id_column].fillna("").str.strip()
                if factset_entity_id_column
                else ""
            ),
        }
    )

    # Clean and filter
    cdp = cdp.dropna(subset=["year"])
    cdp["year"] = cdp["year"].astype(int)
    cdp["cdp_name_key"] = cdp["cdp_org_name"].map(normalize_name)
    cdp = cdp[
        (cdp["cdp_name_key"] != "") | (cdp["cdp_isin"] != "") | (cdp["factset_entity_id"] != "")
    ].drop_duplicates(["year", "cdp_isin", "cdp_name_key", "factset_entity_id"])

    return cdp

def get_cdp_disclosing_supplier_years(
    cdp_data: pd.DataFrame,
) -> set[tuple[int, str]]:
    """
    Extract the set of (year, factset_entity_id) pairs for suppliers disclosing to CDP.
    This replaces `load_cdp_disclosing_supplier_years()` by using the CDP DataFrame directly.

    Args:
        cdp_data: DataFrame returned by `read_cdp_company_year()`.

    Returns:
        Set of tuples (year, factset_entity_id) for disclosing suppliers.
    """
    if cdp_data.empty:
        return set()

    # Filter rows with non-empty factset_entity_id
    disclosing = cdp_data[cdp_data["factset_entity_id"] != ""]
    return set(
        zip(
            disclosing["year"].astype(int),
            disclosing["factset_entity_id"],
        )
    )


def add_cdp_metrics(
    common: pd.DataFrame, cdp_path: Path | None
) -> pd.DataFrame:
    cdp_columns = [
        "cdp_org_name",
        "cdp_isin",
        "cdp_emissions",
        "cdp_target",
        "cdp_renewable_pct",
        "cdp_match_method",
        "cdp_name_score",
    ]
    common = common.copy()
    if cdp_path is None:
        for column in cdp_columns:
            common[column] = pd.NA
        return common

    cdp = read_cdp_company_year(cdp_path)
    cdp = cdp[cdp["year"].isin(common["year"].unique())]
    if cdp.empty:
        for column in cdp_columns:
            common[column] = pd.NA
        return common

    common["common_row_id"] = range(len(common))
    matches = []
    with_isin = common[common["isin"].fillna("") != ""]
    cdp_with_isin = cdp[cdp["cdp_isin"] != ""]
    if not with_isin.empty and not cdp_with_isin.empty:
        isin_matches = with_isin[
            ["common_row_id", "year", "isin"]
        ].merge(
            cdp_with_isin,
            left_on=["year", "isin"],
            right_on=["year", "cdp_isin"],
            how="inner",
        )
        if not isin_matches.empty:
            isin_matches["cdp_match_method"] = "year+isin"
            isin_matches["cdp_name_score"] = 100.0
            matches.append(isin_matches)

    matched_ids = (
        set(matches[0]["common_row_id"]) if matches else set()
    )
    unresolved = common[~common["common_row_id"].isin(matched_ids)]
    fuzzy_rows = []
    for year, group in unresolved.groupby("year", sort=False):
        year_cdp = cdp[cdp["year"].eq(year)]
        choices = year_cdp["cdp_name_key"].drop_duplicates().tolist()
        if not choices:
            continue
        cdp_by_name = year_cdp.drop_duplicates("cdp_name_key").set_index(
            "cdp_name_key"
        )
        for row in group.itertuples(index=False):
            aliases = {
                normalize_name(row.trucost_name),
                normalize_name(row.lseg_name),
                normalize_name(row.factset_name),
            } - {""}
            best_result = None
            for alias in aliases:
                result = process.extractOne(
                    alias,
                    choices,
                    scorer=fuzz.WRatio,
                    score_cutoff=CDP_FUZZY_THRESHOLD,
                )
                if result is not None and (
                    best_result is None or result[1] > best_result[1]
                ):
                    best_result = result
            if best_result is None:
                continue
            matched_name, score, _ = best_result
            cdp_row = cdp_by_name.loc[matched_name]
            fuzzy_rows.append(
                {
                    "common_row_id": row.common_row_id,
                    "cdp_org_name": cdp_row["cdp_org_name"],
                    "cdp_isin": cdp_row["cdp_isin"],
                    "cdp_emissions": cdp_row["cdp_emissions"],
                    "cdp_target": cdp_row["cdp_target"],
                    "cdp_renewable_pct": cdp_row["cdp_renewable_pct"],
                    "cdp_match_method": "year+fuzzy_name",
                    "cdp_name_score": float(score),
                }
            )
    if fuzzy_rows:
        matches.append(pd.DataFrame(fuzzy_rows))

    if matches:
        matched = (
            pd.concat(matches, ignore_index=True, sort=False)
            .sort_values(
                ["common_row_id", "cdp_name_score"],
                ascending=[True, False],
            )
            .drop_duplicates("common_row_id")
        )
        common = common.merge(
            matched[["common_row_id", *cdp_columns]],
            on="common_row_id",
            how="left",
        )
    else:
        for column in cdp_columns:
            common[column] = pd.NA
    return common.drop(columns="common_row_id")


def extract_number(value: object) -> float:
    if pd.isna(value):
        return float("nan")
    match = re.search(
        r"[-+]?\d[\d,]*(?:\.\d+)?",
        str(value).replace("\u00a0", " "),
    )
    if match is None:
        return float("nan")
    return float(match.group().replace(",", ""))


def extract_target_year(value: object) -> object:
    if pd.isna(value):
        return pd.NA
    years = re.findall(r"\b(?:19|20|21)\d{2}\b", str(value))
    return years[0] if years else pd.NA


def summarize_cdp_answers(
    records: list[dict[str, object]],
    matched_by_target: dict[str, list[str]],
) -> pd.DataFrame:
    columns = [
        "requested_org_name",
        "cdp_org_name",
        "cdp_emissions",
        "cdp_target",
        "cdp_renewable_pct",
        "cdp_name_score",
    ]
    if not records:
        return pd.DataFrame(columns=columns)
    answers = pd.DataFrame(records)
    rows = []
    for requested_org, group in answers.groupby(
        "requested_org_name", sort=False
    ):
        contexts = group[
            ["question_code", "question_text", "row_name", "column_header"]
        ].fillna("").astype(str).agg(" ".join, axis=1).map(normalize_name)
        values = group["answer"]

        target_candidates = values[
            contexts.str.contains(r"\btarget year\b", regex=True)
        ].map(extract_target_year).dropna()

        renewable_mask = (
            contexts.str.contains("renewable")
            & contexts.str.contains(r"percent|percentage|proportion|share")
        )
        renewable_candidates = values[renewable_mask].map(extract_number)
        renewable_candidates = renewable_candidates[
            renewable_candidates.between(0, 100, inclusive="both")
        ]

        scope_values: dict[str, float] = {}
        scope_patterns = {
            "scope_1": r"gross global scope 1 emissions|total scope 1 emissions",
            "scope_2_location": (
                r"scope 2 location based emissions|"
                r"gross global scope 2 location based"
            ),
            "scope_2_market": (
                r"scope 2 market based emissions|"
                r"gross global scope 2 market based"
            ),
            "scope_3": r"total scope 3 emissions|scope 3 emissions total",
        }
        for key, pattern in scope_patterns.items():
            candidates = values[
                contexts.str.contains(pattern, regex=True)
            ].map(extract_number)
            candidates = candidates[candidates.ge(0)]
            if not candidates.empty:
                scope_values[key] = float(candidates.iloc[0])
        scope_2 = scope_values.get(
            "scope_2_location", scope_values.get("scope_2_market")
        )
        emission_parts = [
            scope_values.get("scope_1"),
            scope_2,
            scope_values.get("scope_3"),
        ]
        emission_parts = [value for value in emission_parts if value is not None]

        matched_labels = matched_by_target.get(str(requested_org), [])
        matched_name = (
            matched_labels[0]
            if matched_labels
            else group["org_name_matched"].dropna().astype(str).iloc[0]
        )
        rows.append(
            {
                "requested_org_name": requested_org,
                "cdp_org_name": matched_name,
                "cdp_emissions": (
                    sum(emission_parts) if emission_parts else float("nan")
                ),
                "cdp_target": (
                    target_candidates.iloc[0]
                    if not target_candidates.empty
                    else pd.NA
                ),
                "cdp_renewable_pct": (
                    float(renewable_candidates.iloc[0])
                    if not renewable_candidates.empty
                    else float("nan")
                ),
                "cdp_name_score": float(
                    fuzz.WRatio(
                        normalize_name(requested_org),
                        normalize_name(matched_name),
                    )
                ),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def add_cdp_metrics_from_raw(
    common: pd.DataFrame, cdp_root: Path
) -> pd.DataFrame:
    cdp_columns = [
        "cdp_org_name",
        "cdp_isin",
        "cdp_emissions",
        "cdp_target",
        "cdp_renewable_pct",
        "cdp_match_method",
        "cdp_name_score",
    ]
    common = common.copy()
    common["cdp_lookup_name"] = (
        common["factset_name"]
        .fillna(common["lseg_name"])
        .fillna(common["trucost_name"])
        .astype("string")
        .str.strip()
    )
    yearly_metrics = []
    for year, group in common.groupby("year", sort=True):
        file_path = parse_year_file(cdp_root / str(int(year)))
        if file_path is None:
            continue
        org_names = group["cdp_lookup_name"].dropna().unique().tolist()
        if file_path.suffix.casefold() == ".parquet":
            records, matched = extract_many_from_2024_parquet(
                int(year), file_path, org_names
            )
        else:
            records, matched = extract_many_from_legacy_xlsx(
                int(year), file_path, org_names
            )
        metrics = summarize_cdp_answers(records, matched)
        if metrics.empty:
            continue
        metrics["year"] = int(year)
        metrics["cdp_match_method"] = "year+extractor_name"
        yearly_metrics.append(metrics)

    if not yearly_metrics:
        for column in cdp_columns:
            common[column] = pd.NA
        return common.drop(columns="cdp_lookup_name")

    metrics = pd.concat(yearly_metrics, ignore_index=True)
    metrics = metrics.rename(columns={"requested_org_name": "cdp_lookup_name"})
    metrics["cdp_isin"] = pd.NA
    common = common.merge(
        metrics[["year", "cdp_lookup_name", *cdp_columns]],
        on=["year", "cdp_lookup_name"],
        how="left",
    )
    return common.drop(columns="cdp_lookup_name")


def percentage_true(values: pd.Series) -> float:
    observed = values.dropna()
    if observed.empty:
        return float("nan")
    return float(observed.astype(bool).mean() * 100)


def classify_supplier_engagement(
    targets_pct: float, disclosing_pct: float
) -> object:
    if pd.isna(targets_pct) and pd.isna(disclosing_pct):
        return pd.NA
    targets_pct = 0.0 if pd.isna(targets_pct) else targets_pct
    disclosing_pct = 0.0 if pd.isna(disclosing_pct) else disclosing_pct
    if targets_pct >= 50 and disclosing_pct >= 50:
        return "Collaborative"
    if targets_pct > 0:
        return "Advanced"
    if disclosing_pct > 0:
        return "Basic"
    return "None"

def add_factset_supplier_metrics(common: pd.DataFrame, cdp_data: pd.DataFrame) -> pd.DataFrame:
    supplier_columns = [
        "num_suppliers",
        "suppliers_with_targets_pct",
        "suppliers_disclosing_pct",
        "suppliers_renewable_pct",
        "suppliers_engagement_level",
        "suppliers_high_emission_pct",
        "suppliers_diversification",
        "suppliers_geographic_risk",
        "suppliers_contract_length",
        # Add supplier policy columns
        "suppliers_with_emissions_policy_pct",
        "suppliers_with_energy_policy_pct",
        "suppliers_with_renewable_policy_pct",
        "suppliers_with_carbon_pricing_pct",
    ]
    if common.empty:
        for column in supplier_columns:
            common[column] = pd.NA
        return common

    common = common.copy()
    for column in [
        "cdp_target",
        "cdp_renewable_pct",
        "cdp_match_method",
    ]:
        if column not in common.columns:
            common[column] = pd.NA

    company_ids = set(common["factset_entity_id"].dropna().astype(str))
    years = set(common["year"].dropna().astype(int))
    relationships = load_factset_supplier_relationships(company_ids, years)
    if relationships.empty:
        for column in supplier_columns:
            common[column] = pd.NA
        return common

    # Add supplier policies from LSEG
    relationships = get_supplier_policies_from_lseg(relationships)

    supplier_ids = set(relationships["supplier_id"])
    attributes = load_factset_entity_attributes(supplier_ids)
    relationships = relationships.merge(attributes, on="supplier_id", how="left")
    relationships["supplier_geographic_risk"] = relationships[
        "supplier_country"
    ].map(
        lambda country: (
            pd.NA
            if pd.isna(country) or str(country).strip() == ""
            else str(country).strip().upper() in HIGH_CARBON_RISK_COUNTRIES
        )
    )

    supplier_observations = common[
        [
            "year",
            "factset_entity_id",
            "current_emissions",
            "energy_mix_renewable_pct",
            "target_ambition",
            "target_coverage",
            "cdp_target",
            "cdp_renewable_pct",
            "cdp_match_method",
        ]
    ].drop_duplicates(["year", "factset_entity_id"])
    supplier_observations = supplier_observations.rename(
        columns={"factset_entity_id": "supplier_id"}
    )
    relationships = relationships.merge(
        supplier_observations,
        on=["year", "supplier_id"],
        how="left",
    )

    # Targets and disclosing
    target_text = (
        relationships["target_ambition"].astype("string").fillna("").str.strip()
    )
    target_coverage = pd.to_numeric(
        relationships["target_coverage"], errors="coerce"
    )
    cdp_target = (
        relationships["cdp_target"].astype("string").fillna("").str.strip()
    )
    relationships["supplier_has_target"] = pd.Series(
        pd.NA, index=relationships.index, dtype="boolean"
    )
    target_observed = (
        target_text.ne("") | target_coverage.notna() | cdp_target.ne("")
    )
    relationships.loc[target_observed, "supplier_has_target"] = (
        target_text.ne("") | target_coverage.gt(0) | cdp_target.ne("")
    )

    # Renewable energy
    renewable_pct = pd.to_numeric(
        relationships["energy_mix_renewable_pct"], errors="coerce"
    )
    renewable_pct = renewable_pct.fillna(
        pd.to_numeric(relationships["cdp_renewable_pct"], errors="coerce")
    )
    relationships["supplier_uses_renewable"] = renewable_pct.gt(0).where(
        renewable_pct.notna()
    )

    # Supplier emissions
    supplier_emissions = pd.to_numeric(
        relationships["current_emissions"], errors="coerce"
    )
    relationships["supplier_high_emission"] = supplier_emissions.gt(500).where(
        supplier_emissions.notna()
    )

    # CDP disclosing suppliers
    cdp_disclosing = get_cdp_disclosing_supplier_years(cdp_data)
    relationships["supplier_disclosing"] = [
        (int(year), supplier_id) in cdp_disclosing
        for year, supplier_id in zip(
            relationships["year"],
            relationships["supplier_id"],
        )
    ]

    # Supplier policies (from LSEG)
    relationships["supplier_has_emissions_policy"] = relationships[
        "supplier_policy_emissions"
    ].fillna(False).astype(bool)
    relationships["supplier_has_energy_policy"] = relationships[
        "supplier_policy_energy_efficiency"
    ].fillna(False).astype(bool)
    relationships["supplier_has_renewable_policy"] = relationships[
        "supplier_renewable_energy_use"
    ].fillna(False).astype(bool)
    relationships["supplier_has_carbon_pricing"] = relationships[
        "supplier_internal_carbon_pricing"
    ].fillna(False).astype(bool)

    # Aggregate supplier metrics
    rows = []
    for (year, company_id), group in relationships.groupby(
        ["year", "company_id"], sort=False
    ):
        industries = group["supplier_industry_code"].dropna()
        diversification = industries.nunique() if not industries.empty else pd.NA

        # Targets and disclosing
        targets_pct = percentage_true(group["supplier_has_target"])
        disclosing_pct = percentage_true(group["supplier_disclosing"])

        # Supplier policies
        emissions_policy_pct = percentage_true(group["supplier_has_emissions_policy"])
        energy_policy_pct = percentage_true(group["supplier_has_energy_policy"])
        renewable_policy_pct = percentage_true(group["supplier_has_renewable_policy"])
        carbon_pricing_pct = percentage_true(group["supplier_has_carbon_pricing"])

        rows.append(
            {
                "year": year,
                "factset_entity_id": company_id,
                "num_suppliers": group["supplier_id"].nunique(),
                "suppliers_with_targets_pct": targets_pct,
                "suppliers_disclosing_pct": disclosing_pct,
                "suppliers_renewable_pct": percentage_true(
                    group["supplier_uses_renewable"]
                ),
                "suppliers_engagement_level": classify_supplier_engagement(
                    targets_pct, disclosing_pct
                ),
                "suppliers_high_emission_pct": percentage_true(
                    group["supplier_high_emission"]
                ),
                "suppliers_diversification": diversification,
                "suppliers_geographic_risk": percentage_true(
                    group["supplier_geographic_risk"]
                ),
                "suppliers_contract_length": group[
                    "contract_length_years"
                ].mean(),
                # Supplier policies
                "suppliers_with_emissions_policy_pct": emissions_policy_pct,
                "suppliers_with_energy_policy_pct": energy_policy_pct,
                "suppliers_with_renewable_policy_pct": renewable_policy_pct,
                "suppliers_with_carbon_pricing_pct": carbon_pricing_pct,
            }
        )

    metrics = pd.DataFrame(rows)
    return common.merge(
        metrics,
        on=["year", "factset_entity_id"],
        how="left",
    )

def find_common_companies(
    years: range | list[int] | set[int] | tuple[int, ...] | None = None,
    cdp_path: Path | None = None,
    cdp_root: Path | None = CDP_RAW_ROOT,
    names_only: bool = False,
) -> pd.DataFrame:
    requested_years = set(years) if years is not None else None
    intermediate_columns = [
        "year",
        "isin",
        "isin_valid",
        "trucost_company_id",
        "trucost_name",
        "trucost_revenue",
        "lseg_revenue",
        "current_emissions",
        "emissions_intensity",
        "suppliers_emissions",
        "suppliers_emissions_intensity",
        "lseg_instrument",
        "lseg_name",
        "esg_score",
        "carbon_price_internal",
        "energy_mix_renewable_pct",
        "target_ambition",
        "target_coverage",
        "verification_status",
        "policy_adoption",
        "lseg_match_method",
        "lseg_name_score",
        "trucost_lseg_name_exact",
        "trucost_name_key",
        "lseg_name_key",
    ]
    matched_records: dict[tuple[int, str], dict] = {}

    with TemporaryDirectory(prefix="common_companies_") as temporary_directory:
        temporary_path = Path(temporary_directory)
        lseg_path = temporary_path / "lseg"
        lseg_path.mkdir()
        lseg_years: set[int] = set()
        lseg_selected_rows = 0

        for chunk_number, lseg in enumerate(
            iter_lseg(requested_years=requested_years), start=1
        ):
            lseg_selected_rows += len(lseg)
            for year, year_lseg in lseg.groupby("year", sort=False):
                year = int(year)
                year_path = lseg_path / f"{year}.csv"
                year_lseg.to_csv(
                    year_path,
                    mode="a",
                    header=not year_path.exists(),
                    index=False,
                )
                lseg_years.add(year)
            if chunk_number % 20 == 0:
                print(
                    f"Partitioned {lseg_selected_rows:,} selected "
                    "LSEG rows by year"
                )

        lseg_cache: dict[int, pd.DataFrame] = {}
        blocks_cache: dict[int, dict[str, list[str]]] = {}
        fuzzy_cache: dict[
            tuple[int, str], tuple[str, float] | None
        ] = {}
        trucost_selected_rows = 0

        for chunk_number, trucost in enumerate(
            iter_trucost(requested_years=requested_years), start=1
        ):
            trucost_selected_rows += len(trucost)
            for year, year_trucost in trucost.groupby("year", sort=False):
                year = int(year)
                if year not in lseg_years:
                    continue

                if year not in lseg_cache:
                    year_lseg = pd.read_csv(
                        lseg_path / f"{year}.csv",
                        dtype=str,
                        low_memory=False,
                    ).drop_duplicates(
                        ["lseg_name_key", "lseg_isin", "lseg_instrument"]
                    )
                    year_lseg["year"] = year
                    blocks: dict[str, list[str]] = {}
                    for name in year_lseg["lseg_name_key"].drop_duplicates():
                        for key in blocking_keys(name):
                            blocks.setdefault(key, []).append(name)
                    lseg_cache[year] = year_lseg
                    blocks_cache[year] = blocks

                year_trucost = year_trucost.reset_index(drop=True)
                year_trucost["trucost_name_key"] = (
                    year_trucost["trucost_name_key"].fillna("")
                )
                year_trucost["trucost_isin"] = (
                    year_trucost["trucost_isin"].fillna("")
                )
                year_trucost["trucost_row_id"] = range(len(year_trucost))
                matches = match_trucost_to_lseg(
                    year_trucost,
                    lseg_cache[year],
                    lseg_names_by_block={year: blocks_cache[year]},
                    fuzzy_cache=fuzzy_cache,
                )
                if matches.empty:
                    continue

                matches["isin"] = matches["lseg_isin"].map(normalize_isin)
                matches = matches[matches["isin"] != ""].drop_duplicates("isin")
                matches["year"] = year
                matches["isin_valid"] = matches["isin"].map(is_valid_isin)
                matches["lseg_name_score"] = pd.to_numeric(
                    matches["lseg_name_score"], errors="coerce"
                )
                matches["trucost_lseg_name_exact"] = (
                    matches["trucost_name_key"] == matches["lseg_name_key"]
                )
                for record in matches[intermediate_columns].to_dict("records"):
                    key = (year, record["isin"])
                    matched_records.setdefault(key, record)

            if chunk_number % 20 == 0:
                print(
                    f"Processed {trucost_selected_rows:,} selected Trucost rows; "
                    f"matched {len(matched_records):,} company-years"
                )

    if not matched_records:
        return pd.DataFrame(
            columns=[
                "year",
                "isin",
                "isin_valid",
                "trucost_company_id",
                "trucost_name",
                "trucost_revenue",
                "lseg_revenue",
                "revenue",
                "current_emissions",
                "emissions_intensity",
                "suppliers_emissions",
                "suppliers_emissions_intensity",
                "lseg_instrument",
                "lseg_name",
                "esg_score",
                "carbon_price_internal",
                "energy_mix_renewable_pct",
                "target_ambition",
                "target_coverage",
                "verification_status",
                "policy_adoption",
                "cdp_org_name",
                "cdp_isin",
                "cdp_emissions",
                "cdp_target",
                "cdp_renewable_pct",
                "cdp_match_method",
                "cdp_name_score",
                "num_suppliers",
                "suppliers_with_targets_pct",
                "suppliers_disclosing_pct",
                "suppliers_renewable_pct",
                "suppliers_engagement_level",
                "suppliers_high_emission_pct",
                "suppliers_diversification",
                "suppliers_geographic_risk",
                "suppliers_contract_length",
                "lseg_match_method",
                "lseg_name_score",
                "trucost_lseg_name_exact",
                "factset_entity_id",
                "factset_name",
                "factset_name_score",
                "factset_name_exact",
            ]
        )

    common = pd.DataFrame.from_records(list(matched_records.values()))
    common = match_factset_names(common)
    if common.empty:
        return common

    common["factset_name_exact"] = common["factset_name_score"] == 100
    common["revenue"] = pd.to_numeric(
        common["trucost_revenue"], errors="coerce"
    ).fillna(pd.to_numeric(common["lseg_revenue"], errors="coerce"))
    if names_only:
        return (
            common[
                [
                    "year",
                    "isin",
                    "trucost_company_id",
                    "trucost_name",
                    "lseg_instrument",
                    "lseg_name",
                    "factset_entity_id",
                    "factset_name",
                ]
            ]
            .drop_duplicates(["year", "isin", "factset_entity_id"])
            .sort_values(["year", "trucost_name", "isin"])
            .reset_index(drop=True)
        )

    # Add CDP metrics
    common = (
        add_cdp_metrics(common, cdp_path)
        if cdp_path is not None
        else add_cdp_metrics_from_raw(common, cdp_root)
        if cdp_root is not None
        else add_cdp_metrics(common, None)
    )
    cdp_data = read_cdp_company_year(cdp_path) if cdp_path else pd.DataFrame()
    common = add_factset_supplier_metrics(common, cdp_data)

    # === Add Policy/Initiative Scores ===
    # Define all policy columns (from LSEG)
    climate_policy_cols = [
        "Climate Policy Statement",
        "Climate Commitment",
        "Policy Emissions",
        "Internal Carbon Pricing",
        "Climate Change Risks and Opportunities Strategy",
        "Transition Plan Offsets",
    ]
    energy_policy_cols = [
        "Policy Energy Efficiency",
        "Targets Energy Efficiency",
        "Energy Commitment",
    ]
    supply_chain_policy_cols = [
        "Policy Environmental Supply Chain",
        "Supplier Environmental Commitment",
        "Supplier Environmental Policy Communication",
        "Supplier Environmental Policy Training",
        "Supplier Environmental Risk Assessment",
        "Environmental Supply Chain Management",
        "Environmental Supply Chain Monitoring",
        "Env Supply Chain Partnership Termination",
    ]
    circular_economy_cols = [
        "Policy Sustainable Packaging",
        "Resource Reduction Targets",
        "Take-back and Recycling Initiatives",
        "Eco-Design Products",
    ]
    environmental_product_cols = [
        "Environmental Products",
        "Eco-Design Products",
        "Renewable/Clean Energy Products",
        "Water Technologies",
        "Hybrid Vehicles",
    ]
    environmental_policy_cols = list(dict.fromkeys(
        climate_policy_cols
        + energy_policy_cols
        + supply_chain_policy_cols
        + circular_economy_cols
        + ["Environmental Materials Sourcing", "ISO 14000 or EMS"]
    ))

    # Helper functions
    def count_true(df: pd.DataFrame, columns: list[str]) -> pd.Series:
        return df[columns].fillna(False).astype(bool).sum(axis=1)

    def percentage_true(df: pd.DataFrame, columns: list[str]) -> pd.Series:
        return count_true(df, columns) / len(columns) * 100

    # Compute scores
    common["Number of Climate Policies"] = count_true(common, climate_policy_cols)
    common["Number of Energy Policies"] = count_true(common, energy_policy_cols)
    common["Number of Supply Chain Environmental Policies"] = count_true(common, supply_chain_policy_cols)
    common["Number of Circular Economy Initiatives"] = count_true(common, circular_economy_cols)
    common["Number of Green Products/Services"] = count_true(common, environmental_product_cols)
    common["Number of Environmental Policies"] = count_true(common, environmental_policy_cols)
    common["Environmental Policy Coverage Score"] = percentage_true(common, environmental_policy_cols)

    # Targets
    target_existence_cols = [
        "Targets Energy Efficiency",
        "Resource Reduction Targets",
        "Emissions Target Type",
    ]
    common["Number of Environmental Targets"] = count_true(common, target_existence_cols)

    # GHG targets
    ghg_target_cols = [
        "Long Term Set 1 Percentage of GHG Emission Covered by Target",
        "Long Term Set 1 GHG Emission Base Year",
        "Long Term Set 1 GHG Emission Target Year",
        "Long Term Set 1 GHG Emission Percentage Reduction Targeted",
        "Emissions Target Type",
    ]
    common["Number of GHG Target Fields Disclosed"] = common[ghg_target_cols].notna().sum(axis=1)

    # Climate governance
    climate_governance_cols = [
        "TPI Management Question6",  # Board responsibility
        "TPI Management Question14",  # Remuneration
    ]
    common["Climate Governance Score"] = percentage_true(common, climate_governance_cols)

    # Climate strategy
    climate_strategy_cols = [
        "Climate Change Risks and Opportunities Strategy",
        "TPI Management Question11",  # Climate risk management
        "TPI Management Question15",  # Strategy
        "TPI Management Question16",  # Scenario planning
        "TPI Management Question17",  # Carbon price
    ]
    common["Climate Strategy Score"] = percentage_true(common, climate_strategy_cols)

    # Climate disclosure
    climate_disclosure_cols = [
        "TPI Management Question5",   # Scope 1/2 disclosure
        "TPI Management Question8",   # Scope 3
        "TPI Management Question9",   # Verification
        "TPI Management Question12",  # Material Scope 3
    ]
    common["Climate Disclosure Completeness Score"] = percentage_true(common, climate_disclosure_cols)

    # Policy implementation
    implementation_cols = list(dict.fromkeys(
        climate_policy_cols
        + energy_policy_cols
        + supply_chain_policy_cols
        + circular_economy_cols
        + ["Environmental Materials Sourcing", "ISO 14000 or EMS"]
    ))
    common["Policy Implementation Score"] = percentage_true(common, implementation_cols)

    # Renewable energy
    renewable_cols = [
        "Renewable Energy Use",
        "Total Renewable Energy",
        "Electricity Produced from Other Renewables",
        "Electricity Produced from Solar",
        "Electricity Produced from Wind",
    ]
    common["Number of Renewable Energy Initiatives"] = count_true(common, renewable_cols)

    # Supply chain ESG coverage
    common["Supply Chain ESG Coverage Score"] = percentage_true(common, supply_chain_policy_cols)

    # Circular economy
    common["Circular Economy Policy Score"] = percentage_true(common, circular_economy_cols)

    # Green products
    common["Green Product Coverage Score"] = percentage_true(common, environmental_product_cols)

    # Overall score
    score_components = [
        "Environmental Policy Coverage Score",
        "Climate Governance Score",
        "Climate Strategy Score",
        "Climate Disclosure Completeness Score",
        "Policy Implementation Score",
        "Supply Chain ESG Coverage Score",
        "Circular Economy Policy Score",
        "Green Product Coverage Score",
    ]
    common["Overall Environmental Management Score"] = common[score_components].mean(axis=1)

    # === Reorder Columns ===
    output_columns = [
        "year",
        "isin",
        "isin_valid",
        "trucost_name",
        "lseg_name",
        "lseg_instrument",
        "cdp_org_name",
        "factset_name",
        "factset_entity_id",
        # Revenue
        "lseg_revenue",
        "trucost_revenue",
        "revenue",
        # LSEG financials
        "inventory_turnover",
        "number_of_employees",
        "gross_profit",
        "operating_profit",
        # ESG and policies
        "esg_score",
        "policy_emissions",
        "Internal Carbon Pricing",
        "carbon_price_internal",
        # Emissions (separate scopes)
        "scope_1_emissions",
        "scope_2_emissions",
        "scope_3_upstream_emissions",
        "scope_3_downstream_emissions",
        "current_emissions",
        "emissions_intensity",
        "suppliers_emissions",
        "suppliers_emissions_intensity",
        # Targets and verification
        "target_ambition",
        "target_coverage",
        "verification_status",
        # Policy scores
        "Number of Climate Policies",
        "Number of Energy Policies",
        "Number of Supply Chain Environmental Policies",
        "Number of Circular Economy Initiatives",
        "Number of Green Products/Services",
        "Number of Environmental Policies",
        "Environmental Policy Coverage Score",
        "Number of Environmental Targets",
        "Number of GHG Target Fields Disclosed",
        "Climate Governance Score",
        "Climate Strategy Score",
        "Climate Disclosure Completeness Score",
        "Policy Implementation Score",
        "Supply Chain ESG Coverage Score",
        "Circular Economy Policy Score",
        "Green Product Coverage Score",
        "Overall Environmental Management Score",
        # CDP metrics
        "cdp_isin",
        "cdp_emissions",
        "cdp_target",
        "cdp_renewable_pct",
        "cdp_match_method",
        "cdp_name_score",
        # Supply chain metrics
        "num_suppliers",
        "suppliers_with_targets_pct",
        "suppliers_disclosing_pct",
        "suppliers_renewable_pct",
        "suppliers_engagement_level",
        "suppliers_high_emission_pct",
        "suppliers_diversification",
        "suppliers_geographic_risk",
        "suppliers_contract_length",
        # Add supplier policy columns
        "suppliers_with_emissions_policy_pct",
        "suppliers_with_energy_policy_pct",
        "suppliers_with_renewable_policy_pct",
        "suppliers_with_carbon_pricing_pct",
        # Matching metadata
        "lseg_match_method",
        "lseg_name_score",
        "trucost_lseg_name_exact",
        "factset_name_score",
        "factset_name_exact",
    ]

    return (
        common[output_columns]
        .drop_duplicates(["year", "isin", "factset_entity_id"])
        .sort_values(["year", "trucost_name", "isin"])
        .reset_index(drop=True)
    )
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Find companies shared by Trucost, LSEG, and FactSet."
    )
    parser.add_argument(
        "year",
        nargs="?",
        type=int,
        help="Fiscal year to process.",
    )
    parser.add_argument(
        "--year",
        dest="year_option",
        type=int,
        help="Fiscal year to process (alternative to the positional year).",
    )
    parser.add_argument(
        "--cdp-path",
        type=Path,
        help=(
            "Optional CSV/XLSX with year, organization_name, optional isin, "
            "total_emissions, emissions_target, and renewable_energy_pct."
        ),
    )
    parser.add_argument(
        "--cdp-root",
        type=Path,
        default=CDP_RAW_ROOT,
        help="Root directory containing CDP data in year subdirectories.",
    )
    args = parser.parse_args()

    if (
        args.year is not None
        and args.year_option is not None
        and args.year != args.year_option
    ):
        parser.error("Specify the year once, or use the same value both times.")
    selected_year = (
        args.year_option if args.year_option is not None else args.year
    )
    selected_years = [selected_year] if selected_year is not None else None
    common_companies = find_common_companies(
        years=selected_years,
        cdp_path=args.cdp_path,
        cdp_root=args.cdp_root,
    )
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    common_companies.to_csv(OUTPUT_PATH, index=False)

    if common_companies.empty:
        print("No common companies met the configured fuzzy-match thresholds.")
    else:
        common_by_year = (
            common_companies.groupby("year", as_index=False)
            .agg(
                common_companies=("isin", "nunique"),
                valid_isins=("isin_valid", "sum"),
                fuzzy_lseg_matches=(
                    "trucost_lseg_name_exact",
                    lambda values: (~values).sum(),
                ),
                fuzzy_factset_matches=(
                    "factset_name_exact",
                    lambda values: (~values).sum(),
                ),
            )
            .sort_values("year")
        )
        print(common_by_year.to_string(index=False))

    print(f"\nSaved {len(common_companies):,} company-year rows to {OUTPUT_PATH}")

"""
Shared report builder for TRACE3 FactSet/Trucost/CDP outputs.

Provides:
- target emissions profile report (2014-2024, one sheet/year)
- supply chain emissions detail report (2014-2024, one sheet/year)

The functions accept/reuse a shared context so both outputs can be generated
in a single run without re-loading large source files.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
FACTSET_DIR = ROOT / "data" / "raw" / "FactSet"
TRUCOST_DIR = ROOT / "data" / "raw" / "Trucost (Access through WRDS)"
CDP_DIR = ROOT / "data" / "raw" / "CDP"
OUT_DIR = ROOT / "data" / "outputs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

YEARS = list(range(2019, 2025))

SCOPE1_COL = "di_319413"
SCOPE2_LOC_COL = "di_319414"
SCOPE2_MKT_COL = "di_367750"
SCOPE3_UP_COL = "di_319415"
SCOPE3_DN_COL = "di_326737"
SCOPE1_AR_COL = "di_376883"
SCOPE2_LOC_AR_COL = "di_376884"
SCOPE2_MKT_AR_COL = "di_376886"

SCOPE3_CATS = {
    "S3 Cat1 Purch Goods (AR)": "di_378459",
    "S3 Cat2 Capital Goods (AR)": "di_378680",
    "S3 Cat3 Fuel/Energy (AR)": "di_378681",
    "S3 Cat4&6 T&D+Travel (AR)": "di_378682",
    "S3 Cat5 Waste (AR)": "di_378683",
    "S3 Cat7 Emp Commuting (AR)": "di_378684",
    "S3 Cat8 Ups Leased (AR)": "di_378685",
    "S3 Cat9 Dwns T&D": "di_368652",
    "S3 Cat10 Dwns Proc Prods": "di_368653",
    "S3 Cat11 Dwns Use Prods": "di_368654",
    "S3 Cat12 Dwns EoL Prods": "di_368655",
    "S3 Cat13 Dwns Leased": "di_368704",
    "S3 Cat14 Dwns Franchises": "di_368705",
    "S3 Cat15 Dwns Investments": "di_368706",
    "S3 Other Downstream": "di_368707",
    "S3 Other Upstream (AR)": "di_378686",
}

DETAIL_EMISSION_COLS = {
    "Scope 1 tCO2e": SCOPE1_COL,
    "Scope 2 Loc-Based tCO2e": SCOPE2_LOC_COL,
    "Scope 2 Mkt-Based tCO2e": SCOPE2_MKT_COL,
    "Scope 3 Upstream tCO2e": SCOPE3_UP_COL,
    "Scope 3 Downstream tCO2e": SCOPE3_DN_COL,
}

DETAIL_SCOPE3_CATEGORY_COLS = {
    f"Scope 3 Category - {label}": col for label, col in SCOPE3_CATS.items()
}


@dataclass
class ReportContext:
    factset_id: str
    target_name: str
    sym: pd.DataFrame
    rel: pd.DataFrame
    tiers: Dict[str, pd.DataFrame]
    trucost: pd.DataFrame
    cdp: pd.DataFrame
    target_tc: pd.DataFrame
    bridge_lookup: Dict[Tuple[str, int], int]
    trucost_metrics_lookup: Dict[Tuple[int, int], Dict[str, object]]


def _load_pipe(path: Path) -> pd.DataFrame:
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            df = pd.read_csv(path, sep="|", quotechar='"', dtype=str, encoding=enc)
            df.columns = [c.strip().strip('"') for c in df.columns]
            return df
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"Cannot decode {path}")


def _parse_datetime(col: pd.Series) -> pd.Series:
    return pd.to_datetime(col.fillna("").astype(str).str.strip(), errors="coerce")


def _safe_float(values, col: str) -> float:
    if isinstance(values, pd.Series):
        if col not in values.index:
            return np.nan
        raw_val = values[col]
    elif isinstance(values, dict):
        raw_val = values.get(col, np.nan)
    else:
        return np.nan
    try:
        return float(raw_val)
    except (TypeError, ValueError):
        return np.nan


def _load_sym_entity() -> pd.DataFrame:
    path = FACTSET_DIR / "sym_entity_v1_full_12328" / "sym_entity.txt"
    sym = _load_pipe(path)
    cols = list(sym.columns)
    rename = {}
    if cols[0] != "FACTSET_ENTITY_ID":
        rename[cols[0]] = "FACTSET_ENTITY_ID"
    if len(cols) > 1 and cols[1] != "ENTITY_PROPER_NAME":
        rename[cols[1]] = "ENTITY_PROPER_NAME"
    if len(cols) > 2 and cols[2] != "ISO_COUNTRY":
        rename[cols[2]] = "ISO_COUNTRY"
    sym = sym.rename(columns=rename)
    sym["FACTSET_ENTITY_ID"] = sym["FACTSET_ENTITY_ID"].fillna("").str.strip().str.strip('"')
    sym["ENTITY_PROPER_NAME_norm"] = sym["ENTITY_PROPER_NAME"].fillna("").str.strip().str.lower()
    return sym


def _load_relationships() -> pd.DataFrame:
    path = FACTSET_DIR / "ent_supply_chain_v1_full_3856" / "ent_scr_relationships.txt"
    rel = _load_pipe(path)
    cols = list(rel.columns)
    rename = {}
    if len(cols) >= 1 and cols[0] != "ID":
        rename[cols[0]] = "ID"
    if len(cols) >= 2 and cols[1] != "REL_TYPE":
        rename[cols[1]] = "REL_TYPE"
    if len(cols) >= 3:
        rename[cols[2]] = "SOURCE_FACTSET_ENTITY_ID"
    if len(cols) >= 4:
        rename[cols[3]] = "TARGET_FACTSET_ENTITY_ID"
    if len(cols) >= 5 and "START_DATE" not in rel.columns:
        rename[cols[4]] = "START_DATE"
    if len(cols) >= 6 and "END_DATE" not in rel.columns:
        rename[cols[5]] = "END_DATE"
    rel = rel.rename(columns=rename)

    for c in ("SOURCE_FACTSET_ENTITY_ID", "TARGET_FACTSET_ENTITY_ID"):
        rel[c] = rel[c].fillna("").str.strip().str.strip('"')
    rel["REL_TYPE"] = rel["REL_TYPE"].fillna("").str.strip().str.upper()

    rel["_start"] = _parse_datetime(rel.get("START_DATE", pd.Series(dtype=str)))
    rel["_end"] = _parse_datetime(rel.get("END_DATE", pd.Series(dtype=str)))
    rel["_end"] = rel["_end"].fillna(pd.Timestamp("2099-12-31"))
    return rel


def _build_tiers(rel: pd.DataFrame, target_id: str) -> Dict[str, pd.DataFrame]:
    is_supplier_row = rel["REL_TYPE"].str.contains("SUPPLIER", na=False)

    t1s = rel[is_supplier_row & (rel["TARGET_FACTSET_ENTITY_ID"] == target_id)].copy()
    t1s["partner_id"] = t1s["SOURCE_FACTSET_ENTITY_ID"]
    t1s["tier"] = "Tier-1 Supplier"
    t1s_ids = set(t1s["partner_id"].unique())

    # t1c = rel[is_supplier_row & (rel["SOURCE_FACTSET_ENTITY_ID"] == target_id)].copy()
    # t1c["partner_id"] = t1c["TARGET_FACTSET_ENTITY_ID"]
    # t1c["tier"] = "Tier-1 Customer"
    #
    # t2s = rel[is_supplier_row & rel["TARGET_FACTSET_ENTITY_ID"].isin(t1s_ids)].copy()
    # t2s["partner_id"] = t2s["SOURCE_FACTSET_ENTITY_ID"]
    # t2s = t2s[~t2s["partner_id"].isin(t1s_ids | {target_id})]
    # t2s["tier"] = "Tier-2 Supplier"
    # t2s_ids = set(t2s["partner_id"].unique())
    #
    # t3s = rel[is_supplier_row & rel["TARGET_FACTSET_ENTITY_ID"].isin(t2s_ids)].copy()
    # t3s["partner_id"] = t3s["SOURCE_FACTSET_ENTITY_ID"]
    # t3s = t3s[~t3s["partner_id"].isin(t1s_ids | t2s_ids | {target_id})]
    # t3s["tier"] = "Tier-3 Supplier"

    return {
        "tier1_sup": t1s,
        # "tier2_sup": t2s,
        # "tier3_sup": t3s,
        # "tier1_cust": t1c,
    }


def _load_trucost() -> pd.DataFrame:
    path = TRUCOST_DIR / "260710 trucost pulic-ghg-2011to24.csv"
    try:
        df = pd.read_csv(path, dtype=str, encoding="utf-8", low_memory=False)
    except UnicodeDecodeError:
        df = pd.read_csv(path, dtype=str, encoding="latin-1", low_memory=False)

    name_col = next(
        (c for c in df.columns if c.lower() == "companyname"),
        next((c for c in df.columns if "company" in c.lower() and "name" in c.lower()), None),
    )
    if name_col is None:
        raise RuntimeError("Trucost company name column not found.")
    df["_name_norm"] = df[name_col].fillna("").str.strip().str.lower()
    df["fiscalyear"] = df["fiscalyear"].fillna("").astype(str).str.strip()
    df["_fiscalyear_key"] = pd.to_numeric(df["fiscalyear"], errors="coerce").astype("Int64")
    if "companyid" in df.columns:
        df["_companyid_key"] = pd.to_numeric(df["companyid"], errors="coerce").astype("Int64")
    else:
        df["_companyid_key"] = pd.Series(pd.array([pd.NA] * len(df), dtype="Int64"))
    return df


def _load_factset_trucost_bridge() -> pd.DataFrame:
    path = OUT_DIR / "common_companies_by_year_cdp_trucost_factset_lseg_with_trucost_emissions.csv"
    if not path.exists():
        return pd.DataFrame()
    bridge = pd.read_csv(
        path,
        usecols=["factset_entity_id", "trucost_companyid", "trucost_fiscalyear"],
        low_memory=False,
    )
    bridge["factset_entity_id"] = bridge["factset_entity_id"].fillna("").astype(str).str.strip().str.strip('"')
    bridge["_companyid_key"] = pd.to_numeric(bridge["trucost_companyid"], errors="coerce").astype("Int64")
    bridge["_fiscalyear_key"] = pd.to_numeric(bridge["trucost_fiscalyear"], errors="coerce").astype("Int64")
    bridge = bridge.dropna(subset=["_companyid_key", "_fiscalyear_key"])
    return bridge


def _build_bridge_lookup(bridge: pd.DataFrame) -> Dict[Tuple[str, int], int]:
    lookup: Dict[Tuple[str, int], int] = {}
    if bridge.empty:
        return lookup
    slim = bridge[["factset_entity_id", "_fiscalyear_key", "_companyid_key"]].drop_duplicates()
    for _, row in slim.iterrows():
        lookup[(row["factset_entity_id"], int(row["_fiscalyear_key"]))] = int(row["_companyid_key"])
    return lookup


def _build_trucost_metrics_lookup(trucost: pd.DataFrame) -> Dict[Tuple[int, int], Dict[str, object]]:
    lookup: Dict[Tuple[int, int], Dict[str, object]] = {}
    needed_cols = set(DETAIL_EMISSION_COLS.values()) | set(DETAIL_SCOPE3_CATEGORY_COLS.values()) | {
        SCOPE1_COL,
        SCOPE2_LOC_COL,
        SCOPE2_MKT_COL,
        SCOPE3_UP_COL,
        SCOPE3_DN_COL,
        SCOPE1_AR_COL,
        SCOPE2_LOC_AR_COL,
        SCOPE2_MKT_AR_COL,
    } | set(SCOPE3_CATS.values())

    available_needed_cols = [c for c in needed_cols if c in trucost.columns]
    base = trucost.dropna(subset=["_companyid_key", "_fiscalyear_key"]).drop_duplicates(
        subset=["_companyid_key", "_fiscalyear_key"],
        keep="first",
    )
    cols = ["_companyid_key", "_fiscalyear_key", "_name_norm"] + available_needed_cols
    for _, row in base[cols].iterrows():
        key = (int(row["_companyid_key"]), int(row["_fiscalyear_key"]))
        lookup[key] = {c: row[c] for c in available_needed_cols}
        lookup[key]["_name_norm"] = row["_name_norm"]
    return lookup


def _load_cdp_summaries() -> pd.DataFrame:
    frames = []
    for year in YEARS:
        year_dir = CDP_DIR / str(year)
        if not year_dir.exists():
            continue
        candidates = (
            list((year_dir / "RD.U.002.01 - Climate Change (isin)").glob("*summary*.parquet"))
            if (year_dir / "RD.U.002.01 - Climate Change (isin)").exists()
            else []
        )
        if not candidates:
            candidates = list(year_dir.rglob("*summary*.parquet"))
        if not candidates:
            continue
        df = pd.read_parquet(candidates[0])
        df["_cdp_year"] = year
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    cdp = pd.concat(frames, ignore_index=True)
    org_col = next(
        (c for c in cdp.columns if "disclosing_organization" in c.lower() and "number" not in c.lower()),
        next((c for c in cdp.columns if "organization" in c.lower()), None),
    )
    if org_col:
        cdp["_org_norm"] = cdp[org_col].fillna("").str.strip().str.lower()
    cdp["_org_col"] = org_col
    return cdp


def _match_trucost_for_target(
    trucost: pd.DataFrame,
    factset_id: str,
    target_name_norm: str,
    bridge_lookup: Dict[Tuple[str, int], int],
) -> pd.DataFrame:
    rows = []
    for year in YEARS:
        company_id = bridge_lookup.get((factset_id, year))
        if company_id is None:
            continue
        mapped = trucost[
            (trucost["_companyid_key"] == company_id) &
            (trucost["_fiscalyear_key"] == year)
        ]
        if not mapped.empty:
            rows.append(mapped.iloc[0])
    if rows:
        return pd.DataFrame(rows)

    exact = trucost[trucost["_name_norm"] == target_name_norm]
    if not exact.empty:
        return exact
    try:
        from rapidfuzz import fuzz, process

        names = trucost["_name_norm"].unique().tolist()
        match = process.extractOne(target_name_norm, names, scorer=fuzz.token_sort_ratio)
        if match and match[1] >= 85:
            return trucost[trucost["_name_norm"] == match[0]]
    except ImportError:
        pass
    return pd.DataFrame(columns=trucost.columns)


def _build_context(factset_id: str) -> ReportContext:
    target_id = factset_id.strip().strip('"')
    sym = _load_sym_entity()
    rel = _load_relationships()
    tiers = _build_tiers(rel=rel, target_id=target_id)
    trucost = _load_trucost()
    bridge = _load_factset_trucost_bridge()
    bridge_lookup = _build_bridge_lookup(bridge)
    trucost_metrics_lookup = _build_trucost_metrics_lookup(trucost)
    cdp = _load_cdp_summaries()

    target_row = sym[sym["FACTSET_ENTITY_ID"] == target_id]
    target_name = target_row.iloc[0]["ENTITY_PROPER_NAME"] if not target_row.empty else target_id
    target_tc = _match_trucost_for_target(
        trucost=trucost,
        factset_id=target_id,
        target_name_norm=str(target_name).strip().lower(),
        bridge_lookup=bridge_lookup,
    )

    return ReportContext(
        factset_id=target_id,
        target_name=target_name,
        sym=sym,
        rel=rel,
        tiers=tiers,
        trucost=trucost,
        cdp=cdp,
        target_tc=target_tc,
        bridge_lookup=bridge_lookup,
        trucost_metrics_lookup=trucost_metrics_lookup,
    )


def _resolve_context(factset_id: str, reuse_context: Optional[ReportContext]) -> ReportContext:
    if reuse_context is not None:
        if reuse_context.factset_id != factset_id.strip().strip('"'):
            raise ValueError("reuse_context factset_id does not match requested factset_id.")
        return reuse_context
    return _build_context(factset_id)


def _active_partner_summary(df: pd.DataFrame, year: int) -> pd.DataFrame:
    year_start = pd.Timestamp(f"{year}-01-01")
    year_end = pd.Timestamp(f"{year}-12-31")
    active = df[(df["_start"] <= year_end) & (df["_end"] >= year_start)]
    if active.empty:
        return active
    return active


def _first_row_for_year(tc_rows: pd.DataFrame, year: int) -> pd.Series:
    if tc_rows.empty:
        return pd.Series(dtype=object)
    if "_fiscalyear_key" in tc_rows.columns:
        year_rows = tc_rows[tc_rows["_fiscalyear_key"] == year]
    else:
        fiscal_year_num = pd.to_numeric(tc_rows["fiscalyear"], errors="coerce").astype("Int64")
        year_rows = tc_rows[fiscal_year_num == year]
    if year_rows.empty:
        return pd.Series(dtype=object)
    return year_rows.iloc[0]


def build_target_emissions_profile_report(
    factset_id: str,
    output_path: Path,
    reuse_context: Optional[ReportContext] = None,
) -> ReportContext:
    ctx = _resolve_context(factset_id=factset_id, reuse_context=reuse_context)
    writer = pd.ExcelWriter(output_path, engine="openpyxl")

    for year in YEARS:
        row = _first_row_for_year(ctx.target_tc, year)

        s1 = _safe_float(row, SCOPE1_COL) if not row.empty else np.nan
        s2_loc = _safe_float(row, SCOPE2_LOC_COL) if not row.empty else np.nan
        s2_mkt = _safe_float(row, SCOPE2_MKT_COL) if not row.empty else np.nan
        s2_primary = s2_loc if not np.isnan(s2_loc) else s2_mkt
        s3_up = _safe_float(row, SCOPE3_UP_COL) if not row.empty else np.nan
        s3_dn = _safe_float(row, SCOPE3_DN_COL) if not row.empty else np.nan
        s3_total = (
            (s3_up if not np.isnan(s3_up) else 0.0) + (s3_dn if not np.isnan(s3_dn) else 0.0)
        ) or np.nan

        s1_ar = _safe_float(row, SCOPE1_AR_COL) if not row.empty else np.nan
        s2_loc_ar = _safe_float(row, SCOPE2_LOC_AR_COL) if not row.empty else np.nan
        s2_mkt_ar = _safe_float(row, SCOPE2_MKT_AR_COL) if not row.empty else np.nan

        total = sum(v for v in [s1, s2_primary, s3_total] if not np.isnan(v)) or np.nan

        def pct(v: float) -> float:
            if np.isnan(v) or np.isnan(total) or total == 0:
                return np.nan
            return round(v / total * 100, 2)

        # Count unique active partners per tier (not relationship row count)
        t1s = _active_partner_summary(ctx.tiers["tier1_sup"], year)["partner_id"].nunique()
        t2s = _active_partner_summary(ctx.tiers["tier2_sup"], year)["partner_id"].nunique()
        t3s = _active_partner_summary(ctx.tiers["tier3_sup"], year)["partner_id"].nunique()
        t1c = _active_partner_summary(ctx.tiers["tier1_cust"], year)["partner_id"].nunique()

        rows = [
            ("Company", ctx.target_name),
            ("FactSet Entity ID", ctx.factset_id),
            ("Year", year),
            ("", ""),
            ("=== EMISSIONS (tCO2e) ===", ""),
            ("Scope 1 (Gross Estimated)", s1),
            ("Scope 1 As Reported", s1_ar),
            ("Scope 2 Location-Based (Estimated)", s2_loc),
            ("Scope 2 Location-Based As Reported", s2_loc_ar),
            ("Scope 2 Market-Based (Estimated)", s2_mkt),
            ("Scope 2 Market-Based As Reported", s2_mkt_ar),
            ("Scope 3 Upstream Total", s3_up),
            ("Scope 3 Downstream Total", s3_dn),
            ("Scope 3 Total (Up + Down)", s3_total),
        ]
        for label, col in SCOPE3_CATS.items():
            rows.append((label, _safe_float(row, col) if not row.empty else np.nan))
        rows += [
            ("", ""),
            ("=== SCOPE % OF TOTAL GHG ===", ""),
            ("Total GHG (S1+S2+S3) tCO2e", total),
            ("Scope 1 %", pct(s1)),
            ("Scope 2 % (Location-Based)", pct(s2_primary)),
            ("Scope 3 %", pct(s3_total)),
            ("", ""),
            ("=== SUPPLY CHAIN PARTNER COUNTS (active in year) ===", ""),
            ("Tier-1 Suppliers", t1s),
            ("Tier-2 Suppliers", t2s),
            ("Tier-3 Suppliers", t3s),
            ("Tier-1 Customers", t1c),
        ]

        pd.DataFrame(rows, columns=["Metric", "Value"]).to_excel(
            writer, sheet_name=str(year), index=False
        )

    writer.close()
    print(f"Output written: {output_path}")
    return ctx


def _build_trucost_year_name_lookup(trucost_df: pd.DataFrame, year: int) -> Dict[str, pd.Series]:
    year_df = trucost_df[trucost_df["fiscalyear"] == str(year)]
    if year_df.empty:
        return {}
    return {
        key: group.iloc[0]
        for key, group in year_df.groupby("_name_norm", sort=False)
        if key
    }


def _build_cdp_year_name_lookup(cdp_df: pd.DataFrame, year: int) -> Dict[str, str]:
    if cdp_df.empty or "_org_norm" not in cdp_df.columns:
        return {}
    year_df = cdp_df[cdp_df["_cdp_year"] == year]
    if year_df.empty:
        return {}

    out = {}
    for key, group in year_df.groupby("_org_norm", sort=False):
        if not key:
            continue
        row = group.iloc[0]
        org_col = row.get("_org_col")
        out[key] = str(row[org_col]) if org_col else ""
    return out


def build_supply_chain_emissions_detail_report(
    factset_id: str,
    output_path: Path,
    reuse_context: Optional[ReportContext] = None,
) -> ReportContext:
    ctx = _resolve_context(factset_id=factset_id, reuse_context=reuse_context)
    writer = pd.ExcelWriter(output_path, engine="openpyxl")

    name_map = (
        ctx.sym[["FACTSET_ENTITY_ID", "ENTITY_PROPER_NAME"]]
        .drop_duplicates(subset=["FACTSET_ENTITY_ID"])
        .set_index("FACTSET_ENTITY_ID")["ENTITY_PROPER_NAME"]
        .to_dict()
    )

    for year in YEARS:
        year_rows = []
        tc_lookup = _build_trucost_year_name_lookup(ctx.trucost, year)
        cdp_lookup = _build_cdp_year_name_lookup(ctx.cdp, year)

        for tier_df in ctx.tiers.values():
            active = _active_partner_summary(tier_df, year)
            if active.empty:
                continue

            for partner_id, group in active.groupby("partner_id"):
                pname = name_map.get(partner_id, partner_id)
                pname_norm = str(pname).strip().lower()
                start_dt = group["_start"].min()
                end_dt = group["_end"].max()
                rel_type = "; ".join(sorted(set(group["REL_TYPE"].dropna().astype(str).tolist())))

                company_id = ctx.bridge_lookup.get((partner_id, year))
                tc_values: Dict[str, object] = {}
                if company_id is not None:
                    tc_values = ctx.trucost_metrics_lookup.get((company_id, year), {})
                if not tc_values:
                    tc_row = tc_lookup.get(pname_norm, pd.Series(dtype=object))
                    tc_values = tc_row.to_dict() if not tc_row.empty else {}

                emissions = {}
                for label, col in DETAIL_EMISSION_COLS.items():
                    emissions[label] = _safe_float(tc_values, col)
                s3_up = emissions["Scope 3 Upstream tCO2e"]
                s3_dn = emissions["Scope 3 Downstream tCO2e"]
                emissions["Scope 3 Total tCO2e"] = (
                    (s3_up if not np.isnan(s3_up) else 0.0) + (s3_dn if not np.isnan(s3_dn) else 0.0)
                ) or np.nan
                for label, col in DETAIL_SCOPE3_CATEGORY_COLS.items():
                    emissions[label] = _safe_float(tc_values, col)

                year_rows.append(
                    {
                        "FactSet Entity ID": partner_id,
                        "Company Name": pname,
                        "Tier / Role": group["tier"].iloc[0],
                        "Relationship Type": rel_type,
                        "Relationship Start Date": start_dt.date() if not pd.isna(start_dt) else "",
                        "Relationship End Date": end_dt.date() if end_dt < pd.Timestamp("2099-12-31") else "Ongoing",
                        "CDP Organization Name": cdp_lookup.get(pname_norm, ""),
                        **emissions,
                    }
                )

        col_order = [
            "FactSet Entity ID",
            "Company Name",
            "Tier / Role",
            "Relationship Type",
            "Relationship Start Date",
            "Relationship End Date",
            "CDP Organization Name",
            "Scope 1 tCO2e",
            "Scope 2 Loc-Based tCO2e",
            "Scope 2 Mkt-Based tCO2e",
            "Scope 3 Upstream tCO2e",
            "Scope 3 Downstream tCO2e",
            "Scope 3 Total tCO2e",
        ] + list(DETAIL_SCOPE3_CATEGORY_COLS.keys())

        if year_rows:
            year_df = pd.DataFrame(year_rows)
            for col in col_order:
                if col not in year_df.columns:
                    year_df[col] = np.nan
            year_df = year_df[col_order].sort_values(
                ["Tier / Role", "Company Name"], kind="stable"
            ).reset_index(drop=True)
        else:
            year_df = pd.DataFrame(columns=col_order)

        year_df.to_excel(writer, sheet_name=str(year), index=False)

    writer.close()
    print(f"Output written: {output_path}")
    return ctx

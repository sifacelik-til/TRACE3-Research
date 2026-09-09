"""Build a company-level supply-chain report for selected FactSet industries.

Scope:
- FactSet industry codes 1105-3130
- plus electronics/high-tech manufacturing related industry descriptions

Keeps companies (no averaging across companies) and filters to the top 10 relations
per company by relevance (relation revenue pct, then relation start date).

Outputs:
- data/processed/selected_company_relations_top10.csv
- data/processed/selected_company_trucost_yearly.csv
- data/processed/selected_factset_industries.csv
"""
from pathlib import Path
import logging
import re

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
LOGGER = logging.getLogger(__name__)

DATA_RAW = Path("data") / "raw"
FACTSET_DIR = DATA_RAW / "FactSet"
OUT_DIR = Path("data") / "processed"
OUT_DIR.mkdir(parents=True, exist_ok=True)

sym_entity = FACTSET_DIR / "sym_entity_v1_full_12328" / "sym_entity.txt"
sym_sector = FACTSET_DIR / "sym_entity_v1_full_12328" / "sym_entity_sector.txt"
relationships = FACTSET_DIR / "ent_supply_chain_v1_full_3856" / "ent_scr_relationships.txt"
industry_map = FACTSET_DIR / "ref_hub_v2_full_3565" / "factset_industry_map.txt"

TRUCOST_DI_CODES = [
    319410, 319411, 319413, 376883, 319414, 376884, 367750, 376886, 378459,
    368653, 377767, 368654, 377768, 368655, 377405, 368704, 377406, 368705,
    377407, 368706, 377408, 378680, 378681, 378682, 378683, 378684, 378685,
    368652, 377766, 326737, 368707, 377409, 378686, 319415, 319412,
]
TRUCOST_DI_COLS = [f"di_{c}" for c in TRUCOST_DI_CODES]

for p in (sym_entity, sym_sector, relationships, industry_map):
    if not p.exists():
        raise SystemExit(f"Missing required file: {p}")


def read_pipe(path):
    try:
        return pd.read_csv(path, sep="|", quotechar='"', dtype=str, encoding="utf-8")
    except Exception:
        return pd.read_csv(path, sep="|", quotechar='"', dtype=str, encoding="latin-1")


def normalize_cols(df):
    df.columns = [c.strip().strip('"') for c in df.columns]
    return df


LOGGER.info("Loading FactSet entities")
sym = normalize_cols(read_pipe(sym_entity))
sym = sym.rename(columns={sym.columns[0]: "FACTSET_ENTITY_ID", sym.columns[1]: "ENTITY_PROPER_NAME"})
sym["ENTITY_PROPER_NAME_NORM"] = sym["ENTITY_PROPER_NAME"].fillna("").astype(str).str.strip().str.lower()
sym = sym.drop_duplicates(subset=["FACTSET_ENTITY_ID"], keep="first").copy()

LOGGER.info("Loading industry metadata")
sector = normalize_cols(read_pipe(sym_sector))
sector = sector.rename(columns={sector.columns[0]: "FACTSET_ENTITY_ID", sector.columns[2]: "INDUSTRY_CODE", sector.columns[3]: "SECTOR_CODE"})
sector = sector[["FACTSET_ENTITY_ID", "INDUSTRY_CODE"]].drop_duplicates("FACTSET_ENTITY_ID", keep="first")

ind_map = normalize_cols(read_pipe(industry_map))
ind_map = ind_map.rename(columns={ind_map.columns[0]: "INDUSTRY_CODE", ind_map.columns[1]: "INDUSTRY_DESC"})

companies = sym[["FACTSET_ENTITY_ID", "ENTITY_PROPER_NAME", "ENTITY_PROPER_NAME_NORM"]].merge(
    sector, on="FACTSET_ENTITY_ID", how="left"
).merge(ind_map[["INDUSTRY_CODE", "INDUSTRY_DESC"]], on="INDUSTRY_CODE", how="left")
companies["INDUSTRY_CODE"] = companies["INDUSTRY_CODE"].fillna("9999")
companies["INDUSTRY_DESC"] = companies["INDUSTRY_DESC"].fillna("Not Classified")
companies = companies[companies["INDUSTRY_CODE"].astype(str) != "9999"].copy()

code_num = pd.to_numeric(companies["INDUSTRY_CODE"], errors="coerce")
desc = companies["INDUSTRY_DESC"].fillna("").astype(str).str.lower()
range_mask = code_num.between(1105, 3130, inclusive="both")
keyword_mask = desc.str.contains(
    "electronic|electronics|semiconductor|computer|high tech|technology|telecommunications|aerospace|defense|electrical products|electronic production equipment",
    regex=True,
    na=False,
)
selected_industries = (
    companies[range_mask | keyword_mask]
    .groupby(["INDUSTRY_CODE", "INDUSTRY_DESC"])
    .size()
    .reset_index(name="company_count")
    .sort_values(["company_count", "INDUSTRY_CODE"], ascending=[False, True])
    .copy()
)
selected_codes = set(selected_industries["INDUSTRY_CODE"].astype(str))
selected_company_universe = companies[companies["INDUSTRY_CODE"].astype(str).isin(selected_codes)].copy()
selected_company_universe = selected_company_universe.drop_duplicates(subset=["FACTSET_ENTITY_ID"], keep="first")

selected_industries.to_csv(OUT_DIR / "selected_factset_industries.csv", index=False)
LOGGER.info("Selected industries: %d", len(selected_industries))

LOGGER.info("Loading relationships")
rel = normalize_cols(read_pipe(relationships))
rel = rel.rename(columns={rel.columns[0]: "ID", rel.columns[1]: "REL_TYPE", rel.columns[2]: "SOURCE_FACTSET_ENTITY_ID", rel.columns[3]: "TARGET_FACTSET_ENTITY_ID"})
for c in ("START_DATE", "END_DATE", "REVENUE_PCT"):
    if c not in rel.columns:
        rel[c] = None
rel["SOURCE_ID"] = rel["SOURCE_FACTSET_ENTITY_ID"].fillna("").astype(str).str.strip().str.strip('"')
rel["TARGET_ID"] = rel["TARGET_FACTSET_ENTITY_ID"].fillna("").astype(str).str.strip().str.strip('"')
rel["REVENUE_PCT_NUM"] = pd.to_numeric(rel["REVENUE_PCT"], errors="coerce")
rel["START_DATE_DT"] = pd.to_datetime(rel["START_DATE"], errors="coerce")
rel["END_DATE_DT"] = pd.to_datetime(rel["END_DATE"], errors="coerce")

selected_ids = set(selected_company_universe["FACTSET_ENTITY_ID"].astype(str))
rel = rel[rel["SOURCE_ID"].isin(selected_ids) | rel["TARGET_ID"].isin(selected_ids)].copy()
LOGGER.info("Relationships in scope: %d", len(rel))

src = rel[["SOURCE_ID", "TARGET_ID", "REL_TYPE", "START_DATE_DT", "END_DATE_DT", "REVENUE_PCT_NUM"]].copy()
src = src.rename(columns={"SOURCE_ID": "company_id", "TARGET_ID": "partner_id"})
src["company_is_source"] = True
tgt = rel[["TARGET_ID", "SOURCE_ID", "REL_TYPE", "START_DATE_DT", "END_DATE_DT", "REVENUE_PCT_NUM"]].copy()
tgt = tgt.rename(columns={"TARGET_ID": "company_id", "SOURCE_ID": "partner_id"})
tgt["company_is_source"] = False
all_rel = pd.concat([src, tgt], ignore_index=True)
all_rel = all_rel[all_rel["company_id"].astype(str).str.len() > 0].copy()
all_rel["REL_TYPE_UP"] = all_rel["REL_TYPE"].fillna("").astype(str).str.upper()
all_rel["role"] = "related"
all_rel.loc[(all_rel["company_is_source"]) & all_rel["REL_TYPE_UP"].str.contains("SUPPLIER"), "role"] = "customer"
all_rel.loc[(~all_rel["company_is_source"]) & all_rel["REL_TYPE_UP"].str.contains("SUPPLIER"), "role"] = "supplier"
all_rel.loc[(all_rel["company_is_source"]) & all_rel["REL_TYPE_UP"].str.contains("CUSTOMER"), "role"] = "supplier"
all_rel.loc[(~all_rel["company_is_source"]) & all_rel["REL_TYPE_UP"].str.contains("CUSTOMER"), "role"] = "customer"
all_rel = all_rel[all_rel["role"].isin(["supplier", "customer"])].copy()
all_rel = all_rel.drop_duplicates(subset=["company_id", "partner_id", "REL_TYPE", "START_DATE_DT", "END_DATE_DT", "REVENUE_PCT_NUM"])

# Keep only companies in selected industries on the left side.
all_rel = all_rel[all_rel["company_id"].isin(selected_ids)].copy()
all_rel = all_rel.merge(
    selected_company_universe[["FACTSET_ENTITY_ID", "ENTITY_PROPER_NAME", "INDUSTRY_CODE", "INDUSTRY_DESC"]],
    left_on="company_id",
    right_on="FACTSET_ENTITY_ID",
    how="left",
).drop(columns=["FACTSET_ENTITY_ID"])
all_rel = all_rel.rename(columns={"ENTITY_PROPER_NAME": "company_name", "INDUSTRY_CODE": "industry_code", "INDUSTRY_DESC": "industry_desc"})

# Partner metadata (exact fields only)
isin_cols = [c for c in sym.columns if "isin" in c.lower()]
ticker_cols = [c for c in sym.columns if c.lower() in ("ticker", "symbol", "primary_symbol") or "ticker" in c.lower() or "symbol" in c.lower()]
relation_partner_ids = pd.Index(pd.concat([rel["SOURCE_ID"], rel["TARGET_ID"]]).dropna().astype(str).unique())
partner_universe = companies[companies["FACTSET_ENTITY_ID"].isin(relation_partner_ids)].copy()
partner_meta = partner_universe.merge(sym[["FACTSET_ENTITY_ID"] + isin_cols + ticker_cols], on="FACTSET_ENTITY_ID", how="left")
partner_meta = partner_meta.rename(columns={
    "FACTSET_ENTITY_ID": "partner_id",
    "ENTITY_PROPER_NAME": "partner_name",
    "ENTITY_PROPER_NAME_NORM": "partner_name_norm",
    "INDUSTRY_CODE": "partner_industry_code",
    "INDUSTRY_DESC": "partner_industry_desc",
})
partner_meta["entity_name"] = partner_meta["partner_name"]
partner_meta["entity_name_norm"] = partner_meta["partner_name_norm"]

company_meta = selected_company_universe.merge(sym[["FACTSET_ENTITY_ID"] + isin_cols + ticker_cols], on="FACTSET_ENTITY_ID", how="left")
company_meta = company_meta.rename(columns={
    "FACTSET_ENTITY_ID": "company_id",
    "ENTITY_PROPER_NAME": "company_name",
    "ENTITY_PROPER_NAME_NORM": "company_name_norm",
})
company_meta["entity_name"] = company_meta["company_name"]
company_meta["entity_name_norm"] = company_meta["company_name_norm"]
partner_meta = partner_meta.drop_duplicates(subset=["partner_id"], keep="first")
company_meta = company_meta.drop_duplicates(subset=["company_id"], keep="first")

# Exact CDP/company and Trucost/company matching
LOGGER.info("Loading CDP summary")
cdp_candidates = list(DATA_RAW.rglob("*full_extract*_isin*_summary*.parquet"))
if not cdp_candidates:
    cdp_candidates = list(DATA_RAW.rglob("*full_extract*summary*.parquet"))
cdp_summary = pd.DataFrame()
cdp_by_isin = {}
cdp_by_name = {}
cdp_id_col = None
if cdp_candidates:
    cdp_summary = pd.read_parquet(cdp_candidates[0])
    for c in ("disclosing_organization", "disclosing_organization_name", "disclosing_organization_full", "organization_name"):
        if c in cdp_summary.columns:
            cdp_summary["cdp_name_norm"] = cdp_summary[c].fillna("").astype(str).str.strip().str.lower()
            break
    if "isin" in cdp_summary.columns:
        cdp_summary["isin"] = cdp_summary["isin"].fillna("").astype(str).str.strip().str.upper()
        cdp_by_isin = dict(zip(cdp_summary["isin"], cdp_summary.index))
    cdp_candidates_cols = [c for c in cdp_summary.columns if any(k in c.lower() for k in ("organization_id", "participant", "cdp_id", "company_id", "disclosing_organization_id"))]
    if cdp_candidates_cols:
        cdp_id_col = cdp_candidates_cols[0]
    if "cdp_name_norm" in cdp_summary.columns:
        cdp_by_name = dict(zip(cdp_summary["cdp_name_norm"], cdp_summary.index))

LOGGER.info("Loading Trucost")
tr_candidates = list(DATA_RAW.rglob("*trucost*.csv"))
tr = pd.DataFrame()
tr_by_ticker = {}
tr_by_name = {}
if tr_candidates:
    tr = pd.read_csv(tr_candidates[0], dtype=str, encoding="latin-1")
    if "ticker" in tr.columns:
        tr["ticker"] = tr["ticker"].fillna("").astype(str).str.strip().str.upper()
        tr_by_ticker = dict(zip(tr["ticker"], tr["companyid"]))
    if "companyname" in tr.columns:
        tr["companyname_norm"] = tr["companyname"].fillna("").astype(str).str.strip().str.lower()
        tr_by_name = dict(zip(tr["companyname_norm"], tr["companyid"]))
    if "fiscalyear" not in tr.columns and "periodenddate" in tr.columns:
        tr["fiscalyear"] = pd.to_datetime(tr["periodenddate"], errors="coerce").dt.year

# Normalize entity lookups
isin_cols = [c for c in sym.columns if "isin" in c.lower()]
ticker_cols = [c for c in sym.columns if c.lower() in ("ticker", "symbol", "primary_symbol") or "ticker" in c.lower() or "symbol" in c.lower()]

def first_nonempty(series):
    for val in series:
        if pd.notna(val) and str(val).strip():
            return str(val).strip()
    return ""

def build_match_table(df, id_col, prefix):
    out = df.copy()
    if id_col not in out.columns:
        raise KeyError(id_col)
    if "entity_name" not in out.columns:
        if "company_name" in out.columns:
            out["entity_name"] = out["company_name"]
        elif "partner_name" in out.columns:
            out["entity_name"] = out["partner_name"]
        elif "ENTITY_PROPER_NAME" in out.columns:
            out["entity_name"] = out["ENTITY_PROPER_NAME"]
    if "entity_name_norm" not in out.columns:
        if "company_name_norm" in out.columns:
            out["entity_name_norm"] = out["company_name_norm"]
        elif "partner_name_norm" in out.columns:
            out["entity_name_norm"] = out["partner_name_norm"]
        elif "ENTITY_PROPER_NAME_NORM" in out.columns:
            out["entity_name_norm"] = out["ENTITY_PROPER_NAME_NORM"]
        else:
            out["entity_name_norm"] = out["entity_name"].fillna("").astype(str).str.strip().str.lower()
    out[f"{prefix}_isin"] = pd.NA
    out[f"{prefix}_ticker"] = pd.NA
    for c in isin_cols:
        out[f"{prefix}_isin"] = out[f"{prefix}_isin"].combine_first(df[c].fillna("").astype(str).str.strip().str.upper()) if c in df.columns else out[f"{prefix}_isin"]
    for c in ticker_cols:
        out[f"{prefix}_ticker"] = out[f"{prefix}_ticker"].combine_first(df[c].fillna("").astype(str).str.strip().str.upper()) if c in df.columns else out[f"{prefix}_ticker"]
    out = out.drop_duplicates(subset=[id_col], keep="first")
    return out

company_match = build_match_table(company_meta, "company_id", "company")
partner_match = build_match_table(partner_meta, "partner_id", "partner")

def attach_exact_cdp(match_df, entity_prefix):
    if cdp_summary.empty or cdp_id_col is None:
        match_df[f"{entity_prefix}_cdp_id"] = pd.NA
        return match_df
    match_df[f"{entity_prefix}_cdp_id"] = pd.NA
    if "isin" in cdp_summary.columns and f"{entity_prefix}_isin" in match_df.columns:
        isin_map = cdp_summary[["isin", cdp_id_col]].dropna(subset=["isin"]).drop_duplicates("isin", keep="first")
        isin_map = isin_map.rename(columns={"isin": f"{entity_prefix}_isin", cdp_id_col: f"{entity_prefix}_cdp_id"})
        match_df = match_df.merge(isin_map, on=f"{entity_prefix}_isin", how="left", suffixes=("", "_isin"))
        match_df[f"{entity_prefix}_cdp_id"] = match_df[f"{entity_prefix}_cdp_id"].combine_first(match_df[f"{entity_prefix}_cdp_id_isin"])
        match_df = match_df.drop(columns=[f"{entity_prefix}_cdp_id_isin"], errors="ignore")
    if "cdp_name_norm" in cdp_summary.columns and f"{entity_prefix}_cdp_id" in match_df.columns:
        name_map = cdp_summary[["cdp_name_norm", cdp_id_col]].dropna(subset=["cdp_name_norm"]).drop_duplicates("cdp_name_norm", keep="first")
        name_map = name_map.rename(columns={"cdp_name_norm": "entity_name_norm", cdp_id_col: f"{entity_prefix}_cdp_id"})
        match_df = match_df.merge(name_map, on="entity_name_norm", how="left", suffixes=("", "_name"))
        match_df[f"{entity_prefix}_cdp_id"] = match_df[f"{entity_prefix}_cdp_id"].combine_first(match_df[f"{entity_prefix}_cdp_id_name"])
        match_df = match_df.drop(columns=[f"{entity_prefix}_cdp_id_name"], errors="ignore")
    return match_df

def attach_exact_tr(match_df, entity_prefix):
    match_df[f"{entity_prefix}_trucost_companyid"] = pd.NA
    if tr.empty:
        return match_df
    if f"{entity_prefix}_ticker" in match_df.columns and "ticker" in tr.columns:
        ticker_map = tr[["ticker", "companyid"]].dropna(subset=["ticker"]).drop_duplicates("ticker", keep="first")
        ticker_map = ticker_map.rename(columns={"ticker": f"{entity_prefix}_ticker", "companyid": f"{entity_prefix}_trucost_companyid"})
        match_df = match_df.merge(ticker_map, on=f"{entity_prefix}_ticker", how="left", suffixes=("", "_ticker"))
        match_df[f"{entity_prefix}_trucost_companyid"] = match_df[f"{entity_prefix}_trucost_companyid"].combine_first(match_df[f"{entity_prefix}_trucost_companyid_ticker"])
        match_df = match_df.drop(columns=[f"{entity_prefix}_trucost_companyid_ticker"], errors="ignore")
    if "companyname_norm" in tr.columns:
        name_map = tr[["companyname_norm", "companyid"]].dropna(subset=["companyname_norm"]).drop_duplicates("companyname_norm", keep="first")
        name_map = name_map.rename(columns={"companyname_norm": "entity_name_norm", "companyid": f"{entity_prefix}_trucost_companyid"})
        match_df = match_df.merge(name_map, on="entity_name_norm", how="left", suffixes=("", "_name"))
        match_df[f"{entity_prefix}_trucost_companyid"] = match_df[f"{entity_prefix}_trucost_companyid"].combine_first(match_df[f"{entity_prefix}_trucost_companyid_name"])
        match_df = match_df.drop(columns=[f"{entity_prefix}_trucost_companyid_name"], errors="ignore")
    return match_df

company_match = attach_exact_cdp(company_match, "company")
partner_match = attach_exact_cdp(partner_match, "partner")
company_match = attach_exact_tr(company_match, "company")
partner_match = attach_exact_tr(partner_match, "partner")

all_rel = all_rel.merge(company_match[["company_id", "company_cdp_id", "company_trucost_companyid"]], on="company_id", how="left")
all_rel = all_rel.merge(partner_match[["partner_id", "partner_name", "partner_cdp_id", "partner_trucost_companyid", "partner_industry_code", "partner_industry_desc"]], on="partner_id", how="left")

# Rank relations within each company and keep top 10
all_rel = all_rel.sort_values(["company_id", "REVENUE_PCT_NUM", "START_DATE_DT"], ascending=[True, False, False], na_position="last")
all_rel["relevance_rank"] = all_rel.groupby("company_id").cumcount() + 1
all_rel = all_rel[all_rel["relevance_rank"] <= 10].copy()

final_cols = [
    "company_id", "company_name", "industry_code", "industry_desc",
    "partner_id", "partner_name", "partner_industry_code", "partner_industry_desc",
    "role", "REL_TYPE", "relation_start_date", "relation_end_date", "relation_revenue_pct",
    "relevance_rank", "company_cdp_id", "partner_cdp_id",
    "company_trucost_companyid", "partner_trucost_companyid",
]
all_rel = all_rel.rename(columns={"START_DATE_DT": "relation_start_date", "END_DATE_DT": "relation_end_date", "REVENUE_PCT_NUM": "relation_revenue_pct"})
all_rel = all_rel[final_cols].copy()

consolidated_path = OUT_DIR / "selected_company_relations_top10.csv"
all_rel.to_csv(consolidated_path, index=False)
LOGGER.info("Wrote company-level relation report: %s (rows=%d)", consolidated_path, len(all_rel))

# Company-year Trucost table for the selected company universe
if not tr.empty and "companyid" in tr.columns:
    selected_tr_ids = set(all_rel["company_trucost_companyid"].dropna().astype(str).unique())
    tr = tr[tr["companyid"].astype(str).isin(selected_tr_ids)].copy()
    available_di_cols = [c for c in TRUCOST_DI_COLS if c in tr.columns]
    if available_di_cols and "fiscalyear" in tr.columns:
        tr["fiscalyear"] = pd.to_numeric(tr["fiscalyear"], errors="coerce")
        for c in available_di_cols:
            tr[c] = pd.to_numeric(tr[c], errors="coerce")
        company_lookup = company_match[["company_id", "company_cdp_id", "company_trucost_companyid"]].drop_duplicates("company_id", keep="first")
        company_lookup = company_lookup.rename(columns={"company_trucost_companyid": "companyid"})
        tr_yearly = tr.merge(company_lookup, on="companyid", how="left")
        tr_yearly = tr_yearly.merge(
            selected_company_universe[["FACTSET_ENTITY_ID", "INDUSTRY_CODE", "INDUSTRY_DESC"]].drop_duplicates("FACTSET_ENTITY_ID"),
            left_on="company_id",
            right_on="FACTSET_ENTITY_ID",
            how="left",
        )
        tr_yearly = tr_yearly.rename(columns={"INDUSTRY_CODE": "industry_code", "INDUSTRY_DESC": "industry_desc", "fiscalyear": "year"})
        tr_yearly = tr_yearly[["company_id", "companyid", "industry_code", "industry_desc", "year"] + available_di_cols]
    else:
        tr_yearly = pd.DataFrame(columns=["company_id", "companyid", "industry_code", "industry_desc", "year"] + TRUCOST_DI_COLS)
else:
    tr_yearly = pd.DataFrame(columns=["company_id", "companyid", "industry_code", "industry_desc", "year"] + TRUCOST_DI_COLS)

tr_yearly.to_csv(OUT_DIR / "selected_company_trucost_yearly.csv", index=False)
LOGGER.info("Wrote company-year Trucost table: %s (rows=%d)", OUT_DIR / "selected_company_trucost_yearly.csv", len(tr_yearly))

print("Done")

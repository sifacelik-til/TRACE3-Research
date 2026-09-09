"""Aggregate FactSet supply-chain data for the top 35 industries.

Outputs:
- data/processed/top35_industry_summary.csv
- data/processed/top35_industry_trucost_yearly.csv
- data/processed/top35_factset_industries.csv

The report is industry-level (not per-company) to keep the full FactSet universe tractable.
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

for p in (sym_entity, sym_sector, relationships, industry_map):
    if not p.exists():
        raise SystemExit(f"Missing required file: {p}")


def read_pipe(path):
    try:
        return pd.read_csv(path, sep="|", quotechar='"', dtype=str, encoding="utf-8")
    except Exception:
        return pd.read_csv(path, sep="|", quotechar='"', dtype=str, encoding="latin-1")


LOGGER.info("Loading FactSet entities")
sym = read_pipe(sym_entity)
sym.columns = [c.strip().strip('"') for c in sym.columns]
sym = sym.rename(columns={sym.columns[0]: "FACTSET_ENTITY_ID", sym.columns[1]: "ENTITY_PROPER_NAME"})
sym["ENTITY_PROPER_NAME_NORM"] = sym["ENTITY_PROPER_NAME"].fillna("").astype(str).str.strip().str.lower()
sym = sym.drop_duplicates(subset=["FACTSET_ENTITY_ID"], keep="first").copy()

LOGGER.info("Loading sector and industry map")
sector = read_pipe(sym_sector)
sector.columns = [c.strip().strip('"') for c in sector.columns]
sector = sector.rename(columns={sector.columns[0]: "FACTSET_ENTITY_ID", sector.columns[2]: "INDUSTRY_CODE", sector.columns[3]: "SECTOR_CODE"})
sector = sector[["FACTSET_ENTITY_ID", "INDUSTRY_CODE"]].drop_duplicates("FACTSET_ENTITY_ID", keep="first")

ind_map = read_pipe(industry_map)
ind_map.columns = [c.strip().strip('"') for c in ind_map.columns]
ind_map = ind_map.rename(columns={ind_map.columns[0]: "INDUSTRY_CODE", ind_map.columns[1]: "INDUSTRY_DESC"})

companies = sym[["FACTSET_ENTITY_ID", "ENTITY_PROPER_NAME", "ENTITY_PROPER_NAME_NORM"]].merge(
    sector, on="FACTSET_ENTITY_ID", how="left"
).merge(ind_map[["INDUSTRY_CODE", "INDUSTRY_DESC"]], on="INDUSTRY_CODE", how="left")
companies["INDUSTRY_CODE"] = companies["INDUSTRY_CODE"].fillna("9999")
companies["INDUSTRY_DESC"] = companies["INDUSTRY_DESC"].fillna("Not Classified")
companies = companies[companies["INDUSTRY_CODE"].astype(str) != "9999"].copy()

top_35 = (
    companies.groupby(["INDUSTRY_CODE", "INDUSTRY_DESC"])
    .size()
    .reset_index(name="company_count")
    .sort_values(["company_count", "INDUSTRY_CODE"], ascending=[False, True])
    .head(35)
    .copy()
)
top_35.to_csv(OUT_DIR / "top35_factset_industries.csv", index=False)
top_codes = set(top_35["INDUSTRY_CODE"].astype(str))
selected_companies = companies[companies["INDUSTRY_CODE"].astype(str).isin(top_codes)].copy()
LOGGER.info("Top 35 industries selected; companies in scope: %d", len(selected_companies))

LOGGER.info("Loading relationships")
rel = read_pipe(relationships)
rel.columns = [c.strip().strip('"') for c in rel.columns]
rel = rel.rename(columns={rel.columns[0]: "ID", rel.columns[1]: "REL_TYPE", rel.columns[2]: "SOURCE_FACTSET_ENTITY_ID", rel.columns[3]: "TARGET_FACTSET_ENTITY_ID"})
for c in ("START_DATE", "END_DATE", "REVENUE_PCT"):
    if c not in rel.columns:
        rel[c] = None
rel["SOURCE_ID"] = rel["SOURCE_FACTSET_ENTITY_ID"].fillna("").astype(str).str.strip().str.strip('"')
rel["TARGET_ID"] = rel["TARGET_FACTSET_ENTITY_ID"].fillna("").astype(str).str.strip().str.strip('"')
rel["REVENUE_PCT_NUM"] = pd.to_numeric(rel["REVENUE_PCT"], errors="coerce")
rel["START_DATE_DT"] = pd.to_datetime(rel["START_DATE"], errors="coerce")
rel["END_DATE_DT"] = pd.to_datetime(rel["END_DATE"], errors="coerce")
selected_ids = set(selected_companies["FACTSET_ENTITY_ID"].astype(str))
rel = rel[rel["SOURCE_ID"].isin(selected_ids) | rel["TARGET_ID"].isin(selected_ids)].copy()
LOGGER.info("Relationships in scope after industry filter: %d", len(rel))

# Directional supplier/customer table
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

all_rel = all_rel.merge(
    selected_companies[["FACTSET_ENTITY_ID", "ENTITY_PROPER_NAME", "INDUSTRY_CODE", "INDUSTRY_DESC"]],
    left_on="company_id",
    right_on="FACTSET_ENTITY_ID",
    how="left",
).drop(columns=["FACTSET_ENTITY_ID"])
all_rel = all_rel.rename(columns={"ENTITY_PROPER_NAME": "company_name", "INDUSTRY_CODE": "industry_code", "INDUSTRY_DESC": "industry_desc"})

relation_summary = (
    all_rel.groupby(["industry_code", "industry_desc"])
    .agg(
        relation_count=("partner_id", "size"),
        supplier_relation_count=("role", lambda s: (s == "supplier").sum()),
        customer_relation_count=("role", lambda s: (s == "customer").sum()),
        distinct_partner_count=("partner_id", pd.Series.nunique),
        avg_relation_revenue_pct=("REVENUE_PCT_NUM", "mean"),
        max_relation_revenue_pct=("REVENUE_PCT_NUM", "max"),
        earliest_relation_start=("START_DATE_DT", "min"),
        latest_relation_end=("END_DATE_DT", "max"),
        companies_with_relations=("company_id", pd.Series.nunique),
    )
    .reset_index()
)

# Company-level match table for the companies that actually appear in the filtered relation set.
relation_company_ids = pd.Index(pd.concat([all_rel["company_id"], all_rel["partner_id"]]).dropna().astype(str).unique())
company_subset = selected_companies[selected_companies["FACTSET_ENTITY_ID"].isin(relation_company_ids)].copy()
LOGGER.info("Unique companies in filtered relation universe: %d", len(company_subset))

company_match = company_subset[["FACTSET_ENTITY_ID", "ENTITY_PROPER_NAME", "ENTITY_PROPER_NAME_NORM", "INDUSTRY_CODE", "INDUSTRY_DESC"]].copy()
isin_cols = [c for c in sym.columns if "isin" in c.lower()]
ticker_cols = [c for c in sym.columns if c.lower() in ("ticker", "symbol", "primary_symbol") or "ticker" in c.lower() or "symbol" in c.lower()]
company_meta = sym[["FACTSET_ENTITY_ID"] + isin_cols + ticker_cols].drop_duplicates("FACTSET_ENTITY_ID", keep="first")
company_match = company_match.merge(company_meta, on="FACTSET_ENTITY_ID", how="left")
company_match["partner_name_norm"] = company_match["ENTITY_PROPER_NAME_NORM"].fillna("").astype(str).str.strip().str.lower()
company_match["partner_isin"] = pd.NA
for c in isin_cols:
    company_match["partner_isin"] = company_match["partner_isin"].combine_first(company_match[c].fillna("").astype(str).str.strip().str.upper())
company_match["partner_ticker"] = pd.NA
for c in ticker_cols:
    company_match["partner_ticker"] = company_match["partner_ticker"].combine_first(company_match[c].fillna("").astype(str).str.strip().str.upper())

# CDP exact by ISIN then name
LOGGER.info("Loading CDP summary")
cdp_candidates = list(DATA_RAW.rglob("*full_extract*_isin*_summary*.parquet"))
if not cdp_candidates:
    cdp_candidates = list(DATA_RAW.rglob("*full_extract*summary*.parquet"))
cdp_summary = pd.DataFrame()
if cdp_candidates:
    cdp_summary = pd.read_parquet(cdp_candidates[0])
    cdp_name_col = None
    for c in ("disclosing_organization", "disclosing_organization_name", "disclosing_organization_full", "organization_name"):
        if c in cdp_summary.columns:
            cdp_name_col = c
            break
    if cdp_name_col:
        cdp_summary["cdp_name_norm"] = cdp_summary[cdp_name_col].fillna("").astype(str).str.strip().str.lower()
    if "isin" in cdp_summary.columns:
        cdp_summary["isin"] = cdp_summary["isin"].fillna("").astype(str).str.strip().str.upper()
    cdp_id_cols = [c for c in cdp_summary.columns if any(k in c.lower() for k in ("organization_id", "participant", "cdp_id", "company_id", "disclosing_organization_id"))]
    cdp_isin_map = pd.DataFrame()
    if "isin" in cdp_summary.columns and cdp_id_cols:
        cdp_isin_map = cdp_summary[["isin", cdp_id_cols[0]]].dropna(subset=["isin"]).drop_duplicates("isin", keep="first")
        cdp_isin_map = cdp_isin_map.rename(columns={"isin": "partner_isin", cdp_id_cols[0]: "cdp_id"})
    cdp_name_map = pd.DataFrame()
    if cdp_name_col and cdp_id_cols:
        cdp_name_map = cdp_summary[["cdp_name_norm", cdp_id_cols[0]]].dropna(subset=["cdp_name_norm"]).drop_duplicates("cdp_name_norm", keep="first")
        cdp_name_map = cdp_name_map.rename(columns={cdp_id_cols[0]: "cdp_id", "cdp_name_norm": "partner_name_norm"})

    # normalize company ISIN/ticker
    for c in isin_cols:
        company_match[c] = company_match[c].fillna("").astype(str).str.strip().str.upper()
    for c in ticker_cols:
        company_match[c] = company_match[c].fillna("").astype(str).str.strip().str.upper()
    if isin_cols and not cdp_isin_map.empty:
        company_match = company_match.merge(cdp_isin_map, on="partner_isin", how="left", suffixes=("", "_cdp_isin"))
    else:
        company_match["cdp_id"] = np.nan
    if cdp_name_col and not cdp_name_map.empty:
        company_match = company_match.merge(cdp_name_map, on="partner_name_norm", how="left", suffixes=("", "_cdp_name"))
        if "cdp_id_cdp_name" in company_match.columns:
            company_match["cdp_id"] = company_match["cdp_id"].combine_first(company_match["cdp_id_cdp_name"])
            company_match = company_match.drop(columns=["cdp_id_cdp_name"])

# Trucost exact by ticker / companyname and yearly di_* aggregation
LOGGER.info("Loading Trucost")
tr_candidates = list(DATA_RAW.rglob("*trucost*.csv"))
tr_company_lookup = pd.DataFrame()
tr_yearly = pd.DataFrame()
if tr_candidates:
    tr = read_pipe(tr_candidates[0]) if tr_candidates[0].suffix.lower() == ".txt" else pd.read_csv(tr_candidates[0], dtype=str, encoding="latin-1")
    if "ticker" in tr.columns:
        tr["ticker"] = tr["ticker"].fillna("").astype(str).str.strip().str.upper()
    if "companyname" in tr.columns:
        tr["companyname_norm"] = tr["companyname"].fillna("").astype(str).str.strip().str.lower()
    if "companyid" in tr.columns:
        tr["companyid"] = tr["companyid"].fillna("").astype(str).str.strip()
    if "fiscalyear" not in tr.columns and "periodenddate" in tr.columns:
        tr["fiscalyear"] = pd.to_datetime(tr["periodenddate"], errors="coerce").dt.year
    tr_company_lookup = tr[["companyid"]].drop_duplicates("companyid", keep="first").copy()
    if "ticker" in tr.columns:
        tr_ticker = tr[["ticker", "companyid"]].dropna(subset=["ticker"]).drop_duplicates("ticker", keep="first").rename(columns={"companyid": "trucost_companyid"})
        company_match = company_match.merge(tr_ticker, left_on="partner_ticker", right_on="ticker", how="left")
    if "companyname_norm" in tr.columns:
        tr_name = tr[["companyname_norm", "companyid"]].dropna(subset=["companyname_norm"]).drop_duplicates("companyname_norm", keep="first").rename(columns={"companyid": "trucost_companyid_from_name"})
        company_match = company_match.merge(tr_name, left_on="partner_name_norm", right_on="companyname_norm", how="left")
    if "trucost_companyid" not in company_match.columns:
        company_match["trucost_companyid"] = np.nan
    if "trucost_companyid_from_name" in company_match.columns:
        company_match["trucost_companyid"] = company_match["trucost_companyid"].combine_first(company_match["trucost_companyid_from_name"])
    company_match = company_match.drop(columns=[c for c in ["trucost_companyid_from_name", "companyname_norm", "ticker"] if c in company_match.columns], errors="ignore")

    di_cols = [c for c in tr.columns if c.startswith("di_") and not c.endswith("_text")]
    di_cols = di_cols[:20]
    if di_cols and "fiscalyear" in tr.columns:
        tr["fiscalyear"] = pd.to_numeric(tr["fiscalyear"], errors="coerce")
        matched_companyids = company_match["trucost_companyid"].dropna().astype(str).unique().tolist()
        tr = tr[tr["companyid"].isin(matched_companyids)].copy()
        if not tr.empty:
            for c in di_cols:
                tr[c] = pd.to_numeric(tr[c], errors="coerce")
            tr_yearly = tr.groupby(["companyid", "fiscalyear"])[di_cols].mean().reset_index()
            tr_yearly = tr_yearly.rename(columns={"companyid": "trucost_companyid", "fiscalyear": "year"})
            tr_yearly = tr_yearly.merge(company_match[["FACTSET_ENTITY_ID", "INDUSTRY_CODE", "INDUSTRY_DESC", "trucost_companyid"]].dropna(subset=["trucost_companyid"]).drop_duplicates("trucost_companyid"), on="trucost_companyid", how="left")
            tr_yearly = tr_yearly.rename(columns={"INDUSTRY_CODE": "industry_code", "INDUSTRY_DESC": "industry_desc"})

industry_company_counts = company_subset.groupby(["INDUSTRY_CODE", "INDUSTRY_DESC"]).size().reset_index(name="company_count_in_relations_universe")
cdp_counts = pd.DataFrame(columns=["industry_code", "industry_desc", "cdp_matched_company_count", "cdp_id_count"])
if "cdp_id" in company_match.columns:
    cdp_counts = (
        company_match.assign(cdp_matched=lambda d: d["cdp_id"].notna())
        .groupby(["INDUSTRY_CODE", "INDUSTRY_DESC"])
        .agg(
            cdp_matched_company_count=("cdp_matched", "sum"),
            cdp_id_count=("cdp_id", pd.Series.nunique),
        )
        .reset_index()
        .rename(columns={"INDUSTRY_CODE": "industry_code", "INDUSTRY_DESC": "industry_desc"})
    )

tr_counts = pd.DataFrame(columns=["industry_code", "industry_desc", "trucost_matched_company_count"])
if "trucost_companyid" in company_match.columns:
    tr_counts = (
        company_match.assign(tr_matched=lambda d: d["trucost_companyid"].notna())
        .groupby(["INDUSTRY_CODE", "INDUSTRY_DESC"])
        .agg(trucost_matched_company_count=("tr_matched", "sum"))
        .reset_index()
        .rename(columns={"INDUSTRY_CODE": "industry_code", "INDUSTRY_DESC": "industry_desc"})
    )

industry_summary = relation_summary.merge(industry_company_counts.rename(columns={"INDUSTRY_CODE": "industry_code", "INDUSTRY_DESC": "industry_desc"}), on=["industry_code", "industry_desc"], how="left")
industry_summary = industry_summary.merge(cdp_counts, on=["industry_code", "industry_desc"], how="left")
industry_summary = industry_summary.merge(tr_counts, on=["industry_code", "industry_desc"], how="left")
industry_summary = industry_summary.merge(top_35.rename(columns={"INDUSTRY_CODE": "industry_code", "INDUSTRY_DESC": "industry_desc"}), on=["industry_code", "industry_desc"], how="left")

industry_summary.to_csv(OUT_DIR / "top35_industry_summary.csv", index=False)
top_35.to_csv(OUT_DIR / "top35_factset_industries.csv", index=False)
if not tr_yearly.empty:
    tr_yearly.to_csv(OUT_DIR / "top35_industry_trucost_yearly.csv", index=False)

LOGGER.info("Wrote top35_industry_summary.csv (rows=%d)", len(industry_summary))
LOGGER.info("Wrote top35_industry_trucost_yearly.csv (rows=%d)", len(tr_yearly))
print("Done")

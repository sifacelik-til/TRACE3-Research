"""Aggregate FactSet supply-chain data for selected industries.

Scope:
- FactSet industry codes 1105-3130
- plus electronics / high-tech manufacturing related industries by description

Outputs:
- data/processed/selected_industry_summary.csv
- data/processed/selected_industry_trucost_yearly.csv
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


LOGGER.info("Loading FactSet entities")
sym = read_pipe(sym_entity)
sym.columns = [c.strip().strip('"') for c in sym.columns]
sym = sym.rename(columns={sym.columns[0]: "FACTSET_ENTITY_ID", sym.columns[1]: "ENTITY_PROPER_NAME"})
sym["ENTITY_PROPER_NAME_NORM"] = sym["ENTITY_PROPER_NAME"].fillna("").astype(str).str.strip().str.lower()
sym = sym.drop_duplicates(subset=["FACTSET_ENTITY_ID"], keep="first").copy()

LOGGER.info("Loading industry map")
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

code_num = pd.to_numeric(companies["INDUSTRY_CODE"], errors="coerce")
desc = companies["INDUSTRY_DESC"].fillna("").astype(str).str.lower()
range_mask = code_num.between(1105, 3130, inclusive="both")
keyword_mask = desc.str.contains(
    "electronic|electronics|semiconductor|computer|high tech|technology|telecommunications|aerospace|defense|electrical products|electronic production equipment",
    regex=True,
    na=False,
)
selected = companies[range_mask | keyword_mask].copy()
selected = selected.drop_duplicates(subset=["FACTSET_ENTITY_ID"], keep="first").copy()
selected_codes = (
    selected.groupby(["INDUSTRY_CODE", "INDUSTRY_DESC"])
    .size()
    .reset_index(name="company_count")
    .sort_values(["company_count", "INDUSTRY_CODE"], ascending=[False, True])
)

selected_codes.to_csv(OUT_DIR / "selected_factset_industries.csv", index=False)
LOGGER.info("Selected industries: %d", len(selected_codes))

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

selected_ids = set(selected["FACTSET_ENTITY_ID"].astype(str))
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

all_rel = all_rel.merge(
    selected[["FACTSET_ENTITY_ID", "ENTITY_PROPER_NAME", "INDUSTRY_CODE", "INDUSTRY_DESC"]],
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

relation_ids = pd.Index(pd.concat([all_rel["company_id"], all_rel["partner_id"]]).dropna().astype(str).unique())
company_subset = selected[selected["FACTSET_ENTITY_ID"].isin(relation_ids)].copy()
LOGGER.info("Companies in filtered relation universe: %d", len(company_subset))

# Match Trucost companies exactly by ticker or company name
LOGGER.info("Loading Trucost")
tr_candidates = list(DATA_RAW.rglob("*trucost*.csv"))
tr_yearly = pd.DataFrame()
if tr_candidates:
    tr = pd.read_csv(tr_candidates[0], dtype=str, encoding="latin-1")
    if "ticker" in tr.columns:
        tr["ticker"] = tr["ticker"].fillna("").astype(str).str.strip().str.upper()
    if "companyname" in tr.columns:
        tr["companyname_norm"] = tr["companyname"].fillna("").astype(str).str.strip().str.lower()
    if "companyid" in tr.columns:
        tr["companyid"] = tr["companyid"].fillna("").astype(str).str.strip()
    if "fiscalyear" not in tr.columns and "periodenddate" in tr.columns:
        tr["fiscalyear"] = pd.to_datetime(tr["periodenddate"], errors="coerce").dt.year

    tr_company_map = company_subset[["FACTSET_ENTITY_ID", "ENTITY_PROPER_NAME", "ENTITY_PROPER_NAME_NORM"]].copy()
    tr_company_map = tr_company_map.merge(
        sym[["FACTSET_ENTITY_ID"] + [c for c in sym.columns if c.lower() in ("ticker", "symbol", "primary_symbol") or "ticker" in c.lower() or "symbol" in c.lower()]],
        on="FACTSET_ENTITY_ID",
        how="left",
    )
    ticker_cols = [c for c in tr_company_map.columns if c.lower() in ("ticker", "symbol", "primary_symbol") or "ticker" in c.lower() or "symbol" in c.lower()]
    tr_company_map["partner_ticker"] = pd.NA
    for c in ticker_cols:
        tr_company_map["partner_ticker"] = tr_company_map["partner_ticker"].combine_first(tr_company_map[c].fillna("").astype(str).str.strip().str.upper())
    tr_company_map["partner_name_norm"] = tr_company_map["ENTITY_PROPER_NAME_NORM"].fillna("").astype(str).str.strip().str.lower()

    tr_ticker = pd.DataFrame()
    if "ticker" in tr.columns:
        tr_ticker = tr[["ticker", "companyid"]].dropna(subset=["ticker"]).drop_duplicates("ticker", keep="first").rename(columns={"ticker": "partner_ticker", "companyid": "trucost_companyid"})
    tr_name = pd.DataFrame()
    if "companyname_norm" in tr.columns:
        tr_name = tr[["companyname_norm", "companyid"]].dropna(subset=["companyname_norm"]).drop_duplicates("companyname_norm", keep="first").rename(columns={"companyname_norm": "partner_name_norm", "companyid": "trucost_companyid_from_name"})

    tr_match = tr_company_map[["FACTSET_ENTITY_ID", "partner_ticker", "partner_name_norm"]].drop_duplicates()
    if not tr_ticker.empty:
        tr_match = tr_match.merge(tr_ticker, on="partner_ticker", how="left")
    else:
        tr_match["trucost_companyid"] = np.nan
    if not tr_name.empty:
        tr_match = tr_match.merge(tr_name, on="partner_name_norm", how="left")
        tr_match["trucost_companyid"] = tr_match["trucost_companyid"].combine_first(tr_match["trucost_companyid_from_name"])
        tr_match = tr_match.drop(columns=["trucost_companyid_from_name"], errors="ignore")

    matched_companyids = tr_match["trucost_companyid"].dropna().astype(str).unique().tolist()
    tr = tr[tr["companyid"].isin(matched_companyids)].copy()

    available_di_cols = [c for c in TRUCOST_DI_COLS if c in tr.columns]
    if available_di_cols and "fiscalyear" in tr.columns:
        tr["fiscalyear"] = pd.to_numeric(tr["fiscalyear"], errors="coerce")
        for c in available_di_cols:
            tr[c] = pd.to_numeric(tr[c], errors="coerce")
        tr = tr.merge(tr_match[["FACTSET_ENTITY_ID", "trucost_companyid"]], left_on="companyid", right_on="trucost_companyid", how="left")
        tr = tr.merge(
            selected[["FACTSET_ENTITY_ID", "INDUSTRY_CODE", "INDUSTRY_DESC"]].drop_duplicates("FACTSET_ENTITY_ID"),
            on="FACTSET_ENTITY_ID",
            how="left",
        )
        tr = tr.dropna(subset=["INDUSTRY_CODE", "INDUSTRY_DESC"])
        tr_yearly = (
            tr.groupby(["INDUSTRY_CODE", "INDUSTRY_DESC", "fiscalyear"])[available_di_cols]
            .mean()
            .reset_index()
            .rename(columns={"fiscalyear": "year", "INDUSTRY_CODE": "industry_code", "INDUSTRY_DESC": "industry_desc"})
        )

industry_summary = relation_summary.merge(
    selected_codes.rename(columns={"INDUSTRY_CODE": "industry_code", "INDUSTRY_DESC": "industry_desc"}),
    on=["industry_code", "industry_desc"],
    how="left",
)

industry_summary.to_csv(OUT_DIR / "selected_industry_summary.csv", index=False)
selected_codes.to_csv(OUT_DIR / "selected_factset_industries.csv", index=False)
if not tr_yearly.empty:
    tr_yearly.to_csv(OUT_DIR / "selected_industry_trucost_yearly.csv", index=False)
else:
    pd.DataFrame(columns=["industry_code", "industry_desc", "year"] + TRUCOST_DI_COLS).to_csv(
        OUT_DIR / "selected_industry_trucost_yearly.csv", index=False
    )

LOGGER.info("Wrote selected_industry_summary.csv (rows=%d)", len(industry_summary))
LOGGER.info("Wrote selected_industry_trucost_yearly.csv (rows=%d)", len(tr_yearly))
print("Done")

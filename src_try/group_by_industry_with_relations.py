"""Group FactSet entities by industry and attach relationship metadata, CDP IDs, and Trucost di_* values by year.

This version avoids wide pivot merges by doing per-row exact lookups, so it remains tractable on the full dataset.
"""
from pathlib import Path
import logging
import re
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
LOGGER = logging.getLogger(__name__)

DATA_RAW = Path('data') / 'raw'
FACTSET_DIR = DATA_RAW / 'FactSet'
OUT_DIR = Path('data') / 'processed'
OUT_DIR.mkdir(parents=True, exist_ok=True)

sym_entity = FACTSET_DIR / 'sym_entity_v1_full_12328' / 'sym_entity.txt'
sym_sector = FACTSET_DIR / 'sym_entity_v1_full_12328' / 'sym_entity_sector.txt'
relationships = FACTSET_DIR / 'ent_supply_chain_v1_full_3856' / 'ent_scr_relationships.txt'
industry_map = FACTSET_DIR / 'ref_hub_v2_full_3565' / 'factset_industry_map.txt'

for p in (sym_entity, sym_sector, relationships, industry_map):
    if not p.exists():
        raise SystemExit(f'Missing required file: {p}')

# FactSet entity master
LOGGER.info('Loading FactSet entities')
try:
    sym = pd.read_csv(sym_entity, sep='|', quotechar='"', dtype=str, encoding='utf-8')
except Exception:
    sym = pd.read_csv(sym_entity, sep='|', quotechar='"', dtype=str, encoding='latin-1')
sym.columns = [c.strip().strip('"') for c in sym.columns]
sym = sym.rename(columns={sym.columns[0]: 'FACTSET_ENTITY_ID', sym.columns[1]: 'ENTITY_PROPER_NAME'})
sym['ENTITY_PROPER_NAME_NORM'] = sym['ENTITY_PROPER_NAME'].fillna('').astype(str).str.strip().str.lower()

# FactSet sector + industry mapping
LOGGER.info('Loading sector + industry metadata')
try:
    sector = pd.read_csv(sym_sector, sep='|', quotechar='"', dtype=str, encoding='utf-8')
except Exception:
    sector = pd.read_csv(sym_sector, sep='|', quotechar='"', dtype=str, encoding='latin-1')
sector.columns = [c.strip().strip('"') for c in sector.columns]
sector = sector.rename(columns={sector.columns[0]: 'FACTSET_ENTITY_ID', sector.columns[2]: 'INDUSTRY_CODE', sector.columns[3]: 'SECTOR_CODE'})
sector = sector[['FACTSET_ENTITY_ID', 'INDUSTRY_CODE']].copy()

try:
    ind_map = pd.read_csv(industry_map, sep='|', quotechar='"', dtype=str, encoding='utf-8')
except Exception:
    ind_map = pd.read_csv(industry_map, sep='|', quotechar='"', dtype=str, encoding='latin-1')
ind_map.columns = [c.strip().strip('"') for c in ind_map.columns]
ind_map = ind_map.rename(columns={ind_map.columns[0]: 'INDUSTRY_CODE', ind_map.columns[1]: 'INDUSTRY_DESC'})

companies = sym[['FACTSET_ENTITY_ID', 'ENTITY_PROPER_NAME', 'ENTITY_PROPER_NAME_NORM']].merge(
    sector, on='FACTSET_ENTITY_ID', how='left'
).merge(ind_map[['INDUSTRY_CODE', 'INDUSTRY_DESC']], on='INDUSTRY_CODE', how='left')
companies['INDUSTRY_CODE'] = companies['INDUSTRY_CODE'].fillna('9999')
companies['INDUSTRY_DESC'] = companies['INDUSTRY_DESC'].fillna('Not Classified')
companies = companies.drop_duplicates(subset=['FACTSET_ENTITY_ID'], keep='first').copy()
company_name_map = companies.set_index('FACTSET_ENTITY_ID')['ENTITY_PROPER_NAME'].to_dict()
company_industry_map = companies.set_index('FACTSET_ENTITY_ID')[['INDUSTRY_CODE', 'INDUSTRY_DESC']].to_dict('index')

# Focus on the top 35 industries by company count
top_industry_counts = (
    companies.groupby(['INDUSTRY_CODE', 'INDUSTRY_DESC'])
    .size()
    .reset_index(name='company_count')
    .sort_values(['company_count', 'INDUSTRY_CODE'], ascending=[False, True])
)
top_35_industries = top_industry_counts.head(35).copy()
top_35_codes = top_35_industries['INDUSTRY_CODE'].astype(str).tolist()
companies = companies[companies['INDUSTRY_CODE'].astype(str).isin(top_35_codes)].copy()
company_name_map = companies.set_index('FACTSET_ENTITY_ID')['ENTITY_PROPER_NAME'].to_dict()
company_industry_map = companies.set_index('FACTSET_ENTITY_ID')[['INDUSTRY_CODE', 'INDUSTRY_DESC']].to_dict('index')
top_35_industries.to_csv(OUT_DIR / 'top35_factset_industries.csv', index=False)
LOGGER.info('Selected top 35 industries; companies in scope: %d', len(companies))

# FactSet relationship rows
LOGGER.info('Loading relationships')
try:
    rel = pd.read_csv(relationships, sep='|', quotechar='"', dtype=str, encoding='utf-8')
except Exception:
    rel = pd.read_csv(relationships, sep='|', quotechar='"', dtype=str, encoding='latin-1')
rel.columns = [c.strip().strip('"') for c in rel.columns]
if len(rel.columns) >= 4:
    rel = rel.rename(columns={rel.columns[0]: 'ID', rel.columns[1]: 'REL_TYPE', rel.columns[2]: 'SOURCE_FACTSET_ENTITY_ID', rel.columns[3]: 'TARGET_FACTSET_ENTITY_ID'})
for c in ('START_DATE', 'END_DATE', 'REVENUE_PCT'):
    if c not in rel.columns:
        rel[c] = None
rel['SOURCE_ID'] = rel['SOURCE_FACTSET_ENTITY_ID'].fillna('').astype(str).str.strip().str.strip('"')
rel['TARGET_ID'] = rel['TARGET_FACTSET_ENTITY_ID'].fillna('').astype(str).str.strip().str.strip('"')
rel['REVENUE_PCT_NUM'] = pd.to_numeric(rel['REVENUE_PCT'], errors='coerce')
rel['START_DATE_DT'] = pd.to_datetime(rel['START_DATE'], errors='coerce')
rel['END_DATE_DT'] = pd.to_datetime(rel['END_DATE'], errors='coerce')

# Keep only relationships involving the top-35-industry company universe
selected_company_ids = set(companies['FACTSET_ENTITY_ID'].astype(str))
rel = rel[rel['SOURCE_ID'].isin(selected_company_ids) | rel['TARGET_ID'].isin(selected_company_ids)].copy()
LOGGER.info('Relationships in scope after industry filter: %d', len(rel))

src = rel[['SOURCE_ID', 'TARGET_ID', 'REL_TYPE', 'START_DATE_DT', 'END_DATE_DT', 'REVENUE_PCT_NUM']].copy()
src = src.rename(columns={'SOURCE_ID': 'company_id', 'TARGET_ID': 'partner_id'})
src['company_is_source'] = True

tgt = rel[['TARGET_ID', 'SOURCE_ID', 'REL_TYPE', 'START_DATE_DT', 'END_DATE_DT', 'REVENUE_PCT_NUM']].copy()
tgt = tgt.rename(columns={'TARGET_ID': 'company_id', 'SOURCE_ID': 'partner_id'})
tgt['company_is_source'] = False

all_rel = pd.concat([src, tgt], ignore_index=True)
all_rel = all_rel[all_rel['company_id'].astype(str).str.len() > 0].copy()
all_rel['REL_TYPE_UP'] = all_rel['REL_TYPE'].fillna('').astype(str).str.upper()
all_rel['role'] = 'related'
all_rel.loc[(all_rel['company_is_source']) & all_rel['REL_TYPE_UP'].str.contains('SUPPLIER'), 'role'] = 'customer'
all_rel.loc[(~all_rel['company_is_source']) & all_rel['REL_TYPE_UP'].str.contains('SUPPLIER'), 'role'] = 'supplier'
all_rel.loc[(all_rel['company_is_source']) & all_rel['REL_TYPE_UP'].str.contains('CUSTOMER'), 'role'] = 'supplier'
all_rel.loc[(~all_rel['company_is_source']) & all_rel['REL_TYPE_UP'].str.contains('CUSTOMER'), 'role'] = 'customer'
all_rel['relation_start_date'] = all_rel['START_DATE_DT']
all_rel['relation_end_date'] = all_rel['END_DATE_DT']
all_rel['relation_revenue_pct'] = all_rel['REVENUE_PCT_NUM']
all_rel['customer_revenue_pct'] = np.where(all_rel['role'] == 'customer', all_rel['REVENUE_PCT_NUM'], np.nan)
# Keep only supply-chain roles for this report
all_rel = all_rel[all_rel['role'].isin(['supplier', 'customer'])].copy()
all_rel = all_rel.drop_duplicates(subset=['company_id', 'partner_id', 'REL_TYPE', 'START_DATE_DT', 'END_DATE_DT', 'REVENUE_PCT_NUM'])

# Partner metadata for lookup
partner_id_map = sym[['FACTSET_ENTITY_ID', 'ENTITY_PROPER_NAME', 'ENTITY_PROPER_NAME_NORM']].copy()
if 'ISO_COUNTRY' in sym.columns:
    partner_id_map = partner_id_map.merge(sym[['FACTSET_ENTITY_ID', 'ISO_COUNTRY']], on='FACTSET_ENTITY_ID', how='left')
else:
    partner_id_map['ISO_COUNTRY'] = np.nan
partner_id_map = partner_id_map.rename(columns={'FACTSET_ENTITY_ID': 'partner_id', 'ENTITY_PROPER_NAME': 'partner_name', 'ENTITY_PROPER_NAME_NORM': 'partner_name_norm', 'ISO_COUNTRY': 'partner_country'})
partner_metadata = partner_id_map.set_index('partner_id').to_dict('index')

# CDP summary exact lookup by ISIN (and exact name fallback)
LOGGER.info('Loading CDP summary')
cdp_summary = pd.DataFrame()
cdp_candidates = list(DATA_RAW.rglob('*full_extract*_isin*_summary*.parquet'))
if not cdp_candidates:
    cdp_candidates = list(DATA_RAW.rglob('*full_extract*summary*.parquet'))
if cdp_candidates:
    cdp_path = cdp_candidates[0]
    cdp_summary = pd.read_parquet(cdp_path)
    # exact name normalized
    cdp_name_candidates = [c for c in ('disclosing_organization','disclosing_organization_name','disclosing_organization_full','organization_name') if c in cdp_summary.columns]
    if cdp_name_candidates:
        cdp_name_col = cdp_name_candidates[0]
        cdp_summary['cdp_name_norm'] = cdp_summary[cdp_name_col].fillna('').astype(str).str.strip().str.lower()
    if 'isin' in cdp_summary.columns:
        cdp_summary['isin'] = cdp_summary['isin'].fillna('').astype(str).str.strip().str.upper()
cdp_by_isin = {}
if not cdp_summary.empty and 'isin' in cdp_summary.columns:
    for _, row in cdp_summary.dropna(subset=['isin']).iterrows():
        cdp_by_isin[str(row['isin']).upper()] = row
cdp_name_lookup = {}
if not cdp_summary.empty and 'cdp_name_norm' in cdp_summary.columns:
    for _, row in cdp_summary.dropna(subset=['cdp_name_norm']).iterrows():
        cdp_name_lookup[str(row['cdp_name_norm']).lower()] = row
cdp_id_columns = []
if not cdp_summary.empty:
    cdp_id_columns = [
        c for c in cdp_summary.columns
        if any(k in c.lower() for k in ('organization_id', 'participant', 'cdp_id', 'company_id', 'disclosing_organization_id'))
    ]

# Trucost lookup (name/ticker exact; companyid to di_ values by year)
LOGGER.info('Loading Trucost metadata')
tr_lookup = {}
tr_companyid_from_ticker = {}
tr_companyid_from_name = {}
tr_candidates = list(DATA_RAW.rglob('*trucost*.csv'))
if tr_candidates:
    tr_path = tr_candidates[0]
    try:
        tr = pd.read_csv(tr_path, dtype=str, encoding='utf-8')
    except Exception:
        tr = pd.read_csv(tr_path, dtype=str, encoding='latin-1')
    if 'ticker' in tr.columns:
        tr['ticker'] = tr['ticker'].fillna('').astype(str).str.strip().str.upper()
        tr_companyid_from_ticker = dict(zip(tr['ticker'], tr['companyid']))
    if 'companyname' in tr.columns:
        tr['companyname_norm'] = tr['companyname'].fillna('').astype(str).str.strip().str.lower()
        tr_companyid_from_name = dict(zip(tr['companyname_norm'], tr['companyid']))
    # Build per companyid di_ map by year (only numeric metrics)
    numeric_di_cols = []
    for c in tr.columns:
        if c.startswith('di_') and not c.endswith('_text'):
            numeric_di_cols.append(c)
    di_cols = sorted(set(numeric_di_cols))
    for _, row in tr[['companyid', 'fiscalyear'] + di_cols].dropna(subset=['companyid', 'fiscalyear']).iterrows():
        cid = str(row['companyid']).strip()
        yr = str(int(float(row['fiscalyear']))) if pd.notna(row['fiscalyear']) else None
        if yr is None:
            continue
        if cid not in tr_lookup:
            tr_lookup[cid] = {}
        for c in di_cols:
            val = pd.to_numeric(row[c], errors='coerce')
            if pd.notna(val):
                tr_lookup[cid][f'{c}_{yr}'] = float(val)

# Helper exact match functions

def get_cdp_id_for_partner(pid):
    if pid is None or pid == 'nan':
        return None
    row = sym[sym['FACTSET_ENTITY_ID'] == pid]
    if row.empty:
        return None
    r = row.iloc[0]
    # ISIN lookup
    for c in [x for x in sym.columns if 'isin' in x.lower()]:
        val = str(r.get(c, '')).strip().upper()
        if val and val in cdp_by_isin:
            m = cdp_by_isin[val]
            # pick first non-isin id-like field
            for id_col in cdp_id_columns:
                if id_col in m.index and str(m[id_col]).strip():
                    return str(m[id_col]).strip()
    # exact name fallback
    name = str(r['ENTITY_PROPER_NAME_NORM']).strip().lower()
    if name in cdp_name_lookup:
        row2 = cdp_name_lookup[name]
        for id_col in cdp_id_columns:
            if str(row2[id_col]).strip():
                return str(row2[id_col]).strip()
    return None


def get_trucost_companyid_for_partner(pid):
    if pid is None or pid == 'nan':
        return None
    row = sym[sym['FACTSET_ENTITY_ID'] == pid]
    if row.empty:
        return None
    r = row.iloc[0]
    # exact ticker match
    for c in sym.columns:
        if c.lower() in ('ticker','symbol','primary_symbol') or 'ticker' in c.lower() or 'symbol' in c.lower():
            val = str(r.get(c, '')).strip().upper()
            if val and val in tr_companyid_from_ticker:
                return str(tr_companyid_from_ticker[val])
    # exact name match
    name = str(r['ENTITY_PROPER_NAME_NORM']).strip().lower()
    if name in tr_companyid_from_name:
        return str(tr_companyid_from_name[name])
    return None

# Build final rows
rows = []
company_ids = sorted(set(all_rel['company_id'].dropna().astype(str).tolist()))
for cid in company_ids:
    company_name = company_name_map.get(cid)
    ind = company_industry_map.get(cid, {'INDUSTRY_CODE': '9999', 'INDUSTRY_DESC': 'Not Classified'})
    rel_rows = all_rel[all_rel['company_id'] == cid].copy()
    if rel_rows.empty:
        continue
    rel_rows = rel_rows.sort_values(['REVENUE_PCT_NUM', 'START_DATE_DT'], ascending=[False, False], na_position='last').reset_index(drop=True)
    rel_rows['relevance_rank'] = rel_rows.index + 1
    for _, r in rel_rows.iterrows():
        pid = str(r['partner_id']).strip()
        meta = partner_metadata.get(pid, {'partner_name': None, 'partner_country': None})
        cdp_id = get_cdp_id_for_partner(pid)
        tr_companyid = get_trucost_companyid_for_partner(pid)
        di_values = tr_lookup.get(str(tr_companyid), {}) if tr_companyid else {}
        row = {
            'company_id': cid,
            'company_name': company_name,
            'industry_code': ind['INDUSTRY_CODE'],
            'industry_desc': ind['INDUSTRY_DESC'],
            'partner_id': pid,
            'partner_name': meta.get('partner_name'),
            'partner_country': meta.get('partner_country'),
            'relation_type': r['REL_TYPE'],
            'role': r['role'],
            'relation_start_date': r['START_DATE_DT'],
            'relation_end_date': r['END_DATE_DT'],
            'relation_revenue_pct': r['REVENUE_PCT_NUM'],
            'relevance_rank': r['relevance_rank'],
            'customer_revenue_pct': r['customer_revenue_pct'],
            'cdp_id': cdp_id,
            'trucost_companyid': tr_companyid,
        }
        for key, val in di_values.items():
            row[key] = val
        rows.append(row)

final_df = pd.DataFrame(rows)
if not final_df.empty:
    # keep stable ordering and consistent column names
    final_cols = [
        'company_id','company_name','industry_code','industry_desc',
        'partner_id','partner_name','partner_country',
        'relation_type','role','relation_start_date','relation_end_date','relation_revenue_pct',
        'relevance_rank','customer_revenue_pct','cdp_id','trucost_companyid'
    ]
    for c in sorted(final_df.columns):
        if c.startswith('di_'):
            final_cols.append(c)
    final_df = final_df[final_cols]

consolidated = OUT_DIR / 'factset_by_industry_with_relations.csv'
final_df.to_csv(consolidated, index=False)
LOGGER.info('Wrote consolidated dataset: %s (rows=%d)', consolidated, len(final_df))

if not final_df.empty:
    for (code, desc), g in final_df.groupby(['industry_code', 'industry_desc'], dropna=False):
        slug = re.sub(r'[^a-z0-9]+', '_', str(desc).lower()).strip('_')
        out_path = OUT_DIR / f'industry_{code}_{slug}.csv'
        g.to_csv(out_path, index=False)
        LOGGER.info('Wrote industry CSV: %s (rows=%d)', out_path, len(g))

print('Done')

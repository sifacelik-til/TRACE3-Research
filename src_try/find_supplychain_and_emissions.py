"""
Find supply-chain related companies (suppliers and customers) for a list of target companies using FactSet relationships,
then match those related companies to CDP and Trucost datasets and export one CSV per target.

Outputs:
 - data/processed/{target_slug}_supplychain.csv

Matching strategy:
 - Prefer ISIN-based join when ISIN is available in FactSet or CDP
 - Then prefer exact ticker join (if tickers are available)
 - Finally fallback to fuzzy name matching (rapidfuzz, threshold 85)

Notes:
 - Expects FactSet files under data/raw/FactSet (sym_entity.txt, ent_scr_relationships.txt)
 - Attempts to auto-detect CDP summary parquet and Trucost CSV under data/raw
"""
from pathlib import Path
import pandas as pd
import logging
from rapidfuzz import process, fuzz
import re

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
LOGGER = logging.getLogger(__name__)

DATA_RAW = Path('data') / 'raw'
FACTSET_DIR = DATA_RAW / 'FactSet'
OUT_DIR = Path('data') / 'processed'
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Targets
targets = [
    'Dematic',
    'SSI Schäfer',
    'BEUMER',
    'Swisslog',
    'KNAPP',
    'TGW',
    'Daifuku'
]

# File paths
sym_entity = FACTSET_DIR / 'sym_entity_v1_full_12328' / 'sym_entity.txt'
relationships = FACTSET_DIR / 'ent_supply_chain_v1_full_3856' / 'ent_scr_relationships.txt'

if not sym_entity.exists() or not relationships.exists():
    LOGGER.error('Required FactSet files not found: %s or %s', sym_entity, relationships)
    raise SystemExit(1)

# Load sym_entity with encoding fallbacks
LOGGER.info('Loading FactSet entity list from %s', sym_entity)
try:
    sym = pd.read_csv(sym_entity, sep='|', quotechar='"', dtype=str, encoding='utf-8')
except Exception:
    try:
        sym = pd.read_csv(sym_entity, sep='|', quotechar='"', dtype=str, encoding='latin-1')
    except Exception:
        sym = pd.read_csv(sym_entity, sep='|', quotechar='"', dtype=str, encoding='cp1252')
sym.columns = [c.strip().strip('"') for c in sym.columns]
# Ensure expected columns
sym = sym.rename(columns={sym.columns[0]:'FACTSET_ENTITY_ID', sym.columns[1]:'ENTITY_PROPER_NAME'})
if len(sym.columns) >= 3:
    sym = sym.rename(columns={sym.columns[2]:'ISO_COUNTRY'})

sym['ENTITY_PROPER_NAME_norm'] = sym['ENTITY_PROPER_NAME'].fillna('').astype(str).str.strip().str.lower()

# Try to find ISIN/ticker columns in sym if present
isin_cols = [c for c in sym.columns if 'isin' in c.lower()]
ticker_cols = [c for c in sym.columns if c.lower() in ('ticker','symbol','primary_symbol') or 'ticker' in c.lower() or 'symbol' in c.lower()]

# Load relationships with encoding fallback
LOGGER.info('Loading FactSet relationships from %s', relationships)
try:
    rel = pd.read_csv(relationships, sep='|', quotechar='"', dtype=str, encoding='utf-8')
except Exception:
    try:
        rel = pd.read_csv(relationships, sep='|', quotechar='"', dtype=str, encoding='latin-1')
    except Exception:
        rel = pd.read_csv(relationships, sep='|', quotechar='"', dtype=str, encoding='cp1252')
rel.columns = [c.strip().strip('"') for c in rel.columns]
# expected: ID | REL_TYPE | SOURCE_FACTSET_ENTITY_ID | TARGET_FACTSET_ENTITY_ID | ...
rel = rel.rename(columns={rel.columns[0]:'ID', rel.columns[1]:'REL_TYPE', rel.columns[2]:'SOURCE_FACTSET_ENTITY_ID', rel.columns[3]:'TARGET_FACTSET_ENTITY_ID'})

# Load CDP summary parquet (prefer ISIN summary)
cdp_summary = None
cdp_name_col = None
cdp_parquet_candidates = list(DATA_RAW.rglob('*full_extract*_isin*_summary*.parquet'))
if not cdp_parquet_candidates:
    cdp_parquet_candidates = list(DATA_RAW.rglob('*full_extract*summary*.parquet'))
if cdp_parquet_candidates:
    cdp_parquet = cdp_parquet_candidates[0]
    LOGGER.info('Loading CDP summary parquet: %s', cdp_parquet)
    cdp_summary = pd.read_parquet(cdp_parquet)
    # find name column
    for col in ('disclosing_organization','disclosing_organization_name','disclosing_organization_full','organization_name'):
        if col in cdp_summary.columns:
            cdp_name_col = col
            break
    if not cdp_name_col:
        # fallback to first string column
        for col in cdp_summary.columns:
            if pd.api.types.is_string_dtype(cdp_summary[col]):
                cdp_name_col = col
                break
    cdp_summary['cdp_name_norm'] = cdp_summary[cdp_name_col].fillna('').astype(str).str.strip().str.lower()
    # detect potential id columns in CDP
    cdp_id_cols = [c for c in cdp_summary.columns if any(k in c.lower() for k in ('organization_id','participant','cdp_id','disclosing_organization_id','company_id','isin'))]
else:
    LOGGER.info('No CDP summary found; CDP matching will be skipped')
    cdp_id_cols = []

# Load Trucost CSV
tr = None
trucost_candidates = list(DATA_RAW.rglob('*trucost*.csv'))
if trucost_candidates:
    trucost_path = trucost_candidates[0]
    LOGGER.info('Loading Trucost: %s', trucost_path)
    try:
        tr = pd.read_csv(trucost_path, dtype=str, encoding='utf-8')
    except Exception:
        tr = pd.read_csv(trucost_path, dtype=str, encoding='latin-1')
    # normalize
    if 'companyname' in tr.columns:
        tr['companyname_norm'] = tr['companyname'].fillna('').astype(str).str.strip().str.lower()
    else:
        # try common name cols
        for col in tr.columns:
            if 'name' in col.lower():
                tr['companyname_norm'] = tr[col].fillna('').astype(str).str.strip().str.lower()
                break
    # find emission-like columns
    emis_patterns = ('emiss','ghg','co2','scope','tco2','tonne','tonnes','total_energy')
    tr_emis_cols = [c for c in tr.columns if any(p in c.lower() for p in emis_patterns)]
else:
    LOGGER.info('No Trucost CSV found; Trucost matching will be skipped')
    tr_emis_cols = []

# Helper match functions
from functools import lru_cache

@lru_cache(maxsize=1024)
def match_cdp_by_name(name):
    if cdp_summary is None or not name:
        return None
    # exact
    exact = cdp_summary[cdp_summary['cdp_name_norm'] == name]
    if not exact.empty:
        return exact.iloc[0]
    # fuzzy
    cand = process.extractOne(name, cdp_summary['cdp_name_norm'].unique().tolist(), scorer=fuzz.token_sort_ratio)
    if cand and cand[1] >= 85:
        return cdp_summary[cdp_summary['cdp_name_norm'] == cand[0]].iloc[0]
    return None

@lru_cache(maxsize=1024)
def match_trucost_by_name(name):
    if tr is None or not name:
        return None
    exact = tr[tr['companyname_norm'] == name]
    if not exact.empty:
        return exact.iloc[0]
    cand = process.extractOne(name, tr['companyname_norm'].unique().tolist(), scorer=fuzz.token_sort_ratio)
    if cand and cand[1] >= 85:
        return tr[tr['companyname_norm'] == cand[0]].iloc[0]
    return None

# utility to slugify target for file names
def slug(s):
    s = s.lower()
    s = re.sub(r'[^a-z0-9]+','_', s)
    s = re.sub(r'_+','_', s).strip('_')
    return s

# For each target: find matching FactSet entities and their related partners
entity_names = sym['ENTITY_PROPER_NAME_norm'].tolist()

for target in targets:
    LOGGER.info('Processing target: %s', target)
    t_norm = target.strip().lower()
    # find candidate FactSet entities (contains or fuzzy)
    matches = sym[sym['ENTITY_PROPER_NAME_norm'].str.contains(t_norm, na=False)]
    if matches.empty:
        best = process.extractOne(t_norm, entity_names, scorer=fuzz.token_sort_ratio)
        if best and best[1] >= 80:
            matched_name = best[0]
            matches = sym[sym['ENTITY_PROPER_NAME_norm'] == matched_name]
    if matches.empty:
        LOGGER.warning('No FactSet entity found for target: %s', target)
        continue
    # collect related partners
    related = []
    for _, ent in matches.iterrows():
        ent_id = ent['FACTSET_ENTITY_ID']
        ent_name = ent['ENTITY_PROPER_NAME']
        ent_country = ent.get('ISO_COUNTRY', None)
        # relationships where either source or target matches ent_id
        # strip quotes in rel ids for comparison
        rel_src = rel['SOURCE_FACTSET_ENTITY_ID'].fillna('').astype(str).str.strip().str.strip('"')
        rel_tgt = rel['TARGET_FACTSET_ENTITY_ID'].fillna('').astype(str).str.strip().str.strip('"')
        # where source == ent_id or target == ent_id
        mask = (rel_src == ent_id) | (rel_tgt == ent_id)
        rel_rows = rel[mask]
        for _, r in rel_rows.iterrows():
            rtype = r.get('REL_TYPE', '')
            src = str(r.get('SOURCE_FACTSET_ENTITY_ID','')).strip().strip('"')
            tgt = str(r.get('TARGET_FACTSET_ENTITY_ID','')).strip().strip('"')
            # determine partner id and role
            if src == ent_id and tgt != ent_id:
                partner_id = tgt
                # if relation type mentions 'SUPPLIER' then partner is supplier? Convention uncertain; infer:
                # If REL_TYPE contains 'SUPPLIER' then source -> target means SOURCE is buyer and TARGET is supplier. So partner role = 'supplier'
                if 'SUPPLIER' in rtype.upper():
                    role = 'supplier'
                elif 'CUSTOMER' in rtype.upper():
                    role = 'customer'
                else:
                    role = 'related'
            elif tgt == ent_id and src != ent_id:
                partner_id = src
                # if REL_TYPE contains 'SUPPLIER' and target == ent -> partner (source) is supplier
                if 'SUPPLIER' in rtype.upper():
                    role = 'supplier'
                elif 'CUSTOMER' in rtype.upper():
                    role = 'customer'
                else:
                    role = 'related'
            else:
                continue
            related.append({'target_factset_id': ent_id, 'target_factset_name': ent_name, 'target_country': ent_country, 'partner_factset_id': partner_id, 'rel_type': rtype, 'role': role, 'rel_start_date': r.get('START_DATE'), 'rel_end_date': r.get('END_DATE'), 'rel_revenue_pct': r.get('REVENUE_PCT')})
    if not related:
        LOGGER.info('No related partners found for %s', target)
        continue
    df_rel = pd.DataFrame(related).drop_duplicates()
    # enrich partners with FactSet names
    def lookup_name(fid):
        row = sym[sym['FACTSET_ENTITY_ID']==fid]
        if not row.empty:
            return row.iloc[0]['ENTITY_PROPER_NAME'], row.iloc[0].get('ISO_COUNTRY', None)
        return None, None
    enriched = []
    for _, row in df_rel.iterrows():
        pid = row['partner_factset_id']
        pname, pcountry = lookup_name(pid)
        # match to CDP and Trucost
        cdp_isin = None
        cdp_id_val = None
        cdp_org_name = None
        tr_companyid = None
        tr_gvkey = None
        tr_emis = {}
        # If sym has ISIN for partner, try by ISIN
        partner_row = sym[sym['FACTSET_ENTITY_ID']==pid]
        partner_isin = None
        for ic in isin_cols:
            if ic in partner_row.columns:
                partner_isin = partner_row.iloc[0].get(ic)
                break
        if cdp_summary is not None and partner_isin:
            match = cdp_summary[cdp_summary['isin'].fillna('').astype(str).str.upper() == str(partner_isin).upper()]
            if not match.empty:
                m = match.iloc[0]
                cdp_isin = m.get('isin')
                cdp_org_name = m.get(cdp_name_col)
                # attempt to capture a CDP id
                for cid in cdp_id_cols:
                    if cid in m.index and cid != cdp_name_col:
                        cdp_id_val = m.get(cid)
                        break
        # name-based CDP lookup
        if cdp_summary is not None and not cdp_isin:
            if pname:
                m = match_cdp_by_name(pname.strip().lower())
                if m is not None:
                    cdp_org_name = m.get(cdp_name_col)
                    cdp_isin = m.get('isin', None) if 'isin' in m.index else None
                    if not cdp_id_val:
                        for cid in cdp_id_cols:
                            if cid in m.index and cid != cdp_name_col:
                                cdp_id_val = m.get(cid)
                                break
        # Trucost by name
        if tr is not None and pname:
            mtr = match_trucost_by_name(pname.strip().lower())
            if mtr is not None:
                # extract some identifier cols if present
                for col in ('companyid','gvkey','company_id'):
                    if col in mtr.index:
                        if col == 'companyid':
                            tr_companyid = mtr.get(col)
                        elif col == 'gvkey':
                            tr_gvkey = mtr.get(col)
                # emission columns
                for ec in tr_emis_cols:
                    tr_emis[f'trucost_{ec}'] = mtr.get(ec)
        enriched.append({
            'target': target,
            'target_factset_id': row['target_factset_id'],
            'target_factset_name': row['target_factset_name'],
            'target_country': row['target_country'],
            'related_factset_id': row['partner_factset_id'],
            'related_factset_name': pname,
            'related_country': pcountry,
            'relation_type': row['rel_type'],
            'role': row['role'],
                    'relation_start_date': row.get('rel_start_date'),
                    'relation_end_date': row.get('rel_end_date'),
                    'relation_revenue_pct': row.get('rel_revenue_pct'),
                    'cdp_isin': cdp_isin,
                    'cdp_org_name': cdp_org_name,
                    'cdp_id': cdp_id_val,
                    'trucost_companyid': tr_companyid,
                    'trucost_gvkey': tr_gvkey,
                    **tr_emis
                })
    df_out = pd.DataFrame(enriched)
    # write per-target CSV
    out_path = OUT_DIR / f"{slug(target)}_supplychain.csv"
    df_out.to_csv(out_path, index=False)
    LOGGER.info('Wrote %d related partners for %s to %s', len(df_out), target, out_path)

print('Done')

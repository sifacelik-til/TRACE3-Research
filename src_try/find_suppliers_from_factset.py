"""
Find suppliers for a list of target companies using FactSet supply-chain relationships,
then match those suppliers to CDP and Trucost datasets by name/ISIN where possible.

Outputs:
 - data/processed/targets_suppliers_factset.csv

Usage:
  .venv\Scripts\python src\find_suppliers_from_factset.py

Notes:
 - Expects FactSet files under data/raw/FactSet as present in the repo (sym_entity.txt, ent_scr_relationships.txt)
 - Matches supplier names to CDP (CDP ISIN summary parquet if available) and Trucost CSV by exact name then fuzzy fallback.
"""
from pathlib import Path
import pandas as pd
import logging
from rapidfuzz import process, fuzz

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
LOGGER = logging.getLogger(__name__)

DATA_RAW = Path('data') / 'raw'
FACTSET_DIR = DATA_RAW / 'FactSet'
OUT = Path('data') / 'processed'
OUT.mkdir(parents=True, exist_ok=True)

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

# Paths to FactSet files
sym_entity = FACTSET_DIR / 'sym_entity_v1_full_12328' / 'sym_entity.txt'
relationships = FACTSET_DIR / 'ent_supply_chain_v1_full_3856' / 'ent_scr_relationships.txt'

if not sym_entity.exists() or not relationships.exists():
    LOGGER.error('Required FactSet files not found: %s or %s', sym_entity, relationships)
    raise SystemExit(1)

# Load sym_entity: FACTSET_ENTITY_ID|ENTITY_PROPER_NAME|ISO_COUNTRY|ENTITY_TYPE
LOGGER.info('Loading FactSet entity list from %s', sym_entity)
# read with encoding fallbacks (some FactSet files contain non-utf8 chars)
try:
    sym = pd.read_csv(sym_entity, sep='|', quotechar='"', dtype=str, encoding='utf-8')
except Exception:
    try:
        sym = pd.read_csv(sym_entity, sep='|', quotechar='"', dtype=str, encoding='latin-1')
    except Exception:
        # final fallback to cp1252
        sym = pd.read_csv(sym_entity, sep='|', quotechar='"', dtype=str, encoding='cp1252')

sym.columns = [c.strip('"') for c in sym.columns]
# clean columns
sym.columns = [c.strip().strip('"') for c in sym.columns]
# Rename expected columns
sym = sym.rename(columns={sym.columns[0]:'FACTSET_ENTITY_ID', sym.columns[1]:'ENTITY_PROPER_NAME'})
if len(sym.columns) >= 3:
    sym = sym.rename(columns={sym.columns[2]:'ISO_COUNTRY'})

sym['ENTITY_PROPER_NAME_norm'] = sym['ENTITY_PROPER_NAME'].fillna('').str.strip().str.lower()

# Load relationships (pipe-delimited with quotes)
LOGGER.info('Loading FactSet relationships from %s', relationships)
rel = pd.read_csv(relationships, sep='|', quotechar='"', dtype=str)
rel.columns = [c.strip('"') for c in rel.columns]
rel.columns = [c.strip().strip('"') for c in rel.columns]
rel = rel.rename(columns={rel.columns[0]:'ID', rel.columns[1]:'REL_TYPE', rel.columns[2]:'SOURCE_FACTSET_ENTITY_ID', rel.columns[3]:'TARGET_FACTSET_ENTITY_ID'})

# Prepare CDP summary (prefer ISIN summary parquet)
cdp_summary = None
cdp_parquet_candidates = list(DATA_RAW.rglob('*full_extract_cm_eds_c_isin*_summary*.parquet'))
if cdp_parquet_candidates:
    cdp_parquet = cdp_parquet_candidates[0]
    LOGGER.info('Loading CDP summary parquet: %s', cdp_parquet)
    cdp_summary = pd.read_parquet(cdp_parquet)
    # normalize name
    for col in ('disclosing_organization','disclosing_organization_name','disclosing_organization_full'):
        if col in cdp_summary.columns:
            cdp_name_col = col
            break
    else:
        cdp_name_col = 'disclosing_organization' if 'disclosing_organization' in cdp_summary.columns else cdp_summary.columns[0]
    cdp_summary['cdp_name_norm'] = cdp_summary[cdp_name_col].fillna('').astype(str).str.strip().str.lower()
else:
    LOGGER.info('No CDP ISIN summary parquet found; CDP matching will be skipped')

# Load Trucost CSV
trucost_candidates = list(DATA_RAW.rglob('*trucost*.csv'))
if trucost_candidates:
    trucost_path = trucost_candidates[0]
    LOGGER.info('Loading Trucost: %s', trucost_path)
    tr = pd.read_csv(trucost_path, dtype=str)
    tr['companyname_norm'] = tr.get('companyname','').fillna('').astype(str).str.strip().str.lower()
else:
    LOGGER.info('No Trucost CSV found; Trucost matching will be skipped')
    tr = None

# Result rows
rows = []

# Helper to fuzzy match supplier name to CDP and Trucost
def match_in_cdp(name):
    if cdp_summary is None or not name:
        return None, None
    # exact
    exact = cdp_summary[cdp_summary['cdp_name_norm'] == name]
    if not exact.empty:
        r = exact.iloc[0]
        return r.get('isin', None), r.get(cdp_name_col, None)
    # fuzzy
    cand = process.extractOne(name, cdp_summary['cdp_name_norm'].unique().tolist(), scorer=fuzz.token_sort_ratio)
    if cand and cand[1] >= 85:
        matched = cdp_summary[cdp_summary['cdp_name_norm'] == cand[0]].iloc[0]
        return matched.get('isin', None), matched.get(cdp_name_col, None)
    return None, None

def match_in_trucost(name):
    # always return a tuple (companyid, gvkey) or (None, None) to allow unpacking
    if tr is None or not name:
        return None, None
    exact = tr[tr['companyname_norm'] == name]
    if not exact.empty:
        r = exact.iloc[0]
        return r.get('companyid', None), r.get('gvkey', None)
    # fuzzy
    cand = process.extractOne(name, tr['companyname_norm'].unique().tolist(), scorer=fuzz.token_sort_ratio)
    if cand and cand[1] >= 85:
        matched = tr[tr['companyname_norm'] == cand[0]].iloc[0]
        return matched.get('companyid', None), matched.get('gvkey', None)
    return None, None

# For each target, find FactSet entity IDs by name (exact or fuzzy)
entity_names = sym['ENTITY_PROPER_NAME_norm'].tolist()
for target in targets:
    t_norm = target.strip().lower()
    # try exact contains
    matches = sym[sym['ENTITY_PROPER_NAME_norm'].str.contains(t_norm, na=False)]
    if matches.empty:
        # fuzzy
        best = process.extractOne(t_norm, entity_names, scorer=fuzz.token_sort_ratio)
        if best and best[1] >= 80:
            matched_name = best[0]
            matches = sym[sym['ENTITY_PROPER_NAME_norm'] == matched_name]
    if matches.empty:
        LOGGER.warning('No FactSet entity found for target: %s', target)
        continue
    # For each matched entity (could be multiple), find suppliers where TARGET_FACTSET_ENTITY_ID == entity id
    for _, ent in matches.iterrows():
        ent_id = ent['FACTSET_ENTITY_ID']
        ent_name = ent['ENTITY_PROPER_NAME']
        ent_country = ent.get('ISO_COUNTRY', None)
        # find relationships where REL_TYPE == 'SUPPLIER' and TARGET_FACTSET_ENTITY_ID equals ent_id
        suppliers = rel[(rel['REL_TYPE']=='"SUPPLIER"') & (rel['TARGET_FACTSET_ENTITY_ID']==f'"{ent_id}"')]
        # note: file values include quotes; sym has unquoted IDs; need to strip quotes in rel
        if suppliers.empty:
            # try without quotes
            suppliers = rel[(rel['REL_TYPE']=='SUPPLIER') & (rel['TARGET_FACTSET_ENTITY_ID']==ent_id)]
        if suppliers.empty:
            # fallback: look where TARGET contains ent_id
            suppliers = rel[rel['TARGET_FACTSET_ENTITY_ID'].str.contains(ent_id.replace('-',''), na=False)]
        # collect supplier IDs from SOURCE_FACTSET_ENTITY_ID (strip quotes)
        supplier_ids = suppliers['SOURCE_FACTSET_ENTITY_ID'].fillna('').astype(str).str.strip().str.strip('"').unique().tolist()
        for sid in supplier_ids:
            if not sid:
                continue
            # lookup supplier name in sym
            srow = sym[sym['FACTSET_ENTITY_ID']==sid]
            supplier_name = srow['ENTITY_PROPER_NAME'].iloc[0] if not srow.empty else None
            sup_country = srow['ISO_COUNTRY'].iloc[0] if not srow.empty and 'ISO_COUNTRY' in srow.columns else None
            # match to CDP and Trucost
            isin_cdp, cdp_org = match_in_cdp((supplier_name or '').strip().lower())
            tr_companyid, tr_gvkey = match_in_trucost((supplier_name or '').strip().lower())
            rows.append({
                'target': target,
                'target_factset_id': ent_id,
                'target_factset_name': ent_name,
                'target_country': ent_country,
                'supplier_factset_id': sid,
                'supplier_factset_name': supplier_name,
                'supplier_country': sup_country,
                'cdp_isin': isin_cdp,
                'cdp_org': cdp_org,
                'trucost_companyid': tr_companyid,
                'trucost_gvkey': tr_gvkey
            })

# write output
out = OUT / 'targets_suppliers_factset.csv'
df_out = pd.DataFrame(rows)
df_out.to_csv(out, index=False)
LOGGER.info('Wrote suppliers dataset to %s (rows=%d)', out, len(df_out))
print('Done')

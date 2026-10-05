import re
from pathlib import Path

import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils.dataframe import dataframe_to_rows
from rapidfuzz import fuzz, process

root = Path(r'C:\Users\scelik\Desktop\TRACE3Code')
node_path = root / 'data' / 'outputs' / 'dataset_readers' / 'requested_supplychain_networks' / '6501_Hitachi_Ltd.' / 'nodes.csv'
tr_path = next((root / 'data' / 'raw').rglob('*trucost*.csv'))
source_wb = root / 'data' / 'outputs' / 'dataset_readers' / 'requested_supplychain_networks' / '6501_Hitachi_Ltd_company_profile.xlsx'
new_wb = root / 'data' / 'outputs' / 'dataset_readers' / 'requested_supplychain_networks' / '6501_Hitachi_Ltd_company_profile_with_network_cdp.xlsx'
out_csv = root / 'data' / 'outputs' / 'dataset_readers' / 'requested_supplychain_networks' / 'hitachi_network_top100_emissions_and_cdp_categories.csv'

section_labels = {
    'C1': 'C1 Governance',
    'C2': 'C2 Risks and Opportunities',
    'C3': 'C3 Business Strategy',
    'C4': 'C4 Targets and Performance',
    'C5': 'C5 Climate Risk and Data',
    'C6': 'C6 Energy',
    'C7': 'C7 GHG Inventory',
    'C8': 'C8 Emissions Reduction',
    'C9': 'C9 Value Chain and Supplier Engagement',
    'C10': 'C10 Products and Services',
    'C11': 'C11 Pricing',
    'C12': 'C12 Engagement',
}
section_text = '; '.join(section_labels.values())

nodes = pd.read_csv(node_path, low_memory=False)
nodes = nodes[nodes['entity_proper_name'].notna()].copy()
nodes['entity_proper_name'] = nodes['entity_proper_name'].astype(str)
nodes = nodes[nodes['entity_proper_name'] != 'Hitachi Ltd.']
nodes['max_coverage'] = nodes[['coverage_upstream_pct', 'coverage_downstream_pct']].max(axis=1, skipna=True)
nodes = nodes.sort_values('max_coverage', ascending=False).drop_duplicates(subset=['entity_proper_name']).head(100).copy()

tr = pd.read_csv(tr_path, low_memory=False)
tr['companyname_norm'] = tr['companyname'].fillna('').astype(str).str.lower().str.replace(r'[^a-z0-9]+', ' ', regex=True).str.strip()
tr_names = tr['companyname_norm'].drop_duplicates().tolist()

def norm(s):
    return re.sub(r'[^a-z0-9]+', ' ', (s or '').lower()).strip()

def match_trucost_company(name):
    n = norm(name)
    exact = tr[tr['companyname_norm'] == n]
    if not exact.empty:
        return exact.iloc[0]
    cand = process.extractOne(n, tr_names, scorer=fuzz.token_sort_ratio, score_cutoff=78)
    if cand:
        return tr[tr['companyname_norm'] == cand[0]].iloc[0]
    return None

def pct_reduction(first, last):
    if pd.isna(first) or pd.isna(last) or first == 0:
        return None
    return (first - last) / first * 100.0

rows = []
for _, r in nodes.iterrows():
    name = str(r['entity_proper_name']).strip()
    match = match_trucost_company(name)
    s1 = s2 = s3 = None
    start_year = end_year = None
    if match is not None:
        emissions = tr[tr['companyname'] == match['companyname']].copy()
        if emissions.empty:
            emissions = tr[tr['companyname_norm'] == match['companyname_norm']].copy()
        emissions = emissions[['companyname', 'ticker', 'fiscalyear', 'di_319413', 'di_319414', 'di_319415']].dropna(subset=['fiscalyear']).copy()
        emissions['fiscalyear'] = pd.to_numeric(emissions['fiscalyear'], errors='coerce')
        emissions['di_319413'] = pd.to_numeric(emissions['di_319413'], errors='coerce')
        emissions['di_319414'] = pd.to_numeric(emissions['di_319414'], errors='coerce')
        emissions['di_319415'] = pd.to_numeric(emissions['di_319415'], errors='coerce')
        emissions = emissions.sort_values('fiscalyear').drop_duplicates()
        if not emissions.empty:
            first = emissions.iloc[0]
            last = emissions.iloc[-1]
            s1 = pct_reduction(first['di_319413'], last['di_319413'])
            s2 = pct_reduction(first['di_319414'], last['di_319414'])
            s3 = pct_reduction(first['di_319415'], last['di_319415'])
            start_year = int(first['fiscalyear'])
            end_year = int(last['fiscalyear'])
    rows.append({
        'entity_proper_name': name,
        'max_coverage_pct': float(r['max_coverage']) if pd.notna(r['max_coverage']) else None,
        'scope1_pct_reduction': s1,
        'scope2_pct_reduction': s2,
        'scope3_pct_reduction': s3,
        'start_year': start_year,
        'end_year': end_year,
        'trucost_match': 'Yes' if match is not None else 'No',
        'CDP_2021_2024_questionnaire_sections': section_text,
        'CDP_note': 'No direct company-level CDP response found in the raw archive for this network node; section taxonomy reflects the standard CDP climate questionnaire categories used in recent years.',
    })

summary = pd.DataFrame(rows).sort_values('max_coverage_pct', ascending=False).reset_index(drop=True)
summary.to_csv(out_csv, index=False)

if source_wb.exists():
    wb = load_workbook(source_wb)
else:
    wb = Workbook()

if 'Network_Emissions_CDP' in wb.sheetnames:
    del wb['Network_Emissions_CDP']
ws = wb.create_sheet('Network_Emissions_CDP')
for row in dataframe_to_rows(summary, index=False, header=True):
    ws.append(row)
for cell in ws[1]:
    cell.font = Font(bold=True)
    cell.fill = PatternFill('solid', fgColor='D9EAF7')
for row in ws.iter_rows():
    for cell in row:
        cell.alignment = Alignment(vertical='top', wrap_text=True)
ws.freeze_panes = 'A2'
for col, width in {'A': 34, 'B': 18, 'C': 18, 'D': 18, 'E': 18, 'F': 12, 'G': 12, 'H': 12, 'I': 100, 'J': 110}.items():
    ws.column_dimensions[col].width = width
wb.save(new_wb)
print(f'CSV: {out_csv}')
print(f'Workbook: {new_wb}')

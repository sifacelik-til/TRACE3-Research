"""Extract risk/opportunity source rows without rebuilding other sections."""
from . import extract_cdp_section_records as base

RISK_STAGE=base.STAGE/'risk_opportunities'

def risk_section(code):
    c=code.upper().removeprefix('Q')
    if c.startswith(('CC2.1','CC5.1','CC6.1','C2.','2.1','2.2.1','2.2.2','3.1','3.6','15.1','16.1','16.3')):
        return 'risks_opportunities'

def main():
    base.STAGE=RISK_STAGE
    base.section=risk_section
    base.STAGE.mkdir(parents=True,exist_ok=True)
    sample=base.base_sample()
    for year in range(2016,2026):
        if (base.STAGE/f'{year}.jsonl.gz').exists():continue
        accounts={base.key(r['cdp_account_number']) for r in sample if int(r['year'])==year}
        if year<2024:base.legacy(year,accounts)
        else:base.recent(year,accounts,prefixes=['2.1','2.2.1','2.2.2','3.1','3.6','15.1','16.1','16.3'])

if __name__=='__main__':main()

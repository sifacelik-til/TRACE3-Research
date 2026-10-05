"""Write annual review templates and source mappings for curated CDP datasets."""
import csv
import json
import re
from collections import defaultdict,Counter
from functools import lru_cache
from pathlib import Path
from src.cdp_extraction.build_cdp_section_datasets import ROOT,OUT,FIELDS,META,record_type,label

REPORT=ROOT/'reports/cdp_extraction/cdp_section_extraction_templates'
CACHE=ROOT/'tmp/pdfs/section_templates'

def save(path,fields,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)

@lru_cache(None)
def document(year,code):
    if year<2024:stem=f'{year} Climate Change Questionnaire'
    elif code.startswith(('Q15.','Q16.','Q18.','Q20.')):
        stem='2024 - Corporate Questionnaire - SME Modules 14 to 21' if year==2024 else '2025_SME_Questionnaire_Modules_14-21'
    elif code.startswith('Q7.'):
        stem='2024 - Corporate Questionnaire - Modules 7' if year==2024 else '2025_Full_Corporate_Questionnaire_Module_7'
    else:stem='2024 - Corporate Questionnaire - Modules 1 to 6' if year==2024 else '2025_Full_Corporate_Questionnaire_Modules_1-6'
    return stem,(CACHE/(stem+'.txt')).read_text(encoding='utf-8')

def question(year,code,headers):
    stem,text=document(year,code)
    raw=code.removeprefix('Q')
    pat=(r'(?m)^[ \t]*(?:If (?:yes|no):[ \t]*)?'+re.escape(raw)+r'\s+' if year<2018 else r'\('+re.escape(raw)+r'\)')
    matches=list(re.finditer(pat,text))
    if year>=2024:
        matches=[m for m in matches if 'Question details' in text[m.end():m.end()+1000]]
    elif year>=2018:
        matches=[m for m in matches if m.start()==0 or text[m.start()-1]=='\n']
    page='';prompt='';dependency=''
    if matches:
        m=matches[-1] if year>=2024 else matches[0]
        pages=re.findall(r'===== PDF PAGE (\d+)',text[:m.start()]);page=pages[-1] if pages else ''
        tail=text[m.end():m.end()+3500]
        if year>=2018:
            prompt=re.split(r'Question details|Question dependencies|Change from|Change From|Response options',tail)[0]
            dep=re.search(r'Question dependencies\s*(.*?)(?:Change [fF]rom|Question details|Response options|Rationale|Requested content)',tail,re.S)
            if dep:dependency=re.sub(r'\s+',' ',dep[1]).strip()
        else:
            # Workbook headers contain the exact prompt without response table text.
            for h in headers:
                clean=re.sub(r'^'+re.escape(code)+r'(?:[ _]+C\d+)?[ _-]*','',h,flags=re.I)
                if ' - ' in clean:clean=clean.split(' - ',1)[0]
                if len(clean)>len(prompt):prompt=clean
    if not prompt and year<2024:
        for h in headers:
            clean=re.sub(r'^'+re.escape(code)+r'(?:[ _]+C\d+)?[ _-]*','',h,flags=re.I).split(' - ',1)[0]
            if len(clean)>len(prompt):prompt=clean
    prompt=re.sub(r'\s+',' ',prompt).strip()
    if '===== PDF PAGE' in prompt:prompt=prompt.split('===== PDF PAGE')[0].strip()
    return dict(question=prompt,source_pdf=str(ROOT/'data/raw/CDP/CDP Questionnaires'/(stem+'.pdf')),pdf_page=page,
                dependency=dependency or 'Conditional availability varies by response and questionnaire pathway. Missing answers do not mean No.',
                source_check='Question located in PDF' if page else 'Use source answer header; PDF question heading not matched')

def main():
    csv.field_size_limit(100_000_000)
    with (OUT/'field_selection_audit.csv').open(encoding='utf-8',newline='') as f:audit=list(csv.DictReader(f))
    stats=json.loads((OUT/'validation.json').read_text())
    summary=[]
    for section,all_fields in FIELDS.items():
        root=REPORT/section
        retained=[r for r in audit if r['section']==section and r['decision']=='retained']
        questions=defaultdict(list)
        for r in retained:questions[int(r['year']),r['question_code']].append(r['source_header'])
        infos={(y,c):question(y,c,hs) for (y,c),hs in questions.items()}
        mapping=[];question_rows=[]
        for (y,c),info in sorted(infos.items()):
            question_rows.append(dict(year=y,question_code=c,record_type=record_type(c,y),pathway='SME' if c.startswith(('Q18.','Q20.')) else 'Full',**info))
        for r in retained:
            y=int(r['year']);c=r['question_code'];info=infos[y,c]
            mapping.append(dict(year=y,question_code=c,record_type=record_type(c,y),short_name=r['short_name'],source_field=label(r['source_header']),source_header=r['source_header'],source_pdf=info['source_pdf'],pdf_page=info['pdf_page']))
        save(root/'field_mapping_2016_2025.csv',list(mapping[0]),mapping)
        save(root/'questions_2016_2025.csv',list(question_rows[0]),question_rows)
        grouped=defaultdict(list)
        for r in mapping:grouped[r['short_name']].append(r)
        dictionary=[]
        for f in all_fields:
            rows=grouped[f]
            dictionary.append(dict(short_name=f,source_meanings=' | '.join(sorted({r['source_field'] for r in rows})),years=';'.join(map(str,sorted({r['year'] for r in rows}))),record_types=';'.join(sorted({r['record_type'] for r in rows})),storage='Original answer text; JSON array of answers for multi-select',units='metric tons CO2e' if 'tco2e' in f else 'Percent as reported (not converted to fraction)' if f.endswith('_pct') else 'Reporting currency' if f.endswith('_money') or f=='carbon_tax_paid' else 'Reporting currency per metric ton CO2e' if f in {'internal_price_min','internal_price_max','internal_price_raw'} else 'See source field'))
        for entry in dictionary:
            if entry['short_name']=='climate_relevance':
                entry.update(source_meanings='Derived from questionnaire year, environmental issue answer and source row label',years='2016;2017;2018;2019;2020;2021;2022;2023;2024;2025',record_types='All engagement records',storage='Derived metadata classification',units='Category')
        save(root/'field_dictionary.csv',list(dictionary[0]),dictionary)
        with (OUT/f'cdp_{section}_2016_2025.csv').open(encoding='utf-8',newline='') as stream:
            counts=Counter();filled=Counter();year_fields=defaultdict(set)
            for row in csv.DictReader(stream):
                y=int(row['year']);kind=row['record_type'];counts[y,kind]+=1
                for f in all_fields:
                    if row[f] and row[f].strip().lower() not in {'question not applicable','not applicable','n/a','nan','none','null'}:
                        filled[y,kind,f]+=1;year_fields[y].add(f)
        for y in range(2016,2026):
            cols=META+[f for f in all_fields if f in year_fields[y]]
            save(root/f'{y}_template.csv',cols,[])
        cov=[dict(year=y,record_type=k,short_name=f,records=n,answered_records=filled[y,k,f],missing_pct=round(100*(1-filled[y,k,f]/n),2)) for (y,k),n in sorted(counts.items()) for f in all_fields if any(r['record_type']==k and r['year']==y for r in grouped[f])]
        save(root/'field_coverage.csv',['year','record_type','short_name','records','answered_records','missing_pct'],cov)
        summary.append((section,stats['rows'][section],len(all_fields)))
    lines=['# CDP section datasets, 2016–2025','',
        'Four populated CSV datasets use the same matched company sample as the existing CDP–Trucost–FactSet–LSEG panel. Each section has its own annual blank templates, field dictionary, question inventory and exact source-header mapping.','',
        '| Section | Records | Answer and derived fields |','|---|---:|---:|']
    lines += [f'| [{s.replace("_"," ").title()}]({s}/field_mapping_2016_2025.csv) | {n:,} | {f} |' for s,n,f in summary]
    lines += ['', '## Reading the data','',
        '- One row is one source question row for a CDP account and disclosure year. A company can have several targets, initiatives, verification statements or schemes. Filter `record_type` before calculating totals.',
        '- Join on `year` and `cdp_account_number`. `company_year_links.csv` links accounts to the existing FactSet/Trucost/LSEG panel. Account-level data are not duplicated when an account links to multiple panel companies.',
        '- Company name, primary sector and primary industry come from the existing matched panel. Currency comes from the annual CDP response and is not converted.',
        '- Answer cells contain only source answers. Multi-select answers are stored as JSON lists of answer values. Original question headers and source files are stored separately in the mappings and `answer_provenance.jsonl.gz`.',
        '- Blank means unavailable in that source row. It does not mean zero or No. Useful conditional fields are retained, including fields exceeding 65% missingness, following the requested preference. Field coverage is reported within year and record type.',
        '- Rows containing only CDP inapplicability placeholders are excluded. Individual source answers such as Not applicable are preserved when part of a substantive record.',
        '- `year` is the CDP disclosure year, not necessarily the financial/emissions reporting period. Read target date/year fields as supplied; no date or currency conversions were made.','',
        '## Targets and performance','',
        'Includes active-target flags, absolute/intensity/energy/other/net-zero targets, coverage, base and target years/dates, science-based status, emissions or intensity levels, target progress and selected implementation plans. Detailed scope-category emissions columns are omitted in favor of reported totals and Scope 3 totals; totals are not reconstructed from components.',
        'Emissions-reduction initiatives receive separate `initiative_status`, `initiative_stage`, `initiative`, `investment_method` and `no_initiative` records. Initiative rows retain category/type, scopes, estimated annual CO2e savings, annual monetary savings, investment, payback, lifetime and explanatory comments. Recent questionnaires sometimes supply category and type as one combined answer, preserved in `initiative_type`.',
        '**Savings are estimates.** Do not sum initiative-stage totals together with individual initiative savings. Stages are retained in `row_label` or `initiative_stage`. Neither target progress nor estimated savings establishes a realized company-wide emissions reduction.','',
        '## Verification','',
        'Includes assurance status, cycle, reporting-year status, assurance level, verification standard, verified percentage, emissions scope and Scope 3 category. C10.1a covers Scope 1 and 2 jointly in 2018–2019; explicit source scope is preserved. Later questionnaires split these scopes. Verification attachments and page references are excluded.','',
        '## Carbon pricing','',
        'Includes regulatory coverage, ETS allowances and verified emissions, carbon tax coverage/payment, internal pricing objectives/type/scopes/application/prices, and carbon-credit activity and volumes. The 2016–2017 regulatory flag refers to ETS participation, while later flags also encompass carbon taxes; consult `question_code` and the question inventory.',
        'Credit purchases/origination and canceled/retired credits are different measures and remain in separate fields. `credit_activity_raw` retains the original answer to the year-specific question. From 2024, `internal_pricing_raw` asks about environmental externalities generally; inspect `externalities_priced` or carbon-specific detail records before interpreting it as carbon pricing.','',
        '## Engagement','',
        'Focuses on value-chain engagement, supplier/customer coverage and Scope 3 coverage, supplier requirements, compliance monitoring, non-compliance response and effects. Policy lobbying, trade-association memberships, public communications and attachments are excluded.',
        'From 2024, CDP combines environmental topics. Explicitly non-climate records are excluded; cross-environment records without an explicit issue remain marked `environmental_unspecified`. `climate_relevance` distinguishes these from explicit climate answers. SME questions supply less detail; absent SME carbon-pricing records do not mean No.',
        'A source quirk in 2016–2017 labels some no-engagement explanations CC14.4c although the questionnaire uses CC14.4d. The data preserve the supplied question code and map the answer by its full header.','',
        '## Validation and sources','',
        f'All {sum(stats["verified_source_answers"].values()):,} retained source answer values were checked against separate source provenance after CSV serialization. Record identifiers are unique, and every account-year belongs to the matched sample.',
        'Sources are the local annual CDP Excel exports (2016–2023), response parquet exports (2024–2025), and annual questionnaire PDFs. Question mappings include the original headers and PDF page references where a matching heading was found. A missing PDF heading is explicitly marked for review.',
        'The populated CSV files are in `data/processed/cdp_section_datasets`. This folder also contains coverage, exclusions, source-field audit and validation files.']
    REPORT.mkdir(parents=True,exist_ok=True)
    (REPORT/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    data_readme='\n'.join(lines)+'\n'
    for s in FIELDS:data_readme=data_readme.replace(f']({s}/',f'](../../../reports/cdp_extraction/cdp_section_extraction_templates/{s}/')
    (OUT/'README.md').write_text(data_readme,encoding='utf-8')
    print(json.dumps(summary))
    if (OUT/'cdp_risks_opportunities_2016_2025.csv').exists():
        from src.cdp_extraction.build_cdp_risk_opportunity_templates import main as add_risk_templates
        add_risk_templates()

if __name__=='__main__':main()

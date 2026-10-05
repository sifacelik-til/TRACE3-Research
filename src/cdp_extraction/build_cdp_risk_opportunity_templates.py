"""Annual templates and guide for the populated risk/opportunity section."""
import csv,json,re
from collections import Counter,defaultdict
from src.cdp_extraction.build_cdp_risk_opportunity import OUT,SUPPORT,FIELDS,record_type
from src.cdp_extraction.build_cdp_section_datasets import ROOT,META,label
from src.cdp_extraction.build_cdp_section_templates import REPORT,save,question,document

def main():
    csv.field_size_limit(100_000_000)
    target=REPORT/'risks_opportunities'
    audit=list(csv.DictReader((SUPPORT/'field_selection_audit.csv').open(encoding='utf-8')))
    retained=[r for r in audit if r['decision']=='retained']
    groups=defaultdict(list)
    for r in retained:groups[int(r['year']),r['question_code']].append(r['source_header'])
    info={}
    for (y,c),hs in groups.items():
        details=question(y,c,hs)
        # Legacy exports label risk/opportunity branch columns with subcodes,
        # while the PDF prints the prose under the parent question's table.
        if not details['pdf_page'] and y<2018:
            stem,text=document(y,c)
            words=details['question'].split()[:12]
            pattern=r'\s+'.join(re.escape(w) for w in words)
            match=re.search(pattern,text,re.I)
            if match:
                details['pdf_page']=re.findall(r'===== PDF PAGE (\d+)',text[:match.start()])[-1]
                details['source_check']='Branch wording located in PDF; subcode is from response export'
            elif c.startswith(('CC5.1','CC6.1')):
                parent=question(y,c[:5],[])
                details['pdf_page']=parent['pdf_page']
                details['source_check']='Parent question PDF page; branch subcode and wording verified against response export'
        info[y,c]=details
    questions=[dict(year=y,question_code=c,record_type=record_type(c,y),pathway='SME' if c.startswith(('Q15.','Q16.')) else 'Full',**v) for (y,c),v in sorted(info.items())]
    save(target/'questions_2016_2025.csv',list(questions[0]),questions)
    mapping=[dict(year=r['year'],question_code=r['question_code'],record_type=record_type(r['question_code'],int(r['year'])),short_name=r['short_name'],source_field=label(r['source_header']),source_header=r['source_header'],source_pdf=info[int(r['year']),r['question_code']]['source_pdf'],pdf_page=info[int(r['year']),r['question_code']]['pdf_page']) for r in retained]
    save(target/'field_mapping_2016_2025.csv',list(mapping[0]),mapping)
    byfield=defaultdict(list)
    for r in mapping:byfield[r['short_name']].append(r)
    dictionary=[]
    derived={'climate_relevance':'Environmental issue classification from question year, issue answer and row label','questionnaire_pathway':'Full or SME based on source question family','legacy_category':'Regulation, physical climate or other climate developments, from the source question branch'}
    money={'potential_fin_effect','potential_fin_min','potential_fin_max','current_fin_effect','future_st_min','future_st_max','future_mt_min','future_mt_max','future_lt_min','future_lt_max','response_cost'}
    for f in FIELDS:
        rs=byfield[f]
        dictionary.append(dict(short_name=f,meaning=derived.get(f,' | '.join(sorted({r['source_field'] for r in rs}))),years=';'.join(sorted({r['year'] for r in rs})),record_types=';'.join(sorted({r['record_type'] for r in rs})),units='Company reporting currency; no currency conversion' if f in money else 'Percent as reported' if f.endswith('_pct') else 'Years' if f.endswith('_years') else 'Source answer text/categories',storage='Derived metadata' if f in derived else 'Original answer; JSON list of values for multi-select'))
    save(target/'field_dictionary.csv',list(dictionary[0]),dictionary)
    counts=Counter();filled=Counter();annual_fields=defaultdict(set);sector=Counter();env=Counter()
    with (OUT/'cdp_risks_opportunities_2016_2025.csv').open(encoding='utf-8',newline='') as stream:
        reader=csv.DictReader(stream)
        for row in reader:
            y=int(row['year']);k=row['record_type'];counts[y,k]+=1;env[row['climate_relevance']]+=1
            sector['primary_sector']+=bool(row['primary_sector']);sector['primary_industry']+=bool(row['primary_industry'])
            for f in FIELDS:
                if row[f] and row[f].lower() not in {'question not applicable','not applicable','n/a','nan'}:filled[y,k,f]+=1;annual_fields[y].add(f)
    for y in range(2016,2026):save(target/f'{y}_template.csv',META+[f for f in FIELDS if f in annual_fields[y]],[])
    validfields=defaultdict(set)
    for r in mapping:validfields[int(r['year']),r['record_type']].add(r['short_name'])
    coverage=[dict(year=y,record_type=k,short_name=f,records=n,answered_records=filled[y,k,f],missing_pct=round(100*(1-filled[y,k,f]/n),2)) for (y,k),n in sorted(counts.items()) for f in sorted(validfields[y,k])]
    save(target/'field_coverage.csv',list(coverage[0]),coverage)
    stats=json.loads((SUPPORT/'validation.json').read_text())
    assert sum(counts.values())==stats['rows']['risks_opportunities']
    assert all(q['question'] for q in questions)
    assert {int(q['year']) for q in questions}==set(range(2016,2026))
    typed=Counter()
    for (y,k),n in counts.items():typed[k]+=n
    lines=['# CDP risks and opportunities, 2016–2025','',
        f'Populated dataset: {stats["rows"]["risks_opportunities"]:,} records. It uses the same matched-company sample as the other four sections. All {stats["verified_source_answers"]["risks_opportunities"]:,} retained source values were verified after writing the CSV.','',
        f'[Open the populated CSV](<{(OUT/"cdp_risks_opportunities_2016_2025.csv").as_posix()}>)','',
        '[Question inventory](questions_2016_2025.csv) · [Exact field mappings](field_mapping_2016_2025.csv) · [Field dictionary](field_dictionary.csv) · [Field coverage](field_coverage.csv)','',
        '## Included records','',
        '| Record type | Rows |','|---|---:|']
    lines += [f'| `{k}` | {n:,} |' for k,n in sorted(typed.items())]
    lines += ['', 'Includes process existence, assessment stages/frequency/horizons, assessed risk types, substantive-impact definitions, individual risks and opportunities, financial effects, response strategies and costs, and reasons for no process, risks or opportunities.','',
        'The 2020 source scope includes the C2 overview, C2.1a, C2.2, C2.3a and C2.4a sheets requested earlier, plus C2.2a, C2.2g, C2.3b and C2.4b for risk-type assessments and negative branches.','',
        '## Interpreting the fields','',
        '- One row represents one source question row, keyed by disclosure year, CDP account and record ID. A company can have many risk/opportunity rows. Filter `record_type` before analysis. `item_id` identifies the disclosed risk/opportunity when the source supplies an identifier.',
        '- Shared names such as `driver`, `description`, `time_horizon` and financial-effect fields refer to the risk or opportunity identified by `record_type`. They do not combine different risks or opportunities into a single answer.',
        '- `is_risk_op_assessed` retains the source process-existence answer. It is categorical, not a normalized Boolean or evidence that an assessment was completed. In 2016–2019 it can describe integrated/dedicated/no documented processes; in recent years it can include Yes/No and future plans.',
        '- In 2024–2025, `process_scope` distinguishes Risks only, Opportunities only and Both. Use `process_covers` and `env_issue` on assessment rows to establish climate-risk versus climate-opportunity coverage. A general environmental process does not prove climate-specific assessment.',
        '- `assess_stages` is the coverage of the assessment process. `value_chain_stage` is the location of an individual risk/opportunity. For horizon records, the source `row_label` identifies Short-, Medium- or Long-term. For risk-type assessments, it identifies the assessed risk category.',
        '- For 2020–2023 risk details, the grouped `_G` source field is `risk_type`; its companion is `driver`. Recent exports combine type and driver in a single grouped answer, which remains together in `driver`.',
        '- `potential_fin_effect`/`potential_fin_min`/`potential_fin_max` are potential impacts. `current_fin_effect` is a reporting-year effect. `future_st_*`, `future_mt_*` and `future_lt_*` hold anticipated short-, medium- and long-term amounts. Do not add these different measures together.',
        '- Legacy financial implications and management costs can be narrative text and remain in `financial_effect_text` and `response_cost_text`. All monetary values retain the company reporting currency. No inflation adjustments, currency conversions or interpretation of narrative amounts were applied.',
        '- Explicit Yes variants, including opportunities identified but not currently realizable, are preserved. Blank does not mean No or zero. Useful conditional fields are retained without the earlier 65% missingness cutoff.',
        '- Answer cells contain only answers. Multi-select answers use JSON lists. Source headers/files are stored in the mapping and separate provenance file. Sector and industry are included where available in the matched panel.','',
        '## Year-specific sources','',
        '| Years | Process/assessment | Risks | Opportunities |','|---|---|---|---|',
        '| 2016–2017 | CC2.1 and branches | CC5.1 and branches | CC6.1 and branches |',
        '| 2018–2019 | C2.2 and branches; C2.1 horizons | C2.3/a/b | C2.4/a/b |',
        '| 2020–2023 | C2.1/a/b; C2.2/a/g | C2.3/a/b | C2.4/a/b |',
        '| 2024–2025 Full | 2.1; 2.2.1; 2.2.2 | 3.1; 3.1.1 | 3.6; 3.6.1 |',
        '| 2024–2025 SME | 15.1 | 16.1; 16.1.1 | 16.3; 16.3.1 |','',
        'Explicitly non-climate environmental records are excluded. Recent general process/horizon answers without an explicit issue remain marked `environmental_unspecified`. Climate-specific records are marked `explicit_climate`; older climate-questionnaire records use `climate_questionnaire`.',
        'The original 2016–2017 exports supply CC5.1d/e/f and CC6.1d/e/f for no-risk/no-opportunity explanations. These actual export codes are preserved even where the PDF prints the prose under the parent question instead of displaying a separate subcode.',
        'Additional financial-metric tables 3.1.2/3.6.2 and specialist portfolio-assessment families are outside the requested core scope. Commodity, river-basin and mining identifiers that are irrelevant to the climate records are excluded.',
        f'Validation, original-value provenance and exclusion logs are in `{SUPPORT.relative_to(ROOT).as_posix()}`.','',
        '## Annual blank templates','']
    lines += [f'- [{y} template]({y}_template.csv)' for y in range(2016,2026)]
    (target/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    # Add the fifth section to both existing guides without rewriting four datasets.
    for path in [REPORT/'README.md',OUT/'README.md']:
        text=path.read_text(encoding='utf-8').replace('Four populated CSV datasets','Five populated CSV datasets')
        text=text.replace('\n\n| Risks and Opportunities |','\n| Risks and Opportunities |')
        if '| Risks and Opportunities |' not in text:
            title=f'| Risks and Opportunities | {stats["rows"]["risks_opportunities"]:,} | {len(FIELDS)} |\n'
            text=text.replace('\n\n## Reading the data','\n'+title+'\n## Reading the data',1)
        other_stats=json.loads((OUT/'validation.json').read_text())
        total=sum(other_stats['verified_source_answers'].values())+stats['verified_source_answers']['risks_opportunities']
        text=re.sub(r'All [\d,]+ retained source answer values',f'All {total:,} retained source answer values',text)
        marker='## Risks and opportunities'
        if marker not in text:
            text+='\n'+marker+'\n\n'+f'[Populated dataset and annual templates](<{(target/"README.md").as_posix()}>) cover assessment processes, risk and opportunity details, financial effects, responses and negative branches. The accompanying validation and provenance files are in `risk_opportunity_support`.\n'
        path.write_text(text,encoding='utf-8')
    old=ROOT/'reports/cdp_extraction/cdp_risk_extraction_template/README.md'
    old_text=old.read_text(encoding='utf-8')
    if 'Populated risk and opportunity data are now available' not in old_text:
        old.write_text(f'**Populated risk and opportunity data are now available:** [dataset, updated mappings and annual templates](<{(target/"README.md").as_posix()}>). The review draft below is retained as historical context.\n\n'+old_text,encoding='utf-8')
    print(json.dumps(dict(rows=sum(counts.values()),types=dict(typed),questions=len(questions),pdf_heading_gaps=[(q['year'],q['question_code']) for q in questions if not q['pdf_page']],climate_relevance=dict(env),sector_coverage=dict(sector))))

if __name__=='__main__':main()

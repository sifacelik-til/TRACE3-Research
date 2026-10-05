"""Build review-only annual risk templates from inspected local questionnaires."""
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / 'tmp/pdfs/risk_template'
OUT = ROOT / 'reports/cdp_extraction/cdp_risk_extraction_template'
OUT.mkdir(parents=True, exist_ok=True)
AUDIT = json.loads((CACHE / 'source_sheets.json').read_text(encoding='utf-8'))
rows, questions = [], []


def source(year, pathway='full'):
    if year < 2024:
        name = f'{year} Climate Change Questionnaire'
    elif pathway == 'sme':
        name = ('2024 - Corporate Questionnaire - SME Modules 14 to 21' if year == 2024 else '2025_SME_Questionnaire_Modules_14-21')
    else:
        name = ('2024 - Corporate Questionnaire - Modules 1 to 6' if year == 2024 else '2025_Full_Corporate_Questionnaire_Modules_1-6')
    return ROOT / 'data/raw/CDP/CDP Questionnaires' / (name + '.pdf'), (CACHE / (name + '.txt')).read_text(encoding='utf-8')


def question_info(year, code, pathway):
    path, text = source(year, pathway)
    if year < 2018:
        base = 'CC5.1' if code.startswith('CC5.1') else code
        m = list(re.finditer(r'(?m)^' + re.escape(base) + r'\s+', text))[0]
        tail = text[m.end():]
        end = re.search(r'\n(?:If |Frequency of|Main reason|CC\d|Please identify|For all)', tail)
        prompt = re.sub(r'\s+', ' ', tail[:end.start()] if end else tail[:200]).strip()
        if code in ('CC5.1a', 'CC5.1b', 'CC5.1c'):
            category = {'CC5.1a': 'changes in regulation', 'CC5.1b': 'changes in physical climate parameters', 'CC5.1c': 'changes in other climate-related developments'}[code]
            prompt = f'Please describe your inherent risks that are driven by {category}.'
        if code == 'CC5.1_no_risk':
            prompt = 'Please explain why you do not consider your organization to be exposed to these risks that have the potential to generate a substantive change in your business operations, revenue or expenditure.'
    else:
        matches = list(re.finditer(r'\(' + re.escape(code) + r'\)', text))
        matches = [m for m in matches if ('Question details' in text[m.end():m.end()+800] if year >= 2024 else m.start() == 0 or text[m.start()-1] == '\n')]
        m = matches[-1] if year >= 2024 else matches[0]
        tail = text[m.end():]
        stop = re.search(r'Question details|Question dependencies|Change from|Change From', tail)
        prompt = re.sub(r'\s+', ' ', tail[:stop.start()]).strip()
        prompt = re.split(r'•|===== PDF PAGE', prompt)[0].strip()
    page = int(re.findall(r'===== PDF PAGE (\d+)', text[:m.start()])[-1])
    return str(path), page, prompt


def add(year, table, code, fields, dep='Company-level question; do not infer an answer from missing data.', pathway='full', note=''):
    path, page, prompt = question_info(year, code, pathway)
    availability = 'Questionnaire verified; response columns to check during extraction'
    if year < 2024:
        audit = AUDIT[str(year)]
        availability = ('Workbook not readable during audit' if audit['status'] != 'checked' else 'Standalone sheet present' if code in audit['sheets'] else 'No standalone sheet in local workbook')
    if not any(q['year'] == year and q['pathway'] == pathway and q['question_code'] == code for q in questions):
        questions.append(dict(year=year, pathway=pathway, question_code=code, full_question=prompt, dependency=dep, pdf_page=page, source_pdf=path, local_data_status=availability))
    for short, label, kind in fields:
        rows.append(dict(year=year, pathway=pathway, table=table, question_code=code, short_name=short, source_field=label, data_type=kind, dependency=dep, notes=note, pdf_page=page, source_pdf=path, local_data_status=availability))


def fields(spec):
    return [tuple(line.split('|')) for line in spec.strip().splitlines()]


LEGACY = fields('''risk_driver|Risk driver|category
risk_desc|Description|text
fin_impact_type|Potential impact|category
risk_horizon|Timeframe|category
risk_stage_raw|Direct/Indirect|category
risk_likelihood|Likelihood|category
risk_magnitude|Magnitude of impact|category
fin_impact_text|Estimated financial implications|text
risk_response|Management method|text
response_cost_text|Cost of management|text''')
BASE = fields('''risk_id|Identifier|category
risk_stage|Where in the value chain does the risk driver occur?|category
risk_type|Risk type|category
risk_driver|Primary climate-related risk driver|category
fin_impact_type|Type of financial impact driver|category
risk_desc|Company-specific description|text
risk_horizon|Time horizon|category
risk_likelihood|Likelihood|category
risk_magnitude|Magnitude of impact|category''')
FINANCE = fields('''fin_estimate_type|Are you able to provide a potential financial impact figure?|category
fin_impact|Potential financial impact figure (currency)|decimal
fin_impact_min|Potential financial impact figure - minimum (currency)|decimal
fin_impact_max|Potential financial impact figure - maximum (currency)|decimal
fin_impact_expl|Explanation of financial impact figure|text''')
FULL = fields('''env_issue|Environmental issue the risk relates to|category
risk_id|Risk identifier|category
commodity|Commodity|multiselect; climate N/A
risk_driver_raw|Risk type and primary environmental risk driver|grouped category
risk_stage|Value chain stage where the risk occurs|category
risk_fs_class|Risk type mapped to traditional financial services industry risk classification|multiselect; FS only
risk_country|Country/area where the risk occurs|multiselect
risk_basin|River basin where the risk occurs|multiselect; climate N/A
mining_project|Mining project ID|multiselect; climate N/A
risk_desc|Organization-specific description of risk|text
portfolio_risk_pct|% of portfolio value vulnerable to this risk|percentage band; FS only
fin_impact_type|Primary financial effect of the risk|category
risk_horizons|Time horizon over which the risk is anticipated to have a substantive effect on the organization|multiselect
risk_likelihood|Likelihood of the risk having an effect within the anticipated time horizon|category
risk_magnitude|Magnitude|category
fin_effect_now_desc|Effect of the risk on the financial position, financial performance and cash flows of the organization in the reporting year|text
fin_effect_future_desc|Anticipated effect of the risk on the financial position, financial performance and cash flows of the organization in the selected future time horizons|text
can_quantify_risk|Are you able to quantify the financial effect of the risk?|yes/no
fin_effect_now|Financial effect figure in the reporting year (currency)|decimal
fin_effect_st_min|Anticipated financial effect figure in the short-term - minimum (currency)|decimal
fin_effect_st_max|Anticipated financial effect figure in the short-term - maximum (currency)|decimal
fin_effect_mt_min|Anticipated financial effect figure in the medium-term - minimum (currency)|decimal
fin_effect_mt_max|Anticipated financial effect figure in the medium-term - maximum (currency)|decimal
fin_effect_lt_min|Anticipated financial effect figure in the long-term - minimum (currency)|decimal
fin_effect_lt_max|Anticipated financial effect figure in the long-term - maximum (currency)|decimal
fin_impact_expl|Explanation of financial effect figure|text
response_type|Primary response to risk|grouped category
response_cost|Cost of response to risk|decimal
response_cost_expl|Explanation of cost calculation|text
risk_response|Description of response|text''')

for y in range(2016, 2024):
    if y < 2018:
        yes = 'CC2.1 = integrated company-wide process or dedicated climate-change process.'
        add(y, 'company', 'CC2.1', fields('risk_op_process_raw|Risk management procedures|category\nis_risk_op_assessed|Derived from explicit process-existence answer|nullable boolean'))
        add(y, 'process', 'CC2.1a', fields('assess_freq|Frequency of monitoring|category\nreports_to|To whom are results reported?|category\nassess_geography|Geographical areas considered|text\nassess_horizon_raw|How far into the future are risks considered?|category\nprocess_comment|Comment|text'), yes)
        add(y, 'process', 'CC2.1b', fields('assess_process|Processes applied at company and asset level|text'), yes)
        add(y, 'process', 'CC2.1c', fields('risk_prioritization|How risks and opportunities are prioritized|text'), yes)
        add(y, 'company', 'CC2.1d', fields('no_process_reason|Main reason for not having a process|category\nprocess_plan|Do you plan to introduce a process?|category\nno_process_expl|Comment|text'), 'CC2.1 = no documented process.')
        add(y, 'company', 'CC5.1', fields('risk_categories|Relevant risk categories|multiselect\nhas_climate_risk|Derived from explicit risk-category response|nullable boolean'))
        for code, cat in [('CC5.1a', 'regulation'), ('CC5.1b', 'physical climate'), ('CC5.1c', 'other climate developments')]:
            add(y, 'risk', code, LEGACY, f'CC5.1 identifies risks in category: {cat}.', note=f'Category={cat}; risk key=question_code+row_order. Finance/cost source values may be narratives.')
        add(y, 'company', 'CC5.1_no_risk', fields('no_risk_expl|Explanation for a category without identified inherent risk|text'), 'Risk category not identified in CC5.1.', note='Descriptive branch label, not a verified questionnaire subcode. Do not invent CC5.1d/e/f.')
        continue
    if y < 2020:
        yes = 'C2.2 = integrated company-wide process or dedicated climate-change process.'
        add(y, 'company', 'C2.2', fields('risk_op_process_raw|Process integration option|category\nis_risk_op_assessed|Derived from explicit process-existence answer|nullable boolean'))
        add(y, 'process', 'C2.2a', fields('assess_freq|Frequency of monitoring|category\nassess_horizon_raw|How far into the future are risks considered?|category\nprocess_comment|Comment|text'), yes)
        add(y, 'process', 'C2.2b', fields('assess_process|Risk identification and assessment process|text'), yes)
        add(y, 'process', 'C2.2d', fields('risk_management|Risk/opportunity management process|text'), yes)
        typecode, nocode = 'C2.2c', 'C2.2e'
    else:
        yes = 'C2.1 = Yes.'
        add(y, 'company', 'C2.1', fields('risk_op_process_raw|Does the organization have a process?|yes/no\nis_risk_op_assessed|Derived from explicit Yes/No|nullable boolean'))
        add(y, 'process', 'C2.2', fields('assess_stages|Value chain stage(s) covered|multiselect\nprocess_type|Risk management process|category\nassess_freq|Frequency of assessment|category\nassess_horizons|Time horizon(s) covered|multiselect\nassess_process|Description of process|text'), yes)
        typecode, nocode = 'C2.2a', 'C2.2g'
    add(y, 'risk_type', typecode, fields('assess_risk_type|Risk type (fixed row label)|category\nrisk_type_inclusion|Relevance & inclusion|category\nrisk_type_expl|Please explain|text'), yes, note='Eight climate-risk types; 2018-2019 additionally have Upstream and Downstream rows. Preserve all six relevance/inclusion choices, not a binary flag.')
    add(y, 'company', nocode, fields('no_process_reason|Primary reason|category\nno_process_expl|Please explain|text'), 'C2.2 = no documented process.' if y<2020 else 'C2.1 = No.', note='The plan to introduce a process in two years is a reason option, not a separate observed plan column.')
    add(y, 'company', 'C2.3', fields('climate_risk_raw|Inherent climate-related risks identified|yes/no\nhas_climate_risk|Derived from explicit Yes/No|nullable boolean'), note='Not conditional on process existence.')
    f = list(BASE)
    if y == 2019:
        f[4] = ('fin_impact_type', 'Type of financial impact', 'category')
    elif y >= 2020:
        f[4] = ('fin_impact_type', 'Primary potential financial impact', 'category')
        f.insert(5, ('risk_fs_class', 'Climate risk type mapped to traditional financial services industry risk classification', 'category; FS only'))
    if y == 2018:
        f += fields('fin_impact|Potential financial impact|decimal\nfin_impact_expl|Explanation of financial impact|text\nrisk_response|Management method|text\nresponse_cost|Cost of management|decimal\nrisk_comment|Comment|text')
    elif y == 2019:
        f += FINANCE + fields('risk_response|Management method|text\nresponse_cost|Cost of management|decimal\nrisk_comment|Comment|text')
    else:
        f += FINANCE + fields('response_cost|Cost of response to risk|decimal\nresponse_and_cost_expl|Description of response and explanation of cost calculation|text\nrisk_comment|Comment|text')
    note = ('Stage: Direct operations/Supply chain/Customer. Risk type: Transition/Physical. Horizon includes Current.' if y == 2018 else 'Adds Investment chain to stage choices; Transition/Physical type; horizon includes Current.' if y == 2019 else 'Eight risk types; Direct operations/Upstream/Downstream; no Current horizon option.' if y <= 2021 else 'Adds financial-services portfolio stages; Upstream/Downstream hidden for FS; eight risk types.')
    add(y, 'risk', 'C2.3a', f, 'C2.3 = Yes.', note=note)
    add(y, 'company', 'C2.3b', fields('no_risk_reason|Primary reason|category\nno_risk_expl|Please explain|text'), 'C2.3 = No.')

for y in (2024, 2025):
    add(y, 'company', '2.2.1', fields('''risk_op_process_raw|Process in place|category
is_risk_op_assessed|Derived from Process in place|nullable boolean
process_scope|Risks and/or opportunities evaluated in this process|category
process_dep_link|Is this process informed by the dependencies and/or impacts process?|yes/no
no_process_reason|Primary reason for not evaluating risks and/or opportunities|category
no_process_expl|Explain why you do not evaluate risks and/or opportunities and describe any plans to do so in the future|text
process_link_expl|Explain why you do not have a process for evaluating both risks and opportunities that is informed by a dependencies and/or impacts process|text'''), note='Environmental process, not proof of climate-risk assessment. Process scope: Risks only / Opportunities only / Both. Preserve Yes / No planned / No not planned.')
    proc = fields('''env_issue|Environmental issue|multiselect
process_covers|Indicate which of dependencies, impacts, risks, and opportunities are covered by the process for this environmental issue|multiselect
assess_stages|Value chain stages covered|multiselect
assess_coverage|Coverage|category
supplier_tiers|Supplier tiers covered|multiselect
mining_projects|Mining projects covered|multiselect; sector-specific
assess_method|Type of assessment|category
assess_freq|Frequency of assessment|category
assess_horizons|Time horizons covered|multiselect
process_type|Integration of risk management process|category
assess_location|Location-specificity used|multiselect''')
    if y == 2024:
        proc += fields('tool_types|Type of tools and methods used|multiselect\nassess_tools|Tools and methods used|multiselect\nassess_risk_types|Risk types considered|multiselect\nassess_criteria|Criteria considered|multiselect')
    else:
        proc += fields('assess_tools|Tools and methods used|grouped multiselect\nrisk_types_criteria|Risk types and criteria considered|grouped multiselect')
    proc += fields('assess_stakeholders|Partners and stakeholders considered|multiselect\nprocess_changed|Has this process changed since the previous reporting year?|yes/no\nassess_process|Further details of process|text')
    add(y, 'process', '2.2.2', proc, 'Process in place = Yes in either 2.2 or 2.2.1; select rows including Climate change AND Risks.', note='Not equivalent to the earlier six-category risk-type relevance/inclusion table. In 2025 risk types and criteria form one grouped field.')
    add(y, 'company', '3.1', fields('''env_issue|Environmental issue|category
climate_risk_raw|Environmental risks identified|category
has_climate_risk|Derived from explicit Yes variant / No|nullable boolean
no_risk_reason|Primary reason why your organization does not consider itself to have environmental risks in your direct operations and/or upstream/downstream value chain|category
no_risk_expl|Please explain|text'''), note='Keep Climate change row. Retain detailed Yes variants for operations/value-chain/portfolio; no-risk reason/explanation are in this same table.')
    add(y, 'risk', '3.1.1', FULL, 'Any Yes option in 3.1; select Climate change risk rows.', note='All 30 source columns accounted for; climate-inapplicable columns explicitly marked. Do not combine current and future financial effects with pre-2024 potential-impact fields.')
    add(y, 'company', '15.1', fields('risk_op_process_raw|Process in place|category\nis_risk_op_assessed|Derived from Process in place|nullable boolean\nprocess_scope|Risks and/or opportunities evaluated in this process|category\nassess_freq|Frequency of assessment|category\nassess_process|Please explain the process|text'), pathway='sme', note='No separate structured assessment-stage or risk-type assessment table.')
    add(y, 'company', '16.1', fields('env_issue|Environmental issue|category\nclimate_risk_raw|Environmental risks identified|category\nhas_climate_risk|Derived from explicit Yes variant / No|nullable boolean\nno_risk_reason|Primary reason why your organization does not consider itself to have environmental risks in your direct operations and/or upstream/downstream value chain|category'), pathway='sme', note='Climate change row. No separate Please explain column in this SME table.')
    sme = [FULL[i] for i in [0,1,2,3,4,6,7,9,11,12,13,14,17]]
    sme[3] = ('risk_driver_raw', 'Risk type and primary source of the environmental risk', 'grouped category')
    sme += fields('fin_effect_min|Potential financial effect figure - minimum (currency)|decimal\nfin_effect_max|Potential financial effect figure - maximum (currency)|decimal') + [FULL[i] for i in [25,26,27,28,29]]
    add(y, 'risk', '16.1.1', sme, 'Any Yes option in 16.1; select Climate change risk rows.', pathway='sme', note='All 20 SME source columns accounted for. No separate current/ST/MT/LT financial estimates.')

for y in range(2020, 2026):
    code = 'C2.2' if y < 2024 else '2.2.2'
    for suffix, label in [('direct', 'Direct operations'), ('upstream', 'Upstream'), ('downstream', 'Downstream')]:
        add(y, 'process', code, [(f'assess_{suffix}', f'Derived membership of {label} in assessment stages', 'nullable boolean')], 'Same applicability as assessment-stage source field.', note='1 if selected; 0 only for an applicable, complete, nonblank response not selecting it; otherwise blank. Hidden FS Downstream is not 0.')


def write_csv(path, data, names=None):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=names or list(data[0]))
        writer.writeheader()
        writer.writerows(data)


for y in range(2018, 2026):
    code = 'C2.1' if y < 2020 else 'C2.1a' if y < 2024 else '2.1'
    horizon_fields = fields('horizon|Time horizon|category\nhorizon_from_yrs|From (years)|integer\nhorizon_to_yrs|To (years)|integer')
    horizon_fields += (fields('horizon_comment|Comment|text') if y < 2024 else fields('horizon_open_ended|Is your long-term time horizon open ended?|yes/no; long-term only\nhorizon_planning_link|How this time horizon is linked to strategic and/or financial planning|text'))
    add(y, 'horizon', code, horizon_fields, note='Required following the clarified sheet scope. Short-, medium-, and long-term fixed rows; preserve the organization-specific definitions.')
for y in range(2020, 2024):
    add(y, 'company', 'C2.1b', fields('materiality_def|Definition of substantive financial or strategic impact|text'), note='Top-level answer may be stored in the C2 - Risks and Opportunities overview sheet.')
add(2020, 'company', 'C2.4', fields('climate_opp_raw|Climate-related opportunities identified|category'), note='Keep original Yes / Yes but unable to realize / No variants. Overview-sheet column.')
opp = fields('''opp_id|Identifier|category
opp_stage|Where in the value chain does the opportunity occur?|category
opp_type|Opportunity type|category
opp_driver|Primary climate-related opportunity driver|category
opp_fin_type|Primary potential financial impact|category
opp_desc|Company-specific description|text
opp_horizon|Time horizon|category
opp_likelihood|Likelihood|category
opp_magnitude|Magnitude of impact|category
opp_fin_estimate_type|Are you able to provide a potential financial impact figure?|category
opp_fin_impact|Potential financial impact figure (currency)|decimal
opp_fin_min|Potential financial impact figure - minimum (currency)|decimal
opp_fin_max|Potential financial impact figure - maximum (currency)|decimal
opp_fin_expl|Explanation of financial impact figure|text
opp_cost|Cost to realize opportunity|decimal
opp_strategy_cost_expl|Strategy to realize opportunity and explanation of cost calculation|text
opp_comment|Comment|text''')
add(2020, 'opportunity', 'C2.4a', opp, 'C2.4 = Yes (not the separate Yes, but unable to realize option).', note='Included as the requested 2020 sheet example; the full cross-year opportunity review follows risk-template approval.')
for record in rows + questions:
    if record['local_data_status'] == 'No standalone sheet in local workbook':
        record['local_data_status'] = 'No dedicated sheet; check module overview columns (not evidence of missing answers)'
    if record['year'] in {2020, 2021} and record['question_code'] in {'C2.1', 'C2.1b', 'C2.3', 'C2.4'}:
        record['local_data_status'] = 'Verified column in C2 - Risks and Opportunities overview sheet'
write_csv(OUT / 'risk_field_mapping_2016_2025.csv', rows)
write_csv(OUT / 'risk_questions_2016_2025.csv', questions)
for y in range(2016, 2026):
    directory = OUT / str(y)
    directory.mkdir(exist_ok=True)
    subset = [r for r in rows if r['year'] == y]
    write_csv(directory / 'field_mapping.csv', subset)
    for pathway in sorted({r['pathway'] for r in subset}):
        for table in sorted({r['table'] for r in subset if r['pathway'] == pathway}):
            selected = [r for r in subset if r['pathway'] == pathway and r['table'] == table]
            names = list(dict.fromkeys(r['short_name'] for r in selected))
            keys = ['year', 'cdp_account_number', 'questionnaire_pathway']
            if table != 'company':
                keys += ['question_code', 'row_order']
            write_csv(directory / f'{pathway}_{table}_template.csv', [], keys + names)

md = ['# CDP risk extraction template: 2016-2025',
      '**Draft for review. This task has not changed the datasets or production extraction code.**',
      '**Clarified workbook scope:** use `C2 - Risks and Opportunities`, `C2.1a`, `C2.2`, `C2.3a`, and `C2.4a` as the 2020 example. The last code is C2.4a, without an extra dot after C. Read question columns inside overview sheets as well as dedicated question sheets. The 2020 and 2021 overview sheets were inspected and contain C2.1, C2.1b, C2.3 and C2.4. The 2020 template is checked against actual workbook headers. Time-horizon definitions are now included across years, and the requested 2020 C2.4a opportunity example is included. The earlier requested C2.2a, C2.2g and C2.3b remain in the risk review as well.',
      'Use `is_risk_op_assessed` rather than `is_risk&op_assessed` for compatibility with Python, SQL and statistical software. Its precise meaning is **an assessment/management process exists**, not that assessment was completed. `risk_op_process_raw` retains the original answer; `has_climate_risk` separately records substantive risk identification.',
      '## Proposed structure',
      '| Table | One row per | Content |\n|---|---|---|\n| company | Company-year-pathway | Process existence, risk existence, no-process/no-risk reasons |\n| process | Company-year and process row | Assessment coverage, frequency, horizons and details |\n| risk_type | Company-year and risk-type row (2018-2023) | Relevance/inclusion and explanation |\n| risk | Company-year and individual risk | All risk details, financial impacts and responses |',
      'Keys are `year`, `cdp_account_number`, `questionnaire_pathway`, and for repeating tables `question_code` and `row_order`. Keep `risk_id` when supplied; legacy risk categories use question code plus row order. A company-year view can be generated later, but keeping one row per risk prevents mixing one risk\'s driver with another risk\'s cost. All supplied CSV templates contain headers only, not invented observations.',
      'Answer cells contain only answers; multiselect answers use JSON string lists. Original labels, source paths and cell-status flags belong in a separate provenance export. A missing member of a repeated risk record must not shift the alignment of other fields.',
      '## Decisions that prevent incorrect cross-year comparisons',
      '- **2018-2019 C2.1 is about time horizons.** The process-existence question is C2.2. From 2020-2023 the process question becomes C2.1.',
      '- Assessment coverage (`assess_stages`) differs from the location of a disclosed risk (`risk_stage`). Structured direct/upstream/downstream assessment-stage coverage starts in 2020. The 2018-2019 Upstream/Downstream assessment rows are not the same question.',
      '- For 2024-2025, process existence is environmental, not necessarily climate-specific. Keep `process_scope`, and use 2.2.2 rows including Climate change and Risks. An opportunities-only process does not establish climate-risk assessment.',
      '- Preserve the six relevance/inclusion categories in 2018-2023. Do not replace them with a yes/no flag. In 2024 types are multiselect; in 2025 types and criteria are combined grouped selections.',
      '- Preserve original category labels: Supply chain/Customer/Investment chain in older years are not silently relabeled as Upstream/Downstream. Keep any harmonized categories as separate derived fields.',
      '- Keep legacy financial/cost narratives as text. From 2019, retain point estimates, ranges and no-estimate status separately. In 2024-2025 distinguish reporting-year effects from short/medium/long-term anticipated effects. Join the organization\'s reporting currency before comparing amounts.',
      '- The 65% missingness filter from the earlier panel is **not applied to this review template**. Structural absence and conditional branches should not erase requested questions.',
      '- Distinguish not asked that year, branch skipped, source not provided, unanswered, and explicit No. Only explicit answers can produce 0/1 indicators. Do not infer No from absence of a detailed risk table.',
      '- Financial-services-only columns inside the requested risk tables are retained. Additional portfolio-assessment question families are outside this core scope. SME questions are documented separately for 2024-2025.',
      '## Year-by-year question map',
      '| Year | Process exists | Assessment details/types | No process | Risks exist | Individual risks | No risk |\n|---|---|---|---|---|---|---|']
for y in range(2016, 2026):
    mapping = ([str(y), 'CC2.1', 'CC2.1a-c', 'CC2.1d', 'CC5.1', 'CC5.1a/b/c', 'CC5.1 category branch'] if y < 2018 else
               [str(y), 'C2.2', 'C2.2a-d; types C2.2c', 'C2.2e', 'C2.3', 'C2.3a', 'C2.3b'] if y < 2020 else
               [str(y), 'C2.1', 'C2.2; types C2.2a', 'C2.2g', 'C2.3', 'C2.3a', 'C2.3b'] if y < 2024 else
               [str(y), '2.2.1', '2.2.2', '2.2.1 same table', '3.1', '3.1.1', '3.1 same table'])
    md.append('| ' + ' | '.join(mapping) + ' |')
md += ['## Main dependencies and response choices',
       '**2020-2023:** C2.1=Yes enables C2.2/C2.2a; C2.1=No enables C2.2g. Independently, C2.3=Yes enables C2.3a; C2.3=No enables C2.3b. Do not gate risk existence on process existence.',
       '**2018-2019:** integrated/dedicated process in C2.2 enables C2.2a-d; no documented process enables C2.2e. **2016-2017:** CC2.1 governs CC2.1a-c versus CC2.1d; CC5.1 categories govern their risk/no-risk branches.',
       '**2024-2025 full:** a process in either 2.2 or 2.2.1 enables 2.2.2. Its presence alone does not prove risk assessment; filter Climate change and Risks. Any Yes option in 3.1 enables 3.1.1, with a Climate change row filter. SME uses 16.1 -> 16.1.1.',
       '**Assessment stages (2020-2023):** Direct operations, Upstream, Downstream. The 2022-2023 questionnaire hides Downstream assessment coverage for financial services. `assess_direct`, `assess_upstream`, `assess_downstream` are nullable derived indicators. Selected=1; not selected=0 only when a complete answer is present and the option applies. Otherwise blank.',
       '**Assessment risk types (2018-2023):** Current regulation; Emerging regulation; Technology; Legal; Market; Reputation; Acute physical; Chronic physical. 2018-2019 additionally include Upstream and Downstream rows.',
       '**Risk-type inclusion options:** Relevant, always included; Relevant, sometimes included; Relevant, not included; Not relevant, included; Not relevant, explanation provided; Not evaluated.',
       '**2024-2025 risk-type groups:** Acute physical; Chronic physical; Policy; Market; Reputation; Technology; Liability. These groups do not reproduce the old Current/Emerging regulation distinction.',
       '**Financial estimate availability (2019-2023):** Yes, a single figure estimate; Yes, an estimated range; No, we do not have this figure. Missing estimates remain blank, never zero.',
       '## Full annual question and field templates']
for y in range(2016, 2026):
    md.append(f'### {y}')
    if y < 2024:
        absent = sorted({q['question_code'] for q in questions if q['year'] == y and q['local_data_status'] == 'No standalone sheet in local workbook'})
        if absent:
            md.append('**Local export caveat:** no standalone sheets for ' + ', '.join(f'`{c}`' for c in absent) + '. Check alternative response packaging during extraction; do not interpret these omissions as No. The CC5.1_no_risk label is descriptive, not an actual sheet code.')
        elif AUDIT[str(y)]['status'] != 'checked':
            md.append('**Local export caveat:** the 2020 workbook returned a file-access error. Questionnaire mapping is verified; workbook column availability remains unchecked.')
    for pathway in sorted({q['pathway'] for q in questions if q['year'] == y}):
        src, _ = source(y, pathway)
        md.append(f'**{pathway.upper()} questionnaire.** Source: [{src.name}](<{src.as_posix()}>). Page references are 1-based PDF pages, including the cover.')
        if y == 2025 and pathway == 'full':
            md.append('**2025 change:** tools/methods and risk-types/criteria use grouped selections instead of separate 2024 group and option columns.')
        for q in [q for q in questions if q['year'] == y and q['pathway'] == pathway]:
            md += [f"**{q['question_code']} — {q['full_question']}** (PDF p. {q['pdf_page']})", 'Dependency: ' + q['dependency'], '| Short name | Source field / meaning | Type |\n|---|---|---|']
            selected = [r for r in rows if r['year'] == y and r['pathway'] == pathway and r['question_code'] == q['question_code']]
            for r in selected:
                md.append(f"| `{r['short_name']}` | {r['source_field']} | {r['data_type']} |")
            notes = list(dict.fromkeys(r['notes'] for r in selected if r['notes']))
            md.extend(notes)
md += ['## Supporting questions and review files',
       'Time-horizon definitions and 2020-2023 substantive-impact definitions are included after the clarified workbook scope. The additional financial-metrics question 3.1.2 remains outside this C2.3a-equivalent scope.',
       '`risk_questions_2016_2025.csv`: parent-question wording, year, dependency, PDF page and source. `risk_field_mapping_2016_2025.csv`: full field mappings, types, notes and source availability. Each annual folder contains a field dictionary and empty CSV table templates. The requested 2020 opportunity sheet is included as an example; the full cross-year opportunity review remains next.']
document = re.sub(r'\|\n\n(?=\|)', '|\n', '\n\n'.join(md))
(OUT / 'README.md').write_text(document + '\n', encoding='utf-8')
assert {r['year'] for r in rows} == set(range(2016, 2026))
assert all(re.fullmatch('[a-z][a-z0-9_]*', r['short_name']) for r in rows)
assert all(Path(r['source_pdf']).exists() for r in rows)
for y in (2024, 2025):
    assert len([r for r in rows if r['year'] == y and r['question_code'] == '3.1.1']) == 30
    assert len([r for r in rows if r['year'] == y and r['question_code'] == '16.1.1']) == 20
for path in OUT.glob('*/*template.csv'):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        cols = next(csv.reader(stream))
        assert len(cols) == len(set(cols)), path
print(f'Created {len(questions)} question mappings and {len(rows)} field mappings in {OUT}')

headers_path = CACHE / '2020_actual_headers.json'
if headers_path.exists():
    headers = json.loads(headers_path.read_text(encoding='utf-8'))
    overview = {'C2.1': 'risk_op_process_raw', 'C2.1b': 'materiality_def', 'C2.3': 'climate_risk_raw', 'C2.4': 'climate_opp_raw'}
    by_col = {
        'C2.1a': ['horizon_from_yrs', 'horizon_to_yrs', 'horizon_comment'],
        'C2.2': ['assess_stages', 'process_type', 'assess_freq', 'assess_horizons', 'assess_process'],
        'C2.2a': ['risk_type_inclusion', 'risk_type_expl'],
        'C2.2g': ['no_process_reason', 'no_process_expl'],
        'C2.3a': ['risk_id', 'risk_stage', 'risk_driver', 'fin_impact_type', 'risk_fs_class', 'risk_desc', 'risk_horizon', 'risk_likelihood', 'risk_magnitude', 'fin_estimate_type', 'fin_impact', 'fin_impact_min', 'fin_impact_max', 'fin_impact_expl', 'response_cost', 'response_and_cost_expl', 'risk_comment'],
        'C2.3b': ['no_risk_reason', 'no_risk_expl'],
        'C2.4a': [f[0] for f in opp],
    }
    metadata = {'Account number': 'cdp_account_number', 'Organization': 'company_name', 'Country': 'country', 'Primary activity': 'primary_activity', 'Primary sector': 'primary_sector', 'Primary industry': 'primary_industry', 'Primary questionnaire sector': 'questionnaire_sector', 'Row': 'row_order', 'RowName': 'row_name'}
    requested = ['C2 - Risks and Opportunities', 'C2.1a', 'C2.2', 'C2.3a', 'C2.4a']
    exact = []
    for sheet, labels in headers.items():
        for label in labels:
            if label in metadata:
                short = ('horizon' if sheet == 'C2.1a' and label == 'RowName' else 'assess_risk_type' if sheet == 'C2.2a' and label == 'RowName' else metadata[label])
                role = 'key / metadata'
            elif sheet == requested[0]:
                short = overview[label.split('_', 1)[0]]
                role = 'answer'
            else:
                number = int(re.search(r'_C(\d+)_', label)[1])
                short = 'risk_type' if sheet == 'C2.3a' and number == 3 and label.endswith('_G') else by_col[sheet][number - 1]
                role = 'answer'
            exact.append(dict(year=2020, sheet=sheet, scope='specified five sheets' if sheet in requested else 'earlier risk request', original_header=label, short_name=short, role=role))
    for sheet in headers:
        names = [r['short_name'] for r in exact if r['sheet'] == sheet]
        assert len(names) == len(set(names)), sheet
    write_csv(OUT / '2020' / 'verified_workbook_column_mapping.csv', exact)
    example = ['# 2020 workbook extraction template',
               '**Verified against the actual Excel headers. Review template only; no answer data extracted or overwritten.**',
               'Use these five sheets as requested. `C2.4a` is the opportunity sheet; there is no extra dot after C.',
               '| Source sheet | Content | Row unit |\n|---|---|---|\n| C2 - Risks and Opportunities | Process existence; substantive-impact definition; risk and opportunity identification | Company-year |\n| C2.1a | Short-, medium-, long-term definitions | Company-year-horizon |\n| C2.2 | Value-chain assessment coverage and processes | Company-year-process |\n| C2.3a | All individual risk fields | Company-year-risk |\n| C2.4a | All individual opportunity fields | Company-year-opportunity |',
               'Common identifiers: `year`, `cdp_account_number`, `company_name`. Keep `row_order` and the source row label for alignment; `RowName` specifically becomes `horizon` in C2.1a. Preserve `country`, `primary_activity`, `primary_sector`, `primary_industry` and `questionnaire_sector` in company metadata.',
               '`is_risk_op_assessed` is derived from the explicit C2.1 Yes/No answer (1/0; missing stays missing). Its meaning is a process exists. `risk_op_process_raw` keeps the original answer. `has_climate_risk` can similarly be derived from C2.3. Preserve all C2.4 opportunity response variants rather than turning “Yes, but unable to realize” into No.',
               'Keep a separate row for each risk/opportunity. Multiselect cells contain only selected answer strings. No source metadata is embedded in answer values, and no 65% missingness filter is applied at the extraction/template stage.']
    for sheet in requested:
        example += [f'## {sheet}', '| Actual field / meaning | Short name |\n|---|---|']
        for r in exact:
            if r['sheet'] == sheet and (r['role'] == 'answer' or r['short_name'] == 'horizon'):
                label = r['original_header'].split(' - ')[-1]
                if sheet == requested[0]:
                    label = r['original_header'].split('_', 1)[1]
                example.append(f"| {label} | `{r['short_name']}` |")
        if sheet == 'C2.1a':
            example.append('Three fixed rows: Short-term, Medium-term, Long-term. Do not drop RowName; it identifies which definition the values belong to.')
        if sheet == 'C2.2':
            example.append('Only asked when C2.1=Yes. `assess_stages` contains Direct operations / Upstream / Downstream. Optional `assess_direct`, `assess_upstream`, `assess_downstream` indicators can be derived from a complete applicable response.')
        if sheet == 'C2.3a':
            example.append('Only asked when C2.3=Yes. The `_G` driver column is `risk_type`; the unsuffixed companion is `risk_driver`. This was verified against actual values. Preserve the combined response-and-cost narrative as one field.')
        if sheet == 'C2.4a':
            example.append('Only asked when C2.4=Yes. The separate “Yes, but unable to realize” option does not trigger this detail table.')
    example += ['## Additional sheets from the earlier risk request',
                '`C2.2a` provides risk-type relevance/inclusion, with the risk type stored in RowName. `C2.2g` provides the no-process reason and explanation when C2.1=No. `C2.3b` provides the no-risk reason and explanation when C2.3=No. These remain in the wider risk template; the five sheets alone would omit those answers.',
                'The companion `verified_workbook_column_mapping.csv` contains exact source header strings for all eight checked sheets, including the group suffix and source encoding artifacts, so an implementation can match them without guessing.',
                'The year-by-year questionnaire equivalents and full risk templates for 2016-2025 are in the parent README and annual folders. The 2020 opportunity sheet is included here following the clarified example; the full opportunity review across years is the next step.']
    (OUT / '2020' / 'WORKBOOK_TEMPLATE.md').write_text(re.sub(r'\|\n\n(?=\|)', '|\n', '\n\n'.join(example)) + '\n', encoding='utf-8')
    print(f'Verified 2020 workbook mapping: {len(exact)} headers across {len(headers)} sheets.')

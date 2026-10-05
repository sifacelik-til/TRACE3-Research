"""Curate four CDP section datasets from staged original answer records.

Run extraction first, then python -m src.cdp_extraction.build_cdp_section_datasets.
"""
import csv
import gzip
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from itertools import chain
from contextlib import ExitStack
from functools import lru_cache
from .extract_cdp_section_records import ROOT, OUT, STAGE, base_sample, key, section


def label(header):
    value = header.replace('\xa0', ' ').strip()
    if re.match(r'^col\d+_', value, re.I):
        value = re.sub(r'^col\d+_', '', value, flags=re.I)
    else:
        m = re.match(r'^(?:CC?|Q)\d+(?:\.\d+)*[a-z]?[ _]+C\d+[ _]*(?:-\s*)?(.*)', value, re.I)
        if m:
            value = m[1].split(' - ', 1)[-1]
        else:
            value = re.sub(r'^(?:CC?|Q)\d+(?:\.\d+)*[a-z]?[ _-]*', '', value, flags=re.I)
    return re.sub(r'\s+', ' ', value).strip().lower().rstrip('? ')


def pick(text, rules):
    for pattern, field in rules:
        if re.search(pattern, text): return field
    return None


TARGET_RULES = [
    (r'^scope 2 accounting method', 'scope2_basis'),
    (r'^base year energy.*mwh|^consumption or production.*base year.*mwh', 'base_energy_mwh'),
    (r'^target type: energy carrier', 'energy_carrier'),
    (r'^target type: energy source', 'energy_source'),
    (r'^target type: activity', 'energy_activity'),
    (r'^target denominator', 'other_target_denominator'),
    (r'^end date of base year', 'base_year_end_date'),
    (r'^base year emissions covered.*all selected scopes as %', 'base_emissions_coverage_pct'),
    (r'^% share of low.carbon or renewable energy in base year', 'base_value'),
    (r'^% share of low.carbon or renewable energy in reporting year', 'report_value'),
    (r'^% share of low.carbon or renewable energy at end date', 'target_value'),
    (r'^figure or percentage at end of date of target', 'target_value'),
    (r'^active climate.related target', 'other_target_type'),
    (r'^description of target', 'target_description'),
    (r'^list the emissions reduction initiatives', 'target_key_initiatives'),
    (r'^plan for achieving target', 'target_plan_progress'),
    (r'^do you intend to neutralize', 'net_zero_removals'),
    (r'^do you intend to purchase and cancel carbon credits', 'net_zero_credit_plans'),
    (r'^date target was set', 'target_set_date'),
    (r'^(?:target reference|id$)', 'target_id'),
    (r'^year target was set|^start year$', 'target_set_year'),
    (r'^target coverage$', 'target_coverage'),
    (r'^s(?:cope)? ?3 categories|^scope 3 category', 'scope3_categories'),
    (r'^(?:scope\(s\)|scopes?|ghg scope)(?: covered by target)?$', 'scopes'),
    (r'^greenhouse gases', 'ghgs'),
    (r'^s(?:cope)? ?3 categories|^scope 3 category', 'scope3_categories'),
    (r'^base year$|^base year \(', 'base_year'),
    (r'^target year$|^end date of target|^target year for achieving net zero', 'target_year_or_date'),
    (r'^is this a science.based|^science.based target$|^is this target science.based', 'sbt_status'),
    (r'^target status', 'target_status'),
    (r'^(?:targeted )?(?:% |percentage )?reduction from base(?:line)? year|^targeted reduction', 'target_reduction_pct'),
    (r'^% (?:of )?target achieved|^% achieved \(emissions\)|^% complete \(emissions|^% achieved in reporting year', 'target_achieved_pct'),
    (r'^% complete \(time', 'target_time_pct'),
    (r'^(?:intensity metric|metric$)', 'target_metric'),
    (r'^total base year emissions covered.*all selected|^covered emissions in base year \(metric|^base year emissions covered by target ?\(metric', 'base_emissions_tco2e'),
    (r'^total emissions in reporting year covered.*all selected|^covered emissions in reporting year \(metric', 'report_emissions_tco2e'),
    (r'^total emissions.*(?:target|end date).*all selected|^covered emissions in target year \(metric', 'target_emissions_tco2e'),
    (r'^base year.*total scope 3 emissions covered by target \(', 'base_scope3_tco2e'),
    (r'^intensity figure in base year.*all selected scopes|^intensity figure in base year \(|^normalized base(?:line)? year emissions', 'base_intensity'),
    (r'^intensity figure in reporting year.*all selected scopes|^intensity figure in reporting year \(', 'report_intensity'),
    (r'^intensity figure.*(?:target year|end date of target).*all selected scopes|^intensity figure in target year \(', 'target_intensity'),
    (r'^% (?:of )?emissions.*scope|^covered emissions in base year as %|^% of total base year emissions(?: in all selected scopes|$)', 'base_emissions_coverage_pct'),
    (r'^kpi.*metric numerator', 'other_target_metric'),
    (r'^kpi.*metric denominator', 'other_target_denominator'),
    (r'^kpi in baseline year', 'base_value'),
    (r'^kpi in target year', 'target_value'),
    (r'^target$|^target type: absolute or intensity', 'other_target_type'),
    (r'^target ambition', 'target_ambition'),
    (r'^target type:.*category.*_g$', 'other_target_category'),
    (r'^target type:.*category|^metric \(target numerator|^target denominator', 'other_target_metric'),
    (r'^target type:.*(?:energy|activity)|^energy types covered', 'energy_target_type'),
    (r'^figure or percentage in base year|^base year energy|^% renewable energy in base', 'base_value'),
    (r'^figure or percentage in target year|^% renewable energy in target', 'target_value'),
    (r'^figure or percentage in reporting year', 'report_value'),
    (r'^net.zero target year', 'target_year_or_date'),
    (r'^targets linked|^absolute.*target.*linked|^reference.*linked', 'linked_targets'),
]
INITIATIVE_RULES = [
    (r'^(?:initiative category.*_g|initiative category$|activity type$)', 'initiative_category'),
    (r'^initiative type$|^initiative category.*initiative type|^description of (?:activity|initiative)', 'initiative_type'),
    (r'^estimated annual co2e savings', 'est_annual_savings_tco2e'),
    (r'^scope', 'scopes'),
    (r'^voluntary', 'voluntary_mandatory'),
    (r'^annual monetary savings', 'annual_savings_money'),
    (r'^investment required', 'investment_money'),
    (r'^payback period', 'payback_period'),
    (r'^estimated lifetime', 'initiative_lifetime'),
    (r'^comment$|^please explain$', 'initiative_details'),
]
VERIFY_RULES = [
    (r'^scope$', 'scope'),
    (r'^verification/assurance status|^verification or assurance status|^indicate.*verification|^please indicate.*verification', 'verify_status'),
    (r'^verification or assurance cycle|^verification/assurance cycle', 'verify_cycle'),
    (r'^status in.*reporting year', 'verify_year_status'),
    (r'^type of verification', 'assurance_level'),
    (r'^relevant standard|^verification standard', 'verify_standard'),
    (r'^proportion.*verified', 'verified_pct'),
    (r'^scope 2 approach|^location.based or market.based', 'scope2_basis'),
    (r'^scope 3 category', 'scope3_categories'),
    (r'^data verified|^additional data points verified', 'other_verified_data'),
    (r'^disclosure module verification', 'verified_module'),
    (r'^do you verify', 'other_data_verified'),
]
PRICE_RULES = [
    (r'^actual price.*minimum', 'internal_price_min'),
    (r'^actual price.*maximum', 'internal_price_max'),
    (r'^% of emissions covered by tax', 'tax_emissions_covered_pct'),
    (r'^scheme name|^emissions trading scheme|^name of.*(?:tax|scheme)', 'pricing_system'),
    (r'^%.*scope 1.*(?:ets|tax)', 'scope1_covered_pct'),
    (r'^%.*scope 2.*ets', 'scope2_covered_pct'),
    (r'^allowances allocated', 'allowances_allocated'),
    (r'^allowances purchased', 'allowances_purchased'),
    (r'^verified scope 1 emissions', 'ets_scope1_tco2e'),
    (r'^verified scope 2 emissions', 'ets_scope2_tco2e'),
    (r'^verified emissions', 'ets_verified_tco2e'),
    (r'^total cost of tax paid', 'carbon_tax_paid'),
    (r'^type of (?:internal carbon price|pricing scheme)', 'internal_price_type'),
    (r'^objective', 'price_objective'),
    (r'^ghg scope|^scopes covered', 'scopes'),
    (r'^application$|^business decision.making processes', 'price_application'),
    (r'^actual price', 'internal_price_raw'),
    (r'^minimum actual price', 'internal_price_min'),
    (r'^maximum actual price', 'internal_price_max'),
    (r'^internal price is mandatory', 'price_mandatory'),
    (r'^% total emissions', 'price_emissions_pct'),
    (r'^impact.*implication', 'price_effect'),
    (r'^credit origination or credit purchase|^were these credits issued', 'credit_origin'),
    (r'^project type', 'credit_project_type'),
    (r'^type of mitigation activity', 'credit_mitigation_type'),
    (r'^project identification|^project description', 'credit_project'),
    (r'^verified to which standard|^carbon.crediting program', 'credit_standard'),
    (r'^number of credits.*risk adjusted', 'credit_risk_adj_tco2e'),
    (r'^number of credits', 'credits_tco2e'),
    (r'^credits cance(?:l|ll)ed$|^credits retired$', 'credits_canceled_status'),
    (r'^credits (?:cance(?:l|ll)ed|retired) by.*metric', 'credits_retired_tco2e'),
    (r'^purpose', 'credit_purpose'),
    (r'^vintage of credits', 'credit_vintage'),
]
ENGAGE_RULES = [
    (r'^type of engagement.*_g$', 'engagement_category'),
    (r'^procedures to engage non.compliant', 'noncompliance_procedure'),
    (r'^type of stakeholder', 'stakeholder'),
    (r'^% of stakeholder type engaged', 'stakeholder_covered_pct'),
    (r'^% stakeholder.associated scope 3', 'stakeholder_s3_covered_pct'),
    (r'^% of non.compliant suppliers engaged', 'noncompliant_engaged_pct'),
    (r'^engagement is helping your tier 1 suppliers engage', 'suppliers_engage_own_chain'),
    (r'^type of clients', 'client_type'),
    (r'^%.*investing \(asset managers\).*portfolio', 'asset_manager_portfolio_pct'),
    (r'^%.*investing \(asset owners\).*portfolio', 'asset_owner_portfolio_pct'),
    (r'^%.*scope 3 investees associated', 'investee_s3_covered_pct'),
    (r'^%.*procurement spend.*(?:required|have to comply)', 'required_spend_pct'),
    (r'^%.*procurement spend in compliance', 'compliant_spend_pct'),
    (r'^%.*tier 1 suppliers by procurement spend covered', 'tier1_spend_covered_pct'),
    (r'^climate.related requirement$', 'supplier_requirement'),
    (r'^description of this climate.related requirement', 'requirement_details'),
    (r'^environmental issue', 'environmental_issues'),
    (r'^engaging with this stakeholder', 'engagement_status'),
    (r'^primary reason for (?:not|no) engag', 'no_engagement_reason'),
    (r'^explain why you do not engage', 'no_engagement_expl'),
    (r'^type and details|^type of engagement|^methods of engagement', 'engagement_type'),
    (r'^details of engagement', 'engagement_details'),
    (r'^action driven by supplier', 'engagement_action'),
    (r'^% (?:of )?suppliers by number', 'suppliers_covered_pct'),
    (r'^number of suppliers$', 'suppliers_count'),
    (r'^%.*(?:total )?procurement spend|^%.*total spend', 'spend_covered_pct'),
    (r'^%.*tier 1 suppliers by procurement spend covered', 'tier1_spend_covered_pct'),
    (r'^%.*supplier.related scope 3 emissions.*covered', 'supplier_s3_covered_pct'),
    (r'^%.*supplier.related scope 3 emissions as reported|^% scope 3 emissions as reported', 'supplier_s3_covered_pct'),
    (r'^%.*customers by number', 'customers_covered_pct'),
    (r'^%.*customer.*scope 3', 'customer_s3_covered_pct'),
    (r'^%.*client.associated scope 3', 'client_s3_covered_pct'),
    (r'^%.*investees associated emissions', 'investee_s3_covered_pct'),
    (r'^portfolio coverage|^%.*portfolio covered', 'portfolio_covered_pct'),
    (r'^upstream value chain coverage', 'supplier_tiers'),
    (r'^number of tier 2', 'tier2plus_count'),
    (r'^impact of engagement|^effect of engagement|^describe the engagement and explain the effect', 'engagement_effect'),
    (r'^rationale for.*coverage|^please explain.*rationale|^explain the rationale', 'coverage_reason'),
    (r'^suppliers have to meet', 'supplier_requirements'),
    (r'^policy in place.*non.compliance', 'noncompliance_policy'),
    (r'^environmental requirement$', 'supplier_requirement'),
    (r'^mechanisms for monitoring', 'compliance_monitoring'),
    (r'^%.*procurement spend required', 'required_spend_pct'),
    (r'^%.*procurement spend in compliance', 'compliant_spend_pct'),
    (r'^%.*scope 3.*required to comply', 'required_s3_pct'),
    (r'^%.*scope 3.*in compliance', 'compliant_s3_pct'),
    (r'^response to supplier non.compliance|^procedures to engage non.compliant', 'noncompliance_response'),
    (r'^assessment of supplier dependencies', 'suppliers_assessed'),
    (r'^% tier 1 suppliers assessed', 'tier1_assessed_pct'),
    (r'^supplier engagement prioritization', 'supplier_prioritization'),
    (r'^criteria informing.*prioritized', 'prioritization_criteria'),
    (r'^how you make use of the data', 'supplier_data_use'),
    (r'^please give details$', 'supplier_data_details'),
    (r'^number of smallholders', 'smallholders_count'),
    (r'^stakeholder', 'stakeholder'),
]


@lru_cache(maxsize=None)
def record_type(code, year):
    c=code.upper().removeprefix('Q')
    types={
        'absolute_target':['CC3.1A','C4.1A','7.53.1','20.16.1'],
        'intensity_target':['CC3.1B','C4.1B','7.53.2','20.16.2'],
        'energy_target':['CC3.1D','C4.2A','7.54.1'],
        'other_target':['C4.2B','7.54.2','20.16.3'],
        'net_zero_target':['C4.2C','7.54.3'],
        'target_progress':['CC3.1E'],
        'no_target':['CC3.1F','C4.1C','7.53.3'],
        'initiative_stage':['CC3.3A','C4.3A','7.55.1'],
        'initiative':['CC3.3B','C4.3B','7.55.2','20.17.1'],
        'investment_method':['CC3.3C','C4.3C','7.55.3'],
        'no_initiative':['CC3.3D','C4.3D','7.55.4'],
        'verify_scope1':['CC8.6A','C10.1A','7.9.1'],
        'verify_scope2':['CC8.7A','C10.1B','7.9.2'],
        'verify_scope3':['CC14.2A','C10.1C','7.9.3'],
        'verify_status':['CC8.6','CC8.7','CC14.2','C10.1','7.9','20.8'],
        'other_verification':['CC8.8','C10.2A','C10.2'],
        'ets':['CC13.1A','C11.1B','3.5.2'],
        'carbon_tax':['C11.1C','3.5.3'],
        'carbon_credit':['CC13.2A','C11.2A','7.79.1'],
        'internal_price':['CC2.2D','C11.3A','5.10.1'],
        'supplier_engagement':['C12.1A','5.11.7'],
        'customer_engagement':['C12.1B'],
        'supplier_assessment':['5.11.1','5.11.2'],
        'supplier_requirements':['5.11.5','5.11.6','C12.2A'],
        'client_engagement':['5.11.3'],
        'investee_engagement':['5.11.4'],
        'smallholder_engagement':['5.11.8'],
        'other_engagement':['5.11.9','CC14.4A','C12.1D'],
        'supplier_coverage':['CC14.4B'],
        'supplier_data_use':['CC14.4C'],
        'no_engagement':['CC14.4D','C12.1E'],
    }
    if c=='C4.2' and year<=2019:return 'other_target'
    if c=='C10.1A' and year<=2019:return 'verify_scope1_2'
    if c=='C10.1B' and year<=2019:return 'verify_scope3'
    if c=='C12.2':return 'supplier_requirements_status'
    for kind,codes in types.items():
        if c in codes:return kind
    summary={'CC3.1':'target_status','C4.1':'target_status','7.53':'target_status','20.16':'target_status',
             'C4.2':'other_target_status','7.54':'other_target_status','CC3.3':'initiative_status','C4.3':'initiative_status','7.55':'initiative_status','20.17':'initiative_status',
             'CC13.1':'pricing_status','C11.1':'pricing_status','3.5':'pricing_status','C11.1A':'pricing_systems','3.5.1':'pricing_systems',
             'CC13.2':'credit_status','C11.2':'credit_status','7.79':'credit_status','CC2.2C':'internal_price_status','C11.3':'internal_price_status','5.10':'internal_price_status',
             'CC14.4':'engagement_status','C12.1':'engagement_status','5.11':'engagement_status','18.3':'engagement_status'}
    return summary.get(c)


@lru_cache(maxsize=None)
def field_for(kind, header, code, year):
    t=label(header)
    if kind=='initiative' and year<2020 and t=='initiative type':return 'initiative_category'
    if code.upper()=='CC14.4C' and t.startswith('please explain why you do not engage'):return 'no_engagement_expl'
    if kind=='internal_price_status' and year>=2024:
        return pick(t,[(r'^use of internal pricing','internal_pricing_raw'),(r'^environmental externality priced$','externalities_priced'),(r'^primary reason','no_internal_price_reason'),(r'^explain why','no_internal_price_expl')])
    if kind=='target_status' and t.startswith('primary reason'):return 'no_target_reason'
    if kind=='target_status' and t=='please explain':return 'no_target_expl'
    if kind=='initiative_status' and t.startswith('primary reason'):return 'no_initiative_reason'
    if kind=='initiative':return pick(t,INITIATIVE_RULES)
    if kind=='initiative_stage':return pick(t,[(r'^stage of development','initiative_stage'),(r'^number of (?:initiatives|projects)','initiative_count'),(r'^(?:total )?estimated annual co2e savings','stage_est_savings_tco2e')])
    if kind=='investment_method':return pick(t,[(r'^method$','investment_method')])
    if kind in {'absolute_target','intensity_target','energy_target','other_target','net_zero_target','target_progress'}:return pick(t,TARGET_RULES)
    if kind=='no_target':return pick(t,[(r'^primary reason','no_target_reason'),(r'^five.year forecast','emissions_forecast'),(r'^please explain','no_target_expl')])
    if kind=='no_initiative':return 'no_initiative_reason'
    if kind.startswith('verify') or kind=='other_verification':return pick(t,VERIFY_RULES)
    if kind in {'ets','carbon_tax','carbon_credit','internal_price'}:
        if code.upper()=='CC2.2D':return 'price_details'
        return pick(t,PRICE_RULES)
    simple={'target_status':'target_status_raw','other_target_status':'other_targets_raw','initiative_status':'initiatives_active','pricing_status':'regulated_by_pricing','pricing_systems':'pricing_systems',
            'credit_status':'credit_activity_raw','internal_price_status':'internal_pricing_raw'}
    if kind in simple:return simple[kind]
    if kind=='supplier_requirements_status':return 'supplier_requirements'
    if kind in {'engagement_status','supplier_engagement','customer_engagement','supplier_assessment','supplier_requirements','client_engagement','investee_engagement','smallholder_engagement','other_engagement','supplier_coverage','supplier_data_use','no_engagement'}:
        if code.upper() in {'CC14.4','C12.1'}:return 'engagement_status'
        if code.upper() in {'CC14.4A','C12.1D'}:return 'engagement_details'
        if kind=='no_engagement':return 'no_engagement_expl'
        return pick(t,ENGAGE_RULES)
    return None


META=['record_id','year','cdp_account_number','company_name','primary_sector','primary_industry','currency','record_type','question_code','source_row','row_label']
FIELDS={
    'targets_performance': list(dict.fromkeys([f for _,f in TARGET_RULES+INITIATIVE_RULES]+['target_status_raw','other_targets_raw','initiatives_active','no_target_reason','no_target_expl','emissions_forecast','initiative_stage','initiative_count','stage_est_savings_tco2e','investment_method','no_initiative_reason'])),
    'verification': list(dict.fromkeys(['scope']+[f for _,f in VERIFY_RULES])),
    'carbon_pricing': list(dict.fromkeys([f for _,f in PRICE_RULES]+['regulated_by_pricing','pricing_systems','credit_activity_raw','internal_pricing_raw','price_details','externalities_priced','no_internal_price_reason','no_internal_price_expl'])),
    'engagement':list(dict.fromkeys([f for _,f in ENGAGE_RULES]+['climate_relevance'])),
}


def values(value):
    return value if isinstance(value,list) else [value]


def serialize(vs):
    return vs[0] if len(vs)==1 else json.dumps(vs,ensure_ascii=False,separators=(',',':'))


def build():
    OUT.mkdir(exist_ok=True)
    sample=base_sample()
    companies={}
    for r in sample:
        companies.setdefault((int(r['year']),key(r['cdp_account_number'])),r)
    audit=Counter();coverage=Counter();skips=Counter();field_counts=Counter();projection=Counter()
    streams={s:(OUT/f'cdp_{s}_2016_2025.csv.partial').open('w',encoding='utf-8',newline='') for s in FIELDS}
    writers={s:csv.DictWriter(streams[s],fieldnames=META+fs) for s,fs in FIELDS.items()}
    for w in writers.values():w.writeheader()
    line_path=OUT/'answer_provenance.jsonl.gz.partial'
    with gzip.open(line_path,'wt',encoding='utf-8',compresslevel=1) as lineage:
        for year in range(2016,2026):
            currency=json.loads((STAGE/f'{year}_currencies.json').read_text(encoding='utf-8'))
            seen=set()
            with ExitStack() as stack:
                paths=[STAGE/f'{year}.jsonl.gz']+list(STAGE.glob(f'{year}_supplement.jsonl.gz'))
                source=chain.from_iterable(stack.enter_context(gzip.open(p,'rt',encoding='utf-8')) for p in paths)
                for line in source:
                    r=json.loads(line);s=section(r['question_code']);kind=record_type(r['question_code'],year)
                    if not kind:skips[(year,s,'noncore_question')]+=1;continue
                    flat=[v for x in r['fields'].values() for v in values(x)]
                    if all(v.strip().lower() in {'question not applicable','not applicable','n/a',''} for v in flat):
                        skips[(year,s,'inapplicable_placeholder_only')]+=1;continue
                    if year>=2024 and s in {'engagement','carbon_pricing','risks_opportunities'}:
                        issues=' '.join([r['row_name']]+[str(v) for h,x in r['fields'].items() if label(h).startswith('environmental issue') for v in values(x)]).lower()
                        if any(x in issues for x in ['water','forest','biodiversity','plastic']) and not any(x in issues for x in ['climate','carbon']):
                            skips[(year,s,'explicit_nonclimate_environmental_issue')]+=1;continue
                    selected=defaultdict(list);origins=defaultdict(list)
                    for h,v in r['fields'].items():
                        f=field_for(kind,h,r['question_code'],year)
                        audit[(year,s,r['question_code'],h,f or '', 'retained' if f else 'excluded_noncore_field')]+=1
                        if f:
                            selected[f].extend(values(v));origins[f].append({'header':h,'answer':v})
                    if not selected:skips[(year,s,'no_selected_answers')]+=1;continue
                    assert all(len(v)==1 for v in origins.values()), (year,r['question_code'],origins.keys())
                    # Exact cross-file duplicate only, not distinct source rows.
                    signature=json.dumps([r['cdp_account_number'],r['question_code'],r['row_order'],r['row_name'],r['fields']],sort_keys=True,ensure_ascii=False)
                    sig=hashlib.sha256(signature.encode()).hexdigest()
                    if sig in seen:skips[(year,s,'exact_duplicate_source_record')]+=1;continue
                    seen.add(sig)
                    company=companies[year,r['cdp_account_number']]
                    rid=hashlib.sha256((str(year)+sig).encode()).hexdigest()[:24]
                    result=dict(record_id=rid,year=year,cdp_account_number=r['cdp_account_number'],company_name=company['cdp_org_name'],primary_sector=company.get('primary_sector',''),primary_industry=company.get('primary_industry',''),currency=currency.get(r['cdp_account_number'],''),record_type=kind,question_code=r['question_code'],source_row=r['row_order'],row_label=r['row_name'])
                    for f,vs in selected.items():
                        assert f in FIELDS[s],(s,f)
                        result[f]=serialize(vs);field_counts[s,f]+=1
                        # Keep a source-value fingerprint for post-write verification.
                        projection[s]+=len(vs)
                    if s=='verification':
                        c=r['question_code'].upper()
                        result['scope']=result.get('scope') or ('Scope 1' if kind=='verify_scope1' or c=='CC8.6' else 'Scope 2' if kind=='verify_scope2' or c=='CC8.7' else 'Scope 3' if kind=='verify_scope3' or c=='CC14.2' else r['row_name'])
                    if s=='engagement':
                        result['stakeholder']=result.get('stakeholder') or ({'supplier_engagement':'Suppliers','supplier_assessment':'Suppliers','supplier_requirements':'Suppliers','supplier_coverage':'Suppliers','supplier_data_use':'Suppliers','customer_engagement':'Customers','client_engagement':'Clients','investee_engagement':'Investees','smallholder_engagement':'Smallholders'}.get(kind,r['row_name']))
                        env=' '.join(selected.get('environmental_issues',[])+[r['row_name']]).lower()
                        result['climate_relevance']=('climate_questionnaire' if year<2024 else 'explicit_climate' if 'climate' in env else 'other_environmental_issue' if any(x in env for x in ['water','forest','biodiversity','plastic']) else 'environmental_unspecified')
                    if s=='risks_opportunities':
                        env=' '.join(selected.get('env_issue',[])+[r['row_name']]).lower()
                        result['climate_relevance']='climate_questionnaire' if year<2024 else 'explicit_climate' if 'climate' in env else 'environmental_unspecified'
                        result['questionnaire_pathway']='SME' if r['question_code'].startswith(('Q15.','Q16.')) else 'Full'
                        if year<2018 and kind in {'risk','opportunity','no_risk','no_opportunity'}:
                            result['legacy_category']={'a':'Regulation','d':'Regulation','b':'Physical climate','e':'Physical climate','c':'Other climate developments','f':'Other climate developments'}.get(r['question_code'][-1].lower(),'')
                    writers[s].writerow(result)
                    lineage.write(json.dumps(dict(record_id=rid,section=s,source_file=r['source_file'],source_sheet=r['source_sheet'],fields=origins),ensure_ascii=False)+'\n')
                    coverage[(year,r['cdp_account_number'],s,kind)]+=1
            print(f'{year}: curated {sum(v for k,v in coverage.items() if k[0]==year):,} records',flush=True)
    for stream in streams.values():stream.close()
    # Validate serialization and every selected answer using separate provenance.
    fingerprints={}
    csv.field_size_limit(100_000_000)
    output_counts={}
    for s in FIELDS:
        n=0
        with (OUT/f'cdp_{s}_2016_2025.csv.partial').open(encoding='utf-8',newline='') as stream:
            for row in csv.DictReader(stream):
                assert (int(row['year']),row['cdp_account_number']) in companies
                assert row['record_id'] not in fingerprints
                fingerprints[row['record_id']]={f:row[f] for f in FIELDS[s] if row[f]}
                n+=1
        output_counts[s]=n
    verified=Counter()
    with gzip.open(line_path,'rt',encoding='utf-8') as stream:
        for line in stream:
            item=json.loads(line)
            actual=fingerprints.pop(item['record_id'])
            for f,origins in item['fields'].items():
                vs=[v for o in origins for v in values(o['answer'])]
                assert actual[f]==serialize(vs),(item['record_id'],f)
                verified[item['section']]+=len(vs)
    assert not fingerprints and verified==projection
    for s in FIELDS:(OUT/f'cdp_{s}_2016_2025.csv.partial').replace(OUT/f'cdp_{s}_2016_2025.csv')
    line_path.replace(OUT/'answer_provenance.jsonl.gz')
    def save(name,header,data):
        with (OUT/name).open('w',encoding='utf-8',newline='') as stream:
            w=csv.writer(stream);w.writerow(header);w.writerows(data)
    save('field_selection_audit.csv',['year','section','question_code','source_header','short_name','decision','source_records'],[(*k,v) for k,v in sorted(audit.items())])
    save('record_coverage.csv',['year','cdp_account_number','section','record_type','records'],[(*k,v) for k,v in sorted(coverage.items())])
    save('excluded_records.csv',['year','section','reason','records'],[(*k,v) for k,v in sorted(skips.items())])
    totals=Counter()
    for (y,a,s,_),v in coverage.items():totals[y,a,s]+=v
    save('company_year_coverage.csv',['year','cdp_account_number','section','records'],[(y,a,s,totals[y,a,s]) for (y,a) in companies for s in FIELDS])
    link_cols=['year','cdp_account_number','factset_entity_id','trucost_company_id','lseg_isin','cdp_org_name']
    save('company_year_links.csv',link_cols,[[r.get(c,'') for c in link_cols] for r in sample])
    stats=dict(rows=output_counts,verified_source_answers=dict(verified),matched_company_years=len(sample),unique_cdp_company_years=len(companies))
    (OUT/'validation.json').write_text(json.dumps(stats,indent=2),encoding='utf-8')
    print(json.dumps(stats),flush=True)


if __name__=='__main__':build()

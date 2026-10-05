"""Curate climate risk, opportunity and assessment answers into a fifth dataset."""
import re
from functools import lru_cache
from . import build_cdp_section_datasets as common
from .extract_cdp_risk_opportunity import RISK_STAGE,risk_section

OUT=common.OUT
SUPPORT=OUT/'risk_opportunity_support'

ITEM_RULES=[
    (r'^environmental issue','env_issue'),
    (r'^(?:risk |opportunity )?identifier$','item_id'),
    (r'^(?:risk types? (?:and|&)|primary climate.related risk driver).*_g$|^risk type$','risk_type'),
    (r'^(?:opportunity type and|primary climate.related opportunity driver).*_g$|^opportunity type$','opp_type'),
    (r'^(?:climate )?risk type mapped','financial_risk_class'),
    (r'^risk types? (?:and|&)|^opportunity type and|^(?:primary climate.related )?(?:risk|opportunity) driver','driver'),
    (r'^value chain stage|^where in the value chain|^direct/ ?indirect','value_chain_stage'),
    (r'^country/area','country'),
    (r'^organization.?specific description|^organization specific description|^company. ?specific description|^description$','description'),
    (r'^% of portfolio value','portfolio_exposed_pct'),
    (r'^type of financial impact|^primary financial effect|^primary potential financial impact|^potential impact$','financial_effect_type'),
    (r'^time horizon|^timeframe','time_horizon'),
    (r'^likelihood','likelihood'),
    (r'^magnitude','magnitude'),
    (r'^are you able to (?:provide|quantify)','financial_estimate_status'),
    (r'^anticipated financial effect figure.*short.term.*minimum','future_st_min'),
    (r'^anticipated financial effect figure.*short.term.*maximum','future_st_max'),
    (r'^anticipated financial effect figure.*medium.term.*minimum','future_mt_min'),
    (r'^anticipated financial effect figure.*medium.term.*maximum','future_mt_max'),
    (r'^anticipated financial effect figure.*long.term.*minimum','future_lt_min'),
    (r'^anticipated financial effect figure.*long.term.*maximum','future_lt_max'),
    (r'^financial effect figure in the reporting year','current_fin_effect'),
    (r'^effect of the (?:risk|opportunity) on the financial','current_effect_desc'),
    (r'^anticipated effect of the (?:risk|opportunity)','future_effect_desc'),
    (r'^potential financial (?:impact|effect).*minimum','potential_fin_min'),
    (r'^potential financial (?:impact|effect).*maximum','potential_fin_max'),
    (r'^potential financial (?:impact|effect)','potential_fin_effect'),
    (r'^estimated financial implications','financial_effect_text'),
    (r'^explanation of financial','financial_effect_expl'),
    (r'^primary response','response_type'),
    (r'^description of response and explanation','response_cost_desc'),
    (r'^description of response|^management method|^strategy to realize','response_strategy'),
    (r'^cost of response|^cost to realize','response_cost'),
    (r'^explanation of cost','response_cost_expl'),
    (r'^comment$','comment'),
]
PROCESS_RULES=[
    (r'^environmental issue','env_issue'),
    (r'^process in place','is_risk_op_assessed'),
    (r'^risks and/or opportunities evaluated','process_scope'),
    (r'^indicate which of dependencies','process_covers'),
    (r'^value chain stage','assess_stages'),
    (r'^coverage$','assess_coverage'),
    (r'^supplier tiers','supplier_tiers'),
    (r'^type of assessment','assess_method'),
    (r'^frequency of (?:assessment|monitoring)','assess_frequency'),
    (r'^time horizon(?:s|\(s\)) covered|^how far into the future','assess_horizons'),
    (r'^risk management process|^integration of risk management','process_integration'),
    (r'^location.specificity','assess_location'),
    (r'^type of tools','tool_types'),
    (r'^tools and methods','assess_tools'),
    (r'^risk types and criteria','risk_types_criteria'),
    (r'^risk types considered','assess_risk_types'),
    (r'^criteria considered','assess_criteria'),
    (r'^partners and stakeholders','assess_stakeholders'),
    (r'^has this process changed','process_changed'),
    (r'^further details of process|^description of process|^please explain the process','assess_process'),
    (r'^to whom are results reported','reports_to'),
    (r'^geographical areas','assess_geography'),
    (r'^primary reason|^main reason','no_process_reason'),
    (r'^do you plan to introduce','process_plan'),
    (r'^is this process informed','process_dep_link'),
    (r'^explain why you do not have a process','process_link_expl'),
    (r'^explain why you do not evaluate','no_process_expl'),
    (r'^comment$','comment'),
]
STATUS_RULES=[
    (r'^environmental issue','env_issue'),
    (r'^environmental risks identified','risks_identified'),
    (r'^environmental opportunities identified','opps_identified'),
    (r'^primary reason','no_item_reason'),
    (r'^please explain','no_item_expl'),
]
HORIZON_RULES=[
    (r'^time horizon$','time_horizon'),
    (r'^from \(years\)','horizon_from_years'),
    (r'^to \(years\)','horizon_to_years'),
    (r'^is your long.term time horizon open ended','horizon_open_ended'),
    (r'^how this time horizon is linked','horizon_planning_link'),
    (r'^comment$','comment'),
]
EXTRA=['assess_process','risk_prioritization','risk_management','no_process_expl','risk_type_inclusion','risk_type_expl','materiality_def','risks_identified','opps_identified','no_item_reason','no_item_expl','response_cost','response_cost_text','climate_relevance','questionnaire_pathway','legacy_category']
FIELDS=list(dict.fromkeys([f for _,f in ITEM_RULES+PROCESS_RULES+STATUS_RULES+HORIZON_RULES]+EXTRA))

@lru_cache(None)
def record_type(code,year):
    c=code.upper().removeprefix('Q')
    if c.startswith(('CC5.1','CC6.1')):
        kind='risk' if c.startswith('CC5.') else 'opportunity'
        return kind+'_status' if c in {'CC5.1','CC6.1'} else kind if c[-1] in 'ABC' else 'no_'+kind if c[-1] in 'DEF' else None
    if year<2018:return {'CC2.1':'assessment_status','CC2.1A':'assessment','CC2.1B':'process_detail','CC2.1C':'prioritization','CC2.1D':'no_assessment'}.get(c)
    if c=='C2.1':return 'horizon' if year<2020 else 'assessment_status'
    if c=='C2.2':return 'assessment_status' if year<2020 else 'assessment'
    if c=='C2.2A':return 'assessment' if year<2020 else 'risk_type_assessed'
    if c=='C2.2C' and year<2020:return 'risk_type_assessed'
    return {
        'C2.1A':'horizon','C2.1B':'materiality','C2.2B':'process_detail','C2.2D':'risk_management','C2.2E':'no_assessment','C2.2G':'no_assessment',
        'C2.3':'risk_status','C2.3A':'risk','C2.3B':'no_risk','C2.4':'opportunity_status','C2.4A':'opportunity','C2.4B':'no_opportunity',
        '2.1':'horizon','2.2.1':'assessment_status','2.2.2':'assessment','15.1':'assessment_status',
        '3.1':'risk_status','3.1.1':'risk','16.1':'risk_status','16.1.1':'risk',
        '3.6':'opportunity_status','3.6.1':'opportunity','16.3':'opportunity_status','16.3.1':'opportunity',
    }.get(c)

@lru_cache(None)
def field_for(kind,header,code,year):
    t=common.label(header)
    if kind in {'risk','opportunity'}:
        if t=='cost of management':return 'response_cost_text' if year<2018 else 'response_cost'
        return common.pick(t,ITEM_RULES)
    if kind in {'risk_status','opportunity_status'}:
        if year<2024:return 'risks_identified' if kind=='risk_status' else 'opps_identified'
        return common.pick(t,STATUS_RULES)
    if kind in {'no_risk','no_opportunity'}:
        if year<2018:return 'no_item_expl'
        return common.pick(t,STATUS_RULES)
    if kind=='assessment_status' and year<2024:return 'is_risk_op_assessed'
    if kind in {'assessment','assessment_status','no_assessment'}:
        if kind=='no_assessment' and t in {'comment','please explain'}:return 'no_process_expl'
        return common.pick(t,PROCESS_RULES)
    if kind=='horizon':return common.pick(t,HORIZON_RULES)
    if kind=='risk_type_assessed':return common.pick(t,[(r'^relevance','risk_type_inclusion'),(r'^please explain','risk_type_expl')])
    return {'process_detail':'assess_process','prioritization':'risk_prioritization','risk_management':'risk_management','materiality':'materiality_def'}.get(kind)

def main():
    common.STAGE=RISK_STAGE
    common.OUT=SUPPORT
    common.FIELDS={'risks_opportunities':FIELDS}
    common.section=risk_section
    common.record_type=record_type
    common.field_for=field_for
    common.build()
    (SUPPORT/'cdp_risks_opportunities_2016_2025.csv').replace(OUT/'cdp_risks_opportunities_2016_2025.csv')

if __name__=='__main__':main()

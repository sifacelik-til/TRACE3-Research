# 2020 workbook extraction template

**Verified against the actual Excel headers. Review template only; no answer data extracted or overwritten.**

Use these five sheets as requested. `C2.4a` is the opportunity sheet; there is no extra dot after C.

| Source sheet | Content | Row unit |
|---|---|---|
| C2 - Risks and Opportunities | Process existence; substantive-impact definition; risk and opportunity identification | Company-year |
| C2.1a | Short-, medium-, long-term definitions | Company-year-horizon |
| C2.2 | Value-chain assessment coverage and processes | Company-year-process |
| C2.3a | All individual risk fields | Company-year-risk |
| C2.4a | All individual opportunity fields | Company-year-opportunity |

Common identifiers: `year`, `cdp_account_number`, `company_name`. Keep `row_order` and the source row label for alignment; `RowName` specifically becomes `horizon` in C2.1a. Preserve `country`, `primary_activity`, `primary_sector`, `primary_industry` and `questionnaire_sector` in company metadata.

`is_risk_op_assessed` is derived from the explicit C2.1 Yes/No answer (1/0; missing stays missing). Its meaning is a process exists. `risk_op_process_raw` keeps the original answer. `has_climate_risk` can similarly be derived from C2.3. Preserve all C2.4 opportunity response variants rather than turning “Yes, but unable to realize” into No.

Keep a separate row for each risk/opportunity. Multiselect cells contain only selected answer strings. No source metadata is embedded in answer values, and no 65% missingness filter is applied at the extraction/template stage.

## C2 - Risks and Opportunities

| Actual field / meaning | Short name |
|---|---|
| Does your organization have a process for identifying, assessing, and responding to climate-related risks and opportunities? | `risk_op_process_raw` |
| How does your organization define substantive financial or strategic impact on your business? | `materiality_def` |
| Have you identified any inherent climate-related risks with the potential to have a substantive financial or strategic impact on your business? | `climate_risk_raw` |
| Have you identified any climate-related opportunities with the potential to have a substantive financial or strategic impact on your business? | `climate_opp_raw` |

## C2.1a

| Actual field / meaning | Short name |
|---|---|
| RowName | `horizon` |
| From (years) | `horizon_from_yrs` |
| To (years) | `horizon_to_yrs` |
| Comment | `horizon_comment` |

Three fixed rows: Short-term, Medium-term, Long-term. Do not drop RowName; it identifies which definition the values belong to.

## C2.2

| Actual field / meaning | Short name |
|---|---|
| Value chain stage(s) covered | `assess_stages` |
| Risk management process | `process_type` |
| Frequency of assessment | `assess_freq` |
| Time horizon(s) covered | `assess_horizons` |
| Description of process | `assess_process` |

Only asked when C2.1=Yes. `assess_stages` contains Direct operations / Upstream / Downstream. Optional `assess_direct`, `assess_upstream`, `assess_downstream` indicators can be derived from a complete applicable response.

## C2.3a

| Actual field / meaning | Short name |
|---|---|
| Identifier | `risk_id` |
| Where in the value chain does the risk driver occur? | `risk_stage` |
| Risk type & Primary climate-related risk driver | `risk_driver` |
| Risk type & Primary climate-related risk driver_G | `risk_type` |
| Primary potential financial impact | `fin_impact_type` |
| Climate risk type mapped to traditional financial services industry risk classification | `risk_fs_class` |
| Company-specific description | `risk_desc` |
| Time horizon | `risk_horizon` |
| Likelihood | `risk_likelihood` |
| Magnitude of impact | `risk_magnitude` |
| Are you able to provide a potential financial impact figure? | `fin_estimate_type` |
| Potential financial impact figure (currency) | `fin_impact` |
| Potential financial impact figure – minimum (currency) | `fin_impact_min` |
| Potential financial impact figure – maximum (currency) | `fin_impact_max` |
| Explanation of financial impact figure | `fin_impact_expl` |
| Cost of response to risk | `response_cost` |
| Description of response and explanation of cost calculation | `response_and_cost_expl` |
| Comment | `risk_comment` |

Only asked when C2.3=Yes. The `_G` driver column is `risk_type`; the unsuffixed companion is `risk_driver`. This was verified against actual values. Preserve the combined response-and-cost narrative as one field.

## C2.4a

| Actual field / meaning | Short name |
|---|---|
| Identifier | `opp_id` |
| Where in the value chain does the opportunity occur? | `opp_stage` |
| Opportunity type | `opp_type` |
| Primary climate-related opportunity driver | `opp_driver` |
| Primary potential financial impact | `opp_fin_type` |
| Company-specific description | `opp_desc` |
| Time horizon | `opp_horizon` |
| Likelihood | `opp_likelihood` |
| Magnitude of impact | `opp_magnitude` |
| Are you able to provide a potential financial impact figure? | `opp_fin_estimate_type` |
| Potential financial impact figure (currency) | `opp_fin_impact` |
| Potential financial impact figure – minimum (currency) | `opp_fin_min` |
| Potential financial impact figure – maximum (currency) | `opp_fin_max` |
| Explanation of financial impact figure | `opp_fin_expl` |
| Cost to realize opportunity | `opp_cost` |
| Strategy to realize opportunity and explanation of cost calculation | `opp_strategy_cost_expl` |
| Comment | `opp_comment` |

Only asked when C2.4=Yes. The separate “Yes, but unable to realize” option does not trigger this detail table.

## Additional sheets from the earlier risk request

`C2.2a` provides risk-type relevance/inclusion, with the risk type stored in RowName. `C2.2g` provides the no-process reason and explanation when C2.1=No. `C2.3b` provides the no-risk reason and explanation when C2.3=No. These remain in the wider risk template; the five sheets alone would omit those answers.

The companion `verified_workbook_column_mapping.csv` contains exact source header strings for all eight checked sheets, including the group suffix and source encoding artifacts, so an implementation can match them without guessing.

The year-by-year questionnaire equivalents and full risk templates for 2016-2025 are in the parent README and annual folders. The 2020 opportunity sheet is included here following the clarified example; the full opportunity review across years is the next step.

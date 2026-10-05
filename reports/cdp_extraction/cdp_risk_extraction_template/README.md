**Populated risk and opportunity data are now available:** [dataset, updated mappings and annual templates](<C:/Users/scelik/OneDrive - Tilburg University/TRACE3Code/reports/cdp_extraction/cdp_section_extraction_templates/risks_opportunities/README.md>). The review draft below is retained as historical context.

# CDP risk extraction template: 2016-2025

**Draft for review. This task has not changed the datasets or production extraction code.**

**Clarified workbook scope:** use `C2 - Risks and Opportunities`, `C2.1a`, `C2.2`, `C2.3a`, and `C2.4a` as the 2020 example. The last code is C2.4a, without an extra dot after C. Read question columns inside overview sheets as well as dedicated question sheets. The 2020 and 2021 overview sheets were inspected and contain C2.1, C2.1b, C2.3 and C2.4. The 2020 template is checked against actual workbook headers. Time-horizon definitions are now included across years, and the requested 2020 C2.4a opportunity example is included. The earlier requested C2.2a, C2.2g and C2.3b remain in the risk review as well.

Use `is_risk_op_assessed` rather than `is_risk&op_assessed` for compatibility with Python, SQL and statistical software. Its precise meaning is **an assessment/management process exists**, not that assessment was completed. `risk_op_process_raw` retains the original answer; `has_climate_risk` separately records substantive risk identification.

## Proposed structure

| Table | One row per | Content |
|---|---|---|
| company | Company-year-pathway | Process existence, risk existence, no-process/no-risk reasons |
| process | Company-year and process row | Assessment coverage, frequency, horizons and details |
| risk_type | Company-year and risk-type row (2018-2023) | Relevance/inclusion and explanation |
| risk | Company-year and individual risk | All risk details, financial impacts and responses |

Keys are `year`, `cdp_account_number`, `questionnaire_pathway`, and for repeating tables `question_code` and `row_order`. Keep `risk_id` when supplied; legacy risk categories use question code plus row order. A company-year view can be generated later, but keeping one row per risk prevents mixing one risk's driver with another risk's cost. All supplied CSV templates contain headers only, not invented observations.

Answer cells contain only answers; multiselect answers use JSON string lists. Original labels, source paths and cell-status flags belong in a separate provenance export. A missing member of a repeated risk record must not shift the alignment of other fields.

## Decisions that prevent incorrect cross-year comparisons

- **2018-2019 C2.1 is about time horizons.** The process-existence question is C2.2. From 2020-2023 the process question becomes C2.1.

- Assessment coverage (`assess_stages`) differs from the location of a disclosed risk (`risk_stage`). Structured direct/upstream/downstream assessment-stage coverage starts in 2020. The 2018-2019 Upstream/Downstream assessment rows are not the same question.

- For 2024-2025, process existence is environmental, not necessarily climate-specific. Keep `process_scope`, and use 2.2.2 rows including Climate change and Risks. An opportunities-only process does not establish climate-risk assessment.

- Preserve the six relevance/inclusion categories in 2018-2023. Do not replace them with a yes/no flag. In 2024 types are multiselect; in 2025 types and criteria are combined grouped selections.

- Preserve original category labels: Supply chain/Customer/Investment chain in older years are not silently relabeled as Upstream/Downstream. Keep any harmonized categories as separate derived fields.

- Keep legacy financial/cost narratives as text. From 2019, retain point estimates, ranges and no-estimate status separately. In 2024-2025 distinguish reporting-year effects from short/medium/long-term anticipated effects. Join the organization's reporting currency before comparing amounts.

- The 65% missingness filter from the earlier panel is **not applied to this review template**. Structural absence and conditional branches should not erase requested questions.

- Distinguish not asked that year, branch skipped, source not provided, unanswered, and explicit No. Only explicit answers can produce 0/1 indicators. Do not infer No from absence of a detailed risk table.

- Financial-services-only columns inside the requested risk tables are retained. Additional portfolio-assessment question families are outside this core scope. SME questions are documented separately for 2024-2025.

## Year-by-year question map

| Year | Process exists | Assessment details/types | No process | Risks exist | Individual risks | No risk |
|---|---|---|---|---|---|---|
| 2016 | CC2.1 | CC2.1a-c | CC2.1d | CC5.1 | CC5.1a/b/c | CC5.1 category branch |
| 2017 | CC2.1 | CC2.1a-c | CC2.1d | CC5.1 | CC5.1a/b/c | CC5.1 category branch |
| 2018 | C2.2 | C2.2a-d; types C2.2c | C2.2e | C2.3 | C2.3a | C2.3b |
| 2019 | C2.2 | C2.2a-d; types C2.2c | C2.2e | C2.3 | C2.3a | C2.3b |
| 2020 | C2.1 | C2.2; types C2.2a | C2.2g | C2.3 | C2.3a | C2.3b |
| 2021 | C2.1 | C2.2; types C2.2a | C2.2g | C2.3 | C2.3a | C2.3b |
| 2022 | C2.1 | C2.2; types C2.2a | C2.2g | C2.3 | C2.3a | C2.3b |
| 2023 | C2.1 | C2.2; types C2.2a | C2.2g | C2.3 | C2.3a | C2.3b |
| 2024 | 2.2.1 | 2.2.2 | 2.2.1 same table | 3.1 | 3.1.1 | 3.1 same table |
| 2025 | 2.2.1 | 2.2.2 | 2.2.1 same table | 3.1 | 3.1.1 | 3.1 same table |

## Main dependencies and response choices

**2020-2023:** C2.1=Yes enables C2.2/C2.2a; C2.1=No enables C2.2g. Independently, C2.3=Yes enables C2.3a; C2.3=No enables C2.3b. Do not gate risk existence on process existence.

**2018-2019:** integrated/dedicated process in C2.2 enables C2.2a-d; no documented process enables C2.2e. **2016-2017:** CC2.1 governs CC2.1a-c versus CC2.1d; CC5.1 categories govern their risk/no-risk branches.

**2024-2025 full:** a process in either 2.2 or 2.2.1 enables 2.2.2. Its presence alone does not prove risk assessment; filter Climate change and Risks. Any Yes option in 3.1 enables 3.1.1, with a Climate change row filter. SME uses 16.1 -> 16.1.1.

**Assessment stages (2020-2023):** Direct operations, Upstream, Downstream. The 2022-2023 questionnaire hides Downstream assessment coverage for financial services. `assess_direct`, `assess_upstream`, `assess_downstream` are nullable derived indicators. Selected=1; not selected=0 only when a complete answer is present and the option applies. Otherwise blank.

**Assessment risk types (2018-2023):** Current regulation; Emerging regulation; Technology; Legal; Market; Reputation; Acute physical; Chronic physical. 2018-2019 additionally include Upstream and Downstream rows.

**Risk-type inclusion options:** Relevant, always included; Relevant, sometimes included; Relevant, not included; Not relevant, included; Not relevant, explanation provided; Not evaluated.

**2024-2025 risk-type groups:** Acute physical; Chronic physical; Policy; Market; Reputation; Technology; Liability. These groups do not reproduce the old Current/Emerging regulation distinction.

**Financial estimate availability (2019-2023):** Yes, a single figure estimate; Yes, an estimated range; No, we do not have this figure. Missing estimates remain blank, never zero.

## Full annual question and field templates

### 2016

**FULL questionnaire.** Source: [2016 Climate Change Questionnaire.pdf](<C:/Users/scelik/OneDrive - Tilburg University/TRACE3Code/data/raw/CDP/CDP Questionnaires/2016 Climate Change Questionnaire.pdf>). Page references are 1-based PDF pages, including the cover.

**CC2.1 — Please select the option that best describes your risk management procedures with regard to climate change risks and opportunities** (PDF p. 4)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_op_process_raw` | Risk management procedures | category |
| `is_risk_op_assessed` | Derived from explicit process-existence answer | nullable boolean |

**CC2.1a — Please provide further details on your risk management procedures with regard to climate change risks and opportunities** (PDF p. 4)

Dependency: CC2.1 = integrated company-wide process or dedicated climate-change process.

| Short name | Source field / meaning | Type |
|---|---|---|
| `assess_freq` | Frequency of monitoring | category |
| `reports_to` | To whom are results reported? | category |
| `assess_geography` | Geographical areas considered | text |
| `assess_horizon_raw` | How far into the future are risks considered? | category |
| `process_comment` | Comment | text |

**CC2.1b — Please describe how your risk and opportunity identification processes are applied at both company and asset level** (PDF p. 4)

Dependency: CC2.1 = integrated company-wide process or dedicated climate-change process.

| Short name | Source field / meaning | Type |
|---|---|---|
| `assess_process` | Processes applied at company and asset level | text |

**CC2.1c — How do you prioritize the risks and opportunities identified?** (PDF p. 4)

Dependency: CC2.1 = integrated company-wide process or dedicated climate-change process.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_prioritization` | How risks and opportunities are prioritized | text |

**CC2.1d — Please explain why you do not have a process in place for assessing and managing risks and opportunities from climate change, and whether you plan to introduce such a process in the future** (PDF p. 4)

Dependency: CC2.1 = no documented process.

| Short name | Source field / meaning | Type |
|---|---|---|
| `no_process_reason` | Main reason for not having a process | category |
| `process_plan` | Do you plan to introduce a process? | category |
| `no_process_expl` | Comment | text |

**CC5.1 — Have you identified any inherent climate change risks that have the potential to generate a substantive change in your business operations, revenue or expenditure? (Tick all that apply)** (PDF p. 9)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_categories` | Relevant risk categories | multiselect |
| `has_climate_risk` | Derived from explicit risk-category response | nullable boolean |

**CC5.1a — Please describe your inherent risks that are driven by changes in regulation.** (PDF p. 9)

Dependency: CC5.1 identifies risks in category: regulation.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_driver` | Risk driver | category |
| `risk_desc` | Description | text |
| `fin_impact_type` | Potential impact | category |
| `risk_horizon` | Timeframe | category |
| `risk_stage_raw` | Direct/Indirect | category |
| `risk_likelihood` | Likelihood | category |
| `risk_magnitude` | Magnitude of impact | category |
| `fin_impact_text` | Estimated financial implications | text |
| `risk_response` | Management method | text |
| `response_cost_text` | Cost of management | text |

Category=regulation; risk key=question_code+row_order. Finance/cost source values may be narratives.

**CC5.1b — Please describe your inherent risks that are driven by changes in physical climate parameters.** (PDF p. 9)

Dependency: CC5.1 identifies risks in category: physical climate.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_driver` | Risk driver | category |
| `risk_desc` | Description | text |
| `fin_impact_type` | Potential impact | category |
| `risk_horizon` | Timeframe | category |
| `risk_stage_raw` | Direct/Indirect | category |
| `risk_likelihood` | Likelihood | category |
| `risk_magnitude` | Magnitude of impact | category |
| `fin_impact_text` | Estimated financial implications | text |
| `risk_response` | Management method | text |
| `response_cost_text` | Cost of management | text |

Category=physical climate; risk key=question_code+row_order. Finance/cost source values may be narratives.

**CC5.1c — Please describe your inherent risks that are driven by changes in other climate-related developments.** (PDF p. 9)

Dependency: CC5.1 identifies risks in category: other climate developments.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_driver` | Risk driver | category |
| `risk_desc` | Description | text |
| `fin_impact_type` | Potential impact | category |
| `risk_horizon` | Timeframe | category |
| `risk_stage_raw` | Direct/Indirect | category |
| `risk_likelihood` | Likelihood | category |
| `risk_magnitude` | Magnitude of impact | category |
| `fin_impact_text` | Estimated financial implications | text |
| `risk_response` | Management method | text |
| `response_cost_text` | Cost of management | text |

Category=other climate developments; risk key=question_code+row_order. Finance/cost source values may be narratives.

**CC5.1_no_risk — Please explain why you do not consider your organization to be exposed to these risks that have the potential to generate a substantive change in your business operations, revenue or expenditure.** (PDF p. 9)

Dependency: Risk category not identified in CC5.1.

| Short name | Source field / meaning | Type |
|---|---|---|
| `no_risk_expl` | Explanation for a category without identified inherent risk | text |

Descriptive branch label, not a verified questionnaire subcode. Do not invent CC5.1d/e/f.

### 2017

**FULL questionnaire.** Source: [2017 Climate Change Questionnaire.pdf](<C:/Users/scelik/OneDrive - Tilburg University/TRACE3Code/data/raw/CDP/CDP Questionnaires/2017 Climate Change Questionnaire.pdf>). Page references are 1-based PDF pages, including the cover.

**CC2.1 — Please select the option that best describes your risk management procedures with regard to climate change risks and opportunities** (PDF p. 3)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_op_process_raw` | Risk management procedures | category |
| `is_risk_op_assessed` | Derived from explicit process-existence answer | nullable boolean |

**CC2.1a — Please provide further details on your risk management procedures with regard to climate change risks and opportunities** (PDF p. 3)

Dependency: CC2.1 = integrated company-wide process or dedicated climate-change process.

| Short name | Source field / meaning | Type |
|---|---|---|
| `assess_freq` | Frequency of monitoring | category |
| `reports_to` | To whom are results reported? | category |
| `assess_geography` | Geographical areas considered | text |
| `assess_horizon_raw` | How far into the future are risks considered? | category |
| `process_comment` | Comment | text |

**CC2.1b — Please describe how your risk and opportunity identification processes are applied at both company and asset level** (PDF p. 3)

Dependency: CC2.1 = integrated company-wide process or dedicated climate-change process.

| Short name | Source field / meaning | Type |
|---|---|---|
| `assess_process` | Processes applied at company and asset level | text |

**CC2.1c — How do you prioritize the risks and opportunities identified?** (PDF p. 3)

Dependency: CC2.1 = integrated company-wide process or dedicated climate-change process.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_prioritization` | How risks and opportunities are prioritized | text |

**CC2.1d — Please explain why you do not have a process in place for assessing and managing risks and opportunities from climate change, and whether you plan to introduce such a process in the future** (PDF p. 3)

Dependency: CC2.1 = no documented process.

| Short name | Source field / meaning | Type |
|---|---|---|
| `no_process_reason` | Main reason for not having a process | category |
| `process_plan` | Do you plan to introduce a process? | category |
| `no_process_expl` | Comment | text |

**CC5.1 — Have you identified any inherent climate change risks that have the potential to generate a substantive change in your business operations, revenue or expenditure? (Tick all that apply)** (PDF p. 8)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_categories` | Relevant risk categories | multiselect |
| `has_climate_risk` | Derived from explicit risk-category response | nullable boolean |

**CC5.1a — Please describe your inherent risks that are driven by changes in regulation.** (PDF p. 8)

Dependency: CC5.1 identifies risks in category: regulation.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_driver` | Risk driver | category |
| `risk_desc` | Description | text |
| `fin_impact_type` | Potential impact | category |
| `risk_horizon` | Timeframe | category |
| `risk_stage_raw` | Direct/Indirect | category |
| `risk_likelihood` | Likelihood | category |
| `risk_magnitude` | Magnitude of impact | category |
| `fin_impact_text` | Estimated financial implications | text |
| `risk_response` | Management method | text |
| `response_cost_text` | Cost of management | text |

Category=regulation; risk key=question_code+row_order. Finance/cost source values may be narratives.

**CC5.1b — Please describe your inherent risks that are driven by changes in physical climate parameters.** (PDF p. 8)

Dependency: CC5.1 identifies risks in category: physical climate.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_driver` | Risk driver | category |
| `risk_desc` | Description | text |
| `fin_impact_type` | Potential impact | category |
| `risk_horizon` | Timeframe | category |
| `risk_stage_raw` | Direct/Indirect | category |
| `risk_likelihood` | Likelihood | category |
| `risk_magnitude` | Magnitude of impact | category |
| `fin_impact_text` | Estimated financial implications | text |
| `risk_response` | Management method | text |
| `response_cost_text` | Cost of management | text |

Category=physical climate; risk key=question_code+row_order. Finance/cost source values may be narratives.

**CC5.1c — Please describe your inherent risks that are driven by changes in other climate-related developments.** (PDF p. 8)

Dependency: CC5.1 identifies risks in category: other climate developments.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_driver` | Risk driver | category |
| `risk_desc` | Description | text |
| `fin_impact_type` | Potential impact | category |
| `risk_horizon` | Timeframe | category |
| `risk_stage_raw` | Direct/Indirect | category |
| `risk_likelihood` | Likelihood | category |
| `risk_magnitude` | Magnitude of impact | category |
| `fin_impact_text` | Estimated financial implications | text |
| `risk_response` | Management method | text |
| `response_cost_text` | Cost of management | text |

Category=other climate developments; risk key=question_code+row_order. Finance/cost source values may be narratives.

**CC5.1_no_risk — Please explain why you do not consider your organization to be exposed to these risks that have the potential to generate a substantive change in your business operations, revenue or expenditure.** (PDF p. 8)

Dependency: Risk category not identified in CC5.1.

| Short name | Source field / meaning | Type |
|---|---|---|
| `no_risk_expl` | Explanation for a category without identified inherent risk | text |

Descriptive branch label, not a verified questionnaire subcode. Do not invent CC5.1d/e/f.

### 2018

**FULL questionnaire.** Source: [2018 Climate Change Questionnaire.pdf](<C:/Users/scelik/OneDrive - Tilburg University/TRACE3Code/data/raw/CDP/CDP Questionnaires/2018 Climate Change Questionnaire.pdf>). Page references are 1-based PDF pages, including the cover.

**C2.2 — Select the option that best describes how your organization's processes for identifying, assessing, and managing climate-related issues are integrated into your overall risk management.** (PDF p. 28)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_op_process_raw` | Process integration option | category |
| `is_risk_op_assessed` | Derived from explicit process-existence answer | nullable boolean |

**C2.2a — Select the options that best describe your organization's frequency and time horizon for identifying, and assessing climate-related risks.** (PDF p. 29)

Dependency: C2.2 = integrated company-wide process or dedicated climate-change process.

| Short name | Source field / meaning | Type |
|---|---|---|
| `assess_freq` | Frequency of monitoring | category |
| `assess_horizon_raw` | How far into the future are risks considered? | category |
| `process_comment` | Comment | text |

**C2.2b — Provide further details on your organization’s process(es) for identifying and assessing climate-related risks.** (PDF p. 29)

Dependency: C2.2 = integrated company-wide process or dedicated climate-change process.

| Short name | Source field / meaning | Type |
|---|---|---|
| `assess_process` | Risk identification and assessment process | text |

**C2.2d — Describe your process(es) for managing climate-related risks and opportunities.** (PDF p. 30)

Dependency: C2.2 = integrated company-wide process or dedicated climate-change process.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_management` | Risk/opportunity management process | text |

**C2.2c — Which of the following risk types are considered in your organization's climate-related risk assessments?** (PDF p. 29)

Dependency: C2.2 = integrated company-wide process or dedicated climate-change process.

| Short name | Source field / meaning | Type |
|---|---|---|
| `assess_risk_type` | Risk type (fixed row label) | category |
| `risk_type_inclusion` | Relevance & inclusion | category |
| `risk_type_expl` | Please explain | text |

Eight climate-risk types; 2018-2019 additionally have Upstream and Downstream rows. Preserve all six relevance/inclusion choices, not a binary flag.

**C2.2e — Why does your organization not have a process in place for identifying, assessing, and managing climate-related risks and opportunities, and do you plan to introduce such a process in the future?** (PDF p. 31)

Dependency: C2.2 = no documented process.

| Short name | Source field / meaning | Type |
|---|---|---|
| `no_process_reason` | Primary reason | category |
| `no_process_expl` | Please explain | text |

The plan to introduce a process in two years is a reason option, not a separate observed plan column.

**C2.3 — Have you identified any inherent climate-related risks with the potential to have a substantive financial or strategic impact on your business?** (PDF p. 31)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `climate_risk_raw` | Inherent climate-related risks identified | yes/no |
| `has_climate_risk` | Derived from explicit Yes/No | nullable boolean |

Not conditional on process existence.

**C2.3a — Provide details of risks identified with the potential to have a substantive financial or strategic impact on your business.** (PDF p. 32)

Dependency: C2.3 = Yes.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_id` | Identifier | category |
| `risk_stage` | Where in the value chain does the risk driver occur? | category |
| `risk_type` | Risk type | category |
| `risk_driver` | Primary climate-related risk driver | category |
| `fin_impact_type` | Type of financial impact driver | category |
| `risk_desc` | Company-specific description | text |
| `risk_horizon` | Time horizon | category |
| `risk_likelihood` | Likelihood | category |
| `risk_magnitude` | Magnitude of impact | category |
| `fin_impact` | Potential financial impact | decimal |
| `fin_impact_expl` | Explanation of financial impact | text |
| `risk_response` | Management method | text |
| `response_cost` | Cost of management | decimal |
| `risk_comment` | Comment | text |

Stage: Direct operations/Supply chain/Customer. Risk type: Transition/Physical. Horizon includes Current.

**C2.3b — Why do you not consider your organization to be exposed to climate-related risks with the potential to have a substantive financial or strategic impact on your business?** (PDF p. 34)

Dependency: C2.3 = No.

| Short name | Source field / meaning | Type |
|---|---|---|
| `no_risk_reason` | Primary reason | category |
| `no_risk_expl` | Please explain | text |

**C2.1 — Describe what your organization considers to be short-, medium- and long-term horizons.** (PDF p. 28)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `horizon` | Time horizon | category |
| `horizon_from_yrs` | From (years) | integer |
| `horizon_to_yrs` | To (years) | integer |
| `horizon_comment` | Comment | text |

Required following the clarified sheet scope. Short-, medium-, and long-term fixed rows; preserve the organization-specific definitions.

### 2019

**FULL questionnaire.** Source: [2019 Climate Change Questionnaire.pdf](<C:/Users/scelik/OneDrive - Tilburg University/TRACE3Code/data/raw/CDP/CDP Questionnaires/2019 Climate Change Questionnaire.pdf>). Page references are 1-based PDF pages, including the cover.

**C2.2 — Select the option that best describes how your organization's processes for identifying, assessing, and managing climate-related issues are integrated into your overall risk management.** (PDF p. 31)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_op_process_raw` | Process integration option | category |
| `is_risk_op_assessed` | Derived from explicit process-existence answer | nullable boolean |

**C2.2a — Select the options that best describe your organization's frequency and time horizon for identifying, and assessing climate-related risks.** (PDF p. 32)

Dependency: C2.2 = integrated company-wide process or dedicated climate-change process.

| Short name | Source field / meaning | Type |
|---|---|---|
| `assess_freq` | Frequency of monitoring | category |
| `assess_horizon_raw` | How far into the future are risks considered? | category |
| `process_comment` | Comment | text |

**C2.2b — Provide further details on your organization’s process(es) for identifying and assessing climate-related risks.** (PDF p. 32)

Dependency: C2.2 = integrated company-wide process or dedicated climate-change process.

| Short name | Source field / meaning | Type |
|---|---|---|
| `assess_process` | Risk identification and assessment process | text |

**C2.2d — Describe your process(es) for managing climate-related risks and opportunities.** (PDF p. 33)

Dependency: C2.2 = integrated company-wide process or dedicated climate-change process.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_management` | Risk/opportunity management process | text |

**C2.2c — Which of the following risk types are considered in your organization's climate-related risk assessments?** (PDF p. 33)

Dependency: C2.2 = integrated company-wide process or dedicated climate-change process.

| Short name | Source field / meaning | Type |
|---|---|---|
| `assess_risk_type` | Risk type (fixed row label) | category |
| `risk_type_inclusion` | Relevance & inclusion | category |
| `risk_type_expl` | Please explain | text |

Eight climate-risk types; 2018-2019 additionally have Upstream and Downstream rows. Preserve all six relevance/inclusion choices, not a binary flag.

**C2.2e — Why does your organization not have a process in place for identifying, assessing, and managing climate-related risks and opportunities, and do you plan to introduce such a process in the future?** (PDF p. 34)

Dependency: C2.2 = no documented process.

| Short name | Source field / meaning | Type |
|---|---|---|
| `no_process_reason` | Primary reason | category |
| `no_process_expl` | Please explain | text |

The plan to introduce a process in two years is a reason option, not a separate observed plan column.

**C2.3 — Have you identified any inherent climate-related risks with the potential to have a substantive financial or strategic impact on your business?** (PDF p. 34)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `climate_risk_raw` | Inherent climate-related risks identified | yes/no |
| `has_climate_risk` | Derived from explicit Yes/No | nullable boolean |

Not conditional on process existence.

**C2.3a — Provide details of risks identified with the potential to have a substantive financial or strategic impact on your business.** (PDF p. 35)

Dependency: C2.3 = Yes.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_id` | Identifier | category |
| `risk_stage` | Where in the value chain does the risk driver occur? | category |
| `risk_type` | Risk type | category |
| `risk_driver` | Primary climate-related risk driver | category |
| `fin_impact_type` | Type of financial impact | category |
| `risk_desc` | Company-specific description | text |
| `risk_horizon` | Time horizon | category |
| `risk_likelihood` | Likelihood | category |
| `risk_magnitude` | Magnitude of impact | category |
| `fin_estimate_type` | Are you able to provide a potential financial impact figure? | category |
| `fin_impact` | Potential financial impact figure (currency) | decimal |
| `fin_impact_min` | Potential financial impact figure - minimum (currency) | decimal |
| `fin_impact_max` | Potential financial impact figure - maximum (currency) | decimal |
| `fin_impact_expl` | Explanation of financial impact figure | text |
| `risk_response` | Management method | text |
| `response_cost` | Cost of management | decimal |
| `risk_comment` | Comment | text |

Adds Investment chain to stage choices; Transition/Physical type; horizon includes Current.

**C2.3b — Why do you not consider your organization to be exposed to climate-related risks with the potential to have a substantive financial or strategic impact on your business?** (PDF p. 38)

Dependency: C2.3 = No.

| Short name | Source field / meaning | Type |
|---|---|---|
| `no_risk_reason` | Primary reason | category |
| `no_risk_expl` | Please explain | text |

**C2.1 — Describe what your organization considers to be short-, medium- and long-term horizons.** (PDF p. 31)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `horizon` | Time horizon | category |
| `horizon_from_yrs` | From (years) | integer |
| `horizon_to_yrs` | To (years) | integer |
| `horizon_comment` | Comment | text |

Required following the clarified sheet scope. Short-, medium-, and long-term fixed rows; preserve the organization-specific definitions.

### 2020

**FULL questionnaire.** Source: [2020 Climate Change Questionnaire.pdf](<C:/Users/scelik/OneDrive - Tilburg University/TRACE3Code/data/raw/CDP/CDP Questionnaires/2020 Climate Change Questionnaire.pdf>). Page references are 1-based PDF pages, including the cover.

**C2.1 — Does your organization have a process for identifying, assessing, and responding to climate-related risks and opportunities?** (PDF p. 26)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_op_process_raw` | Does the organization have a process? | yes/no |
| `is_risk_op_assessed` | Derived from explicit Yes/No | nullable boolean |

**C2.2 — Describe your process(es) for identifying, assessing and responding to climate-related risks and opportunities.** (PDF p. 26)

Dependency: C2.1 = Yes.

| Short name | Source field / meaning | Type |
|---|---|---|
| `assess_stages` | Value chain stage(s) covered | multiselect |
| `process_type` | Risk management process | category |
| `assess_freq` | Frequency of assessment | category |
| `assess_horizons` | Time horizon(s) covered | multiselect |
| `assess_process` | Description of process | text |
| `assess_direct` | Derived membership of Direct operations in assessment stages | nullable boolean |
| `assess_upstream` | Derived membership of Upstream in assessment stages | nullable boolean |
| `assess_downstream` | Derived membership of Downstream in assessment stages | nullable boolean |

1 if selected; 0 only for an applicable, complete, nonblank response not selecting it; otherwise blank. Hidden FS Downstream is not 0.

**C2.2a — Which risk types are considered in your organization's climate-related risk assessments?** (PDF p. 27)

Dependency: C2.1 = Yes.

| Short name | Source field / meaning | Type |
|---|---|---|
| `assess_risk_type` | Risk type (fixed row label) | category |
| `risk_type_inclusion` | Relevance & inclusion | category |
| `risk_type_expl` | Please explain | text |

Eight climate-risk types; 2018-2019 additionally have Upstream and Downstream rows. Preserve all six relevance/inclusion choices, not a binary flag.

**C2.2g — Why does your organization not have a process in place for identifying, assessing, and responding to climate-related risks and opportunities, and do you plan to introduce such a process in the future?** (PDF p. 31)

Dependency: C2.1 = No.

| Short name | Source field / meaning | Type |
|---|---|---|
| `no_process_reason` | Primary reason | category |
| `no_process_expl` | Please explain | text |

The plan to introduce a process in two years is a reason option, not a separate observed plan column.

**C2.3 — Have you identified any inherent climate-related risks with the potential to have a substantive financial or strategic impact on your business?** (PDF p. 31)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `climate_risk_raw` | Inherent climate-related risks identified | yes/no |
| `has_climate_risk` | Derived from explicit Yes/No | nullable boolean |

Not conditional on process existence.

**C2.3a — Provide details of risks identified with the potential to have a substantive financial or strategic impact on your business.** (PDF p. 31)

Dependency: C2.3 = Yes.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_id` | Identifier | category |
| `risk_stage` | Where in the value chain does the risk driver occur? | category |
| `risk_type` | Risk type | category |
| `risk_driver` | Primary climate-related risk driver | category |
| `fin_impact_type` | Primary potential financial impact | category |
| `risk_fs_class` | Climate risk type mapped to traditional financial services industry risk classification | category; FS only |
| `risk_desc` | Company-specific description | text |
| `risk_horizon` | Time horizon | category |
| `risk_likelihood` | Likelihood | category |
| `risk_magnitude` | Magnitude of impact | category |
| `fin_estimate_type` | Are you able to provide a potential financial impact figure? | category |
| `fin_impact` | Potential financial impact figure (currency) | decimal |
| `fin_impact_min` | Potential financial impact figure - minimum (currency) | decimal |
| `fin_impact_max` | Potential financial impact figure - maximum (currency) | decimal |
| `fin_impact_expl` | Explanation of financial impact figure | text |
| `response_cost` | Cost of response to risk | decimal |
| `response_and_cost_expl` | Description of response and explanation of cost calculation | text |
| `risk_comment` | Comment | text |

Eight risk types; Direct operations/Upstream/Downstream; no Current horizon option.

**C2.3b — Why do you not consider your organization to be exposed to climate-related risks with the potential to have a substantive financial or strategic impact on your business?** (PDF p. 33)

Dependency: C2.3 = No.

| Short name | Source field / meaning | Type |
|---|---|---|
| `no_risk_reason` | Primary reason | category |
| `no_risk_expl` | Please explain | text |

**C2.1a — How does your organization define short-, medium- and long-term time horizons?** (PDF p. 26)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `horizon` | Time horizon | category |
| `horizon_from_yrs` | From (years) | integer |
| `horizon_to_yrs` | To (years) | integer |
| `horizon_comment` | Comment | text |

Required following the clarified sheet scope. Short-, medium-, and long-term fixed rows; preserve the organization-specific definitions.

**C2.1b — How does your organization define substantive financial or strategic impact on your business?** (PDF p. 26)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `materiality_def` | Definition of substantive financial or strategic impact | text |

Top-level answer may be stored in the C2 - Risks and Opportunities overview sheet.

**C2.4 — Have you identified any climate-related opportunities with the potential to have a substantive financial or strategic impact on your business?** (PDF p. 34)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `climate_opp_raw` | Climate-related opportunities identified | category |

Keep original Yes / Yes but unable to realize / No variants. Overview-sheet column.

**C2.4a — Provide details of opportunities identified with the potential to have a substantive financial or strategic impact on your business.** (PDF p. 34)

Dependency: C2.4 = Yes (not the separate Yes, but unable to realize option).

| Short name | Source field / meaning | Type |
|---|---|---|
| `opp_id` | Identifier | category |
| `opp_stage` | Where in the value chain does the opportunity occur? | category |
| `opp_type` | Opportunity type | category |
| `opp_driver` | Primary climate-related opportunity driver | category |
| `opp_fin_type` | Primary potential financial impact | category |
| `opp_desc` | Company-specific description | text |
| `opp_horizon` | Time horizon | category |
| `opp_likelihood` | Likelihood | category |
| `opp_magnitude` | Magnitude of impact | category |
| `opp_fin_estimate_type` | Are you able to provide a potential financial impact figure? | category |
| `opp_fin_impact` | Potential financial impact figure (currency) | decimal |
| `opp_fin_min` | Potential financial impact figure - minimum (currency) | decimal |
| `opp_fin_max` | Potential financial impact figure - maximum (currency) | decimal |
| `opp_fin_expl` | Explanation of financial impact figure | text |
| `opp_cost` | Cost to realize opportunity | decimal |
| `opp_strategy_cost_expl` | Strategy to realize opportunity and explanation of cost calculation | text |
| `opp_comment` | Comment | text |

Included as the requested 2020 sheet example; the full cross-year opportunity review follows risk-template approval.

### 2021

**FULL questionnaire.** Source: [2021 Climate Change Questionnaire.pdf](<C:/Users/scelik/OneDrive - Tilburg University/TRACE3Code/data/raw/CDP/CDP Questionnaires/2021 Climate Change Questionnaire.pdf>). Page references are 1-based PDF pages, including the cover.

**C2.1 — Does your organization have a process for identifying, assessing, and responding to climate-related risks and opportunities?** (PDF p. 13)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_op_process_raw` | Does the organization have a process? | yes/no |
| `is_risk_op_assessed` | Derived from explicit Yes/No | nullable boolean |

**C2.2 — Describe your process(es) for identifying, assessing and responding to climate-related risks and opportunities.** (PDF p. 13)

Dependency: C2.1 = Yes.

| Short name | Source field / meaning | Type |
|---|---|---|
| `assess_stages` | Value chain stage(s) covered | multiselect |
| `process_type` | Risk management process | category |
| `assess_freq` | Frequency of assessment | category |
| `assess_horizons` | Time horizon(s) covered | multiselect |
| `assess_process` | Description of process | text |
| `assess_direct` | Derived membership of Direct operations in assessment stages | nullable boolean |
| `assess_upstream` | Derived membership of Upstream in assessment stages | nullable boolean |
| `assess_downstream` | Derived membership of Downstream in assessment stages | nullable boolean |

1 if selected; 0 only for an applicable, complete, nonblank response not selecting it; otherwise blank. Hidden FS Downstream is not 0.

**C2.2a — Which risk types are considered in your organization's climate-related risk assessments?** (PDF p. 14)

Dependency: C2.1 = Yes.

| Short name | Source field / meaning | Type |
|---|---|---|
| `assess_risk_type` | Risk type (fixed row label) | category |
| `risk_type_inclusion` | Relevance & inclusion | category |
| `risk_type_expl` | Please explain | text |

Eight climate-risk types; 2018-2019 additionally have Upstream and Downstream rows. Preserve all six relevance/inclusion choices, not a binary flag.

**C2.2g — Why does your organization not have a process in place for identifying, assessing, and responding to climate-related risks and opportunities, and do you plan to introduce such a process in the future?** (PDF p. 15)

Dependency: C2.1 = No.

| Short name | Source field / meaning | Type |
|---|---|---|
| `no_process_reason` | Primary reason | category |
| `no_process_expl` | Please explain | text |

The plan to introduce a process in two years is a reason option, not a separate observed plan column.

**C2.3 — Have you identified any inherent climate-related risks with the potential to have a substantive financial or strategic impact on your business?** (PDF p. 15)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `climate_risk_raw` | Inherent climate-related risks identified | yes/no |
| `has_climate_risk` | Derived from explicit Yes/No | nullable boolean |

Not conditional on process existence.

**C2.3a — Provide details of risks identified with the potential to have a substantive financial or strategic impact on your business.** (PDF p. 16)

Dependency: C2.3 = Yes.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_id` | Identifier | category |
| `risk_stage` | Where in the value chain does the risk driver occur? | category |
| `risk_type` | Risk type | category |
| `risk_driver` | Primary climate-related risk driver | category |
| `fin_impact_type` | Primary potential financial impact | category |
| `risk_fs_class` | Climate risk type mapped to traditional financial services industry risk classification | category; FS only |
| `risk_desc` | Company-specific description | text |
| `risk_horizon` | Time horizon | category |
| `risk_likelihood` | Likelihood | category |
| `risk_magnitude` | Magnitude of impact | category |
| `fin_estimate_type` | Are you able to provide a potential financial impact figure? | category |
| `fin_impact` | Potential financial impact figure (currency) | decimal |
| `fin_impact_min` | Potential financial impact figure - minimum (currency) | decimal |
| `fin_impact_max` | Potential financial impact figure - maximum (currency) | decimal |
| `fin_impact_expl` | Explanation of financial impact figure | text |
| `response_cost` | Cost of response to risk | decimal |
| `response_and_cost_expl` | Description of response and explanation of cost calculation | text |
| `risk_comment` | Comment | text |

Eight risk types; Direct operations/Upstream/Downstream; no Current horizon option.

**C2.3b — Why do you not consider your organization to be exposed to climate-related risks with the potential to have a substantive financial or strategic impact on your business?** (PDF p. 18)

Dependency: C2.3 = No.

| Short name | Source field / meaning | Type |
|---|---|---|
| `no_risk_reason` | Primary reason | category |
| `no_risk_expl` | Please explain | text |

**C2.1a — How does your organization define short-, medium- and long-term time horizons?** (PDF p. 13)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `horizon` | Time horizon | category |
| `horizon_from_yrs` | From (years) | integer |
| `horizon_to_yrs` | To (years) | integer |
| `horizon_comment` | Comment | text |

Required following the clarified sheet scope. Short-, medium-, and long-term fixed rows; preserve the organization-specific definitions.

**C2.1b — How does your organization define substantive financial or strategic impact on your business?** (PDF p. 13)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `materiality_def` | Definition of substantive financial or strategic impact | text |

Top-level answer may be stored in the C2 - Risks and Opportunities overview sheet.

### 2022

**FULL questionnaire.** Source: [2022 Climate Change Questionnaire.pdf](<C:/Users/scelik/OneDrive - Tilburg University/TRACE3Code/data/raw/CDP/CDP Questionnaires/2022 Climate Change Questionnaire.pdf>). Page references are 1-based PDF pages, including the cover.

**C2.1 — Does your organization have a process for identifying, assessing, and responding to climate-related risks and opportunities?** (PDF p. 32)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_op_process_raw` | Does the organization have a process? | yes/no |
| `is_risk_op_assessed` | Derived from explicit Yes/No | nullable boolean |

**C2.2 — Describe your process(es) for identifying, assessing and responding to climate-related risks and opportunities.** (PDF p. 32)

Dependency: C2.1 = Yes.

| Short name | Source field / meaning | Type |
|---|---|---|
| `assess_stages` | Value chain stage(s) covered | multiselect |
| `process_type` | Risk management process | category |
| `assess_freq` | Frequency of assessment | category |
| `assess_horizons` | Time horizon(s) covered | multiselect |
| `assess_process` | Description of process | text |
| `assess_direct` | Derived membership of Direct operations in assessment stages | nullable boolean |
| `assess_upstream` | Derived membership of Upstream in assessment stages | nullable boolean |
| `assess_downstream` | Derived membership of Downstream in assessment stages | nullable boolean |

1 if selected; 0 only for an applicable, complete, nonblank response not selecting it; otherwise blank. Hidden FS Downstream is not 0.

**C2.2a — Which risk types are considered in your organization's climate-related risk assessments?** (PDF p. 33)

Dependency: C2.1 = Yes.

| Short name | Source field / meaning | Type |
|---|---|---|
| `assess_risk_type` | Risk type (fixed row label) | category |
| `risk_type_inclusion` | Relevance & inclusion | category |
| `risk_type_expl` | Please explain | text |

Eight climate-risk types; 2018-2019 additionally have Upstream and Downstream rows. Preserve all six relevance/inclusion choices, not a binary flag.

**C2.2g — Why does your organization not have a process in place for identifying, assessing, and responding to climate-related risks and opportunities, and do you plan to introduce such a process in the future?** (PDF p. 37)

Dependency: C2.1 = No.

| Short name | Source field / meaning | Type |
|---|---|---|
| `no_process_reason` | Primary reason | category |
| `no_process_expl` | Please explain | text |

The plan to introduce a process in two years is a reason option, not a separate observed plan column.

**C2.3 — Have you identified any inherent climate-related risks with the potential to have a substantive financial or strategic impact on your business?** (PDF p. 37)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `climate_risk_raw` | Inherent climate-related risks identified | yes/no |
| `has_climate_risk` | Derived from explicit Yes/No | nullable boolean |

Not conditional on process existence.

**C2.3a — Provide details of risks identified with the potential to have a substantive financial or strategic impact on your business.** (PDF p. 38)

Dependency: C2.3 = Yes.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_id` | Identifier | category |
| `risk_stage` | Where in the value chain does the risk driver occur? | category |
| `risk_type` | Risk type | category |
| `risk_driver` | Primary climate-related risk driver | category |
| `fin_impact_type` | Primary potential financial impact | category |
| `risk_fs_class` | Climate risk type mapped to traditional financial services industry risk classification | category; FS only |
| `risk_desc` | Company-specific description | text |
| `risk_horizon` | Time horizon | category |
| `risk_likelihood` | Likelihood | category |
| `risk_magnitude` | Magnitude of impact | category |
| `fin_estimate_type` | Are you able to provide a potential financial impact figure? | category |
| `fin_impact` | Potential financial impact figure (currency) | decimal |
| `fin_impact_min` | Potential financial impact figure - minimum (currency) | decimal |
| `fin_impact_max` | Potential financial impact figure - maximum (currency) | decimal |
| `fin_impact_expl` | Explanation of financial impact figure | text |
| `response_cost` | Cost of response to risk | decimal |
| `response_and_cost_expl` | Description of response and explanation of cost calculation | text |
| `risk_comment` | Comment | text |

Adds financial-services portfolio stages; Upstream/Downstream hidden for FS; eight risk types.

**C2.3b — Why do you not consider your organization to be exposed to climate-related risks with the potential to have a substantive financial or strategic impact on your business?** (PDF p. 41)

Dependency: C2.3 = No.

| Short name | Source field / meaning | Type |
|---|---|---|
| `no_risk_reason` | Primary reason | category |
| `no_risk_expl` | Please explain | text |

**C2.1a — How does your organization define short-, medium- and long-term time horizons?** (PDF p. 32)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `horizon` | Time horizon | category |
| `horizon_from_yrs` | From (years) | integer |
| `horizon_to_yrs` | To (years) | integer |
| `horizon_comment` | Comment | text |

Required following the clarified sheet scope. Short-, medium-, and long-term fixed rows; preserve the organization-specific definitions.

**C2.1b — How does your organization define substantive financial or strategic impact on your business?** (PDF p. 32)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `materiality_def` | Definition of substantive financial or strategic impact | text |

Top-level answer may be stored in the C2 - Risks and Opportunities overview sheet.

### 2023

**FULL questionnaire.** Source: [2023 Climate Change Questionnaire.pdf](<C:/Users/scelik/OneDrive - Tilburg University/TRACE3Code/data/raw/CDP/CDP Questionnaires/2023 Climate Change Questionnaire.pdf>). Page references are 1-based PDF pages, including the cover.

**C2.1 — Does your organization have a process for identifying, assessing, and responding to climate-related risks and opportunities?** (PDF p. 30)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_op_process_raw` | Does the organization have a process? | yes/no |
| `is_risk_op_assessed` | Derived from explicit Yes/No | nullable boolean |

**C2.2 — Describe your process(es) for identifying, assessing and responding to climate-related risks and opportunities.** (PDF p. 30)

Dependency: C2.1 = Yes.

| Short name | Source field / meaning | Type |
|---|---|---|
| `assess_stages` | Value chain stage(s) covered | multiselect |
| `process_type` | Risk management process | category |
| `assess_freq` | Frequency of assessment | category |
| `assess_horizons` | Time horizon(s) covered | multiselect |
| `assess_process` | Description of process | text |
| `assess_direct` | Derived membership of Direct operations in assessment stages | nullable boolean |
| `assess_upstream` | Derived membership of Upstream in assessment stages | nullable boolean |
| `assess_downstream` | Derived membership of Downstream in assessment stages | nullable boolean |

1 if selected; 0 only for an applicable, complete, nonblank response not selecting it; otherwise blank. Hidden FS Downstream is not 0.

**C2.2a — Which risk types are considered in your organization's climate-related risk assessments?** (PDF p. 31)

Dependency: C2.1 = Yes.

| Short name | Source field / meaning | Type |
|---|---|---|
| `assess_risk_type` | Risk type (fixed row label) | category |
| `risk_type_inclusion` | Relevance & inclusion | category |
| `risk_type_expl` | Please explain | text |

Eight climate-risk types; 2018-2019 additionally have Upstream and Downstream rows. Preserve all six relevance/inclusion choices, not a binary flag.

**C2.2g — Why does your organization not have a process in place for identifying, assessing, and responding to climate-related risks and opportunities, and do you plan to introduce such a process in the future?** (PDF p. 35)

Dependency: C2.1 = No.

| Short name | Source field / meaning | Type |
|---|---|---|
| `no_process_reason` | Primary reason | category |
| `no_process_expl` | Please explain | text |

The plan to introduce a process in two years is a reason option, not a separate observed plan column.

**C2.3 — Have you identified any inherent climate-related risks with the potential to have a substantive financial or strategic impact on your business?** (PDF p. 35)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `climate_risk_raw` | Inherent climate-related risks identified | yes/no |
| `has_climate_risk` | Derived from explicit Yes/No | nullable boolean |

Not conditional on process existence.

**C2.3a — Provide details of risks identified with the potential to have a substantive financial or strategic impact on your business.** (PDF p. 36)

Dependency: C2.3 = Yes.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_id` | Identifier | category |
| `risk_stage` | Where in the value chain does the risk driver occur? | category |
| `risk_type` | Risk type | category |
| `risk_driver` | Primary climate-related risk driver | category |
| `fin_impact_type` | Primary potential financial impact | category |
| `risk_fs_class` | Climate risk type mapped to traditional financial services industry risk classification | category; FS only |
| `risk_desc` | Company-specific description | text |
| `risk_horizon` | Time horizon | category |
| `risk_likelihood` | Likelihood | category |
| `risk_magnitude` | Magnitude of impact | category |
| `fin_estimate_type` | Are you able to provide a potential financial impact figure? | category |
| `fin_impact` | Potential financial impact figure (currency) | decimal |
| `fin_impact_min` | Potential financial impact figure - minimum (currency) | decimal |
| `fin_impact_max` | Potential financial impact figure - maximum (currency) | decimal |
| `fin_impact_expl` | Explanation of financial impact figure | text |
| `response_cost` | Cost of response to risk | decimal |
| `response_and_cost_expl` | Description of response and explanation of cost calculation | text |
| `risk_comment` | Comment | text |

Adds financial-services portfolio stages; Upstream/Downstream hidden for FS; eight risk types.

**C2.3b — Why do you not consider your organization to be exposed to climate-related risks with the potential to have a substantive financial or strategic impact on your business?** (PDF p. 39)

Dependency: C2.3 = No.

| Short name | Source field / meaning | Type |
|---|---|---|
| `no_risk_reason` | Primary reason | category |
| `no_risk_expl` | Please explain | text |

**C2.1a — How does your organization define short-, medium- and long-term time horizons?** (PDF p. 30)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `horizon` | Time horizon | category |
| `horizon_from_yrs` | From (years) | integer |
| `horizon_to_yrs` | To (years) | integer |
| `horizon_comment` | Comment | text |

Required following the clarified sheet scope. Short-, medium-, and long-term fixed rows; preserve the organization-specific definitions.

**C2.1b — How does your organization define substantive financial or strategic impact on your business?** (PDF p. 30)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `materiality_def` | Definition of substantive financial or strategic impact | text |

Top-level answer may be stored in the C2 - Risks and Opportunities overview sheet.

### 2024

**FULL questionnaire.** Source: [2024 - Corporate Questionnaire - Modules 1 to 6.pdf](<C:/Users/scelik/OneDrive - Tilburg University/TRACE3Code/data/raw/CDP/CDP Questionnaires/2024 - Corporate Questionnaire - Modules 1 to 6.pdf>). Page references are 1-based PDF pages, including the cover.

**2.2.1 — Does your organization have a process for identifying, assessing, and managing environmental risks and/or opportunities?** (PDF p. 65)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_op_process_raw` | Process in place | category |
| `is_risk_op_assessed` | Derived from Process in place | nullable boolean |
| `process_scope` | Risks and/or opportunities evaluated in this process | category |
| `process_dep_link` | Is this process informed by the dependencies and/or impacts process? | yes/no |
| `no_process_reason` | Primary reason for not evaluating risks and/or opportunities | category |
| `no_process_expl` | Explain why you do not evaluate risks and/or opportunities and describe any plans to do so in the future | text |
| `process_link_expl` | Explain why you do not have a process for evaluating both risks and opportunities that is informed by a dependencies and/or impacts process | text |

Environmental process, not proof of climate-risk assessment. Process scope: Risks only / Opportunities only / Both. Preserve Yes / No planned / No not planned.

**2.2.2 — Provide details of your organization’s process for identifying, assessing, and managing environmental dependencies, impacts, risks, and/or opportunities.** (PDF p. 66)

Dependency: Process in place = Yes in either 2.2 or 2.2.1; select rows including Climate change AND Risks.

| Short name | Source field / meaning | Type |
|---|---|---|
| `env_issue` | Environmental issue | multiselect |
| `process_covers` | Indicate which of dependencies, impacts, risks, and opportunities are covered by the process for this environmental issue | multiselect |
| `assess_stages` | Value chain stages covered | multiselect |
| `assess_coverage` | Coverage | category |
| `supplier_tiers` | Supplier tiers covered | multiselect |
| `mining_projects` | Mining projects covered | multiselect; sector-specific |
| `assess_method` | Type of assessment | category |
| `assess_freq` | Frequency of assessment | category |
| `assess_horizons` | Time horizons covered | multiselect |
| `process_type` | Integration of risk management process | category |
| `assess_location` | Location-specificity used | multiselect |
| `tool_types` | Type of tools and methods used | multiselect |
| `assess_tools` | Tools and methods used | multiselect |
| `assess_risk_types` | Risk types considered | multiselect |
| `assess_criteria` | Criteria considered | multiselect |
| `assess_stakeholders` | Partners and stakeholders considered | multiselect |
| `process_changed` | Has this process changed since the previous reporting year? | yes/no |
| `assess_process` | Further details of process | text |
| `assess_direct` | Derived membership of Direct operations in assessment stages | nullable boolean |
| `assess_upstream` | Derived membership of Upstream in assessment stages | nullable boolean |
| `assess_downstream` | Derived membership of Downstream in assessment stages | nullable boolean |

Not equivalent to the earlier six-category risk-type relevance/inclusion table. In 2025 risk types and criteria form one grouped field.

1 if selected; 0 only for an applicable, complete, nonblank response not selecting it; otherwise blank. Hidden FS Downstream is not 0.

**3.1 — Have you identified any environmental risks which have had a substantive effect on your organization in the reporting year, or are anticipated to have a substantive effect on your organization in the future?** (PDF p. 125)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `env_issue` | Environmental issue | category |
| `climate_risk_raw` | Environmental risks identified | category |
| `has_climate_risk` | Derived from explicit Yes variant / No | nullable boolean |
| `no_risk_reason` | Primary reason why your organization does not consider itself to have environmental risks in your direct operations and/or upstream/downstream value chain | category |
| `no_risk_expl` | Please explain | text |

Keep Climate change row. Retain detailed Yes variants for operations/value-chain/portfolio; no-risk reason/explanation are in this same table.

**3.1.1 — Provide details of the environmental risks identified which have had a substantive effect on your organization in the reporting year, or are anticipated to have a substantive effect on your organization in the future.** (PDF p. 127)

Dependency: Any Yes option in 3.1; select Climate change risk rows.

| Short name | Source field / meaning | Type |
|---|---|---|
| `env_issue` | Environmental issue the risk relates to | category |
| `risk_id` | Risk identifier | category |
| `commodity` | Commodity | multiselect; climate N/A |
| `risk_driver_raw` | Risk type and primary environmental risk driver | grouped category |
| `risk_stage` | Value chain stage where the risk occurs | category |
| `risk_fs_class` | Risk type mapped to traditional financial services industry risk classification | multiselect; FS only |
| `risk_country` | Country/area where the risk occurs | multiselect |
| `risk_basin` | River basin where the risk occurs | multiselect; climate N/A |
| `mining_project` | Mining project ID | multiselect; climate N/A |
| `risk_desc` | Organization-specific description of risk | text |
| `portfolio_risk_pct` | % of portfolio value vulnerable to this risk | percentage band; FS only |
| `fin_impact_type` | Primary financial effect of the risk | category |
| `risk_horizons` | Time horizon over which the risk is anticipated to have a substantive effect on the organization | multiselect |
| `risk_likelihood` | Likelihood of the risk having an effect within the anticipated time horizon | category |
| `risk_magnitude` | Magnitude | category |
| `fin_effect_now_desc` | Effect of the risk on the financial position, financial performance and cash flows of the organization in the reporting year | text |
| `fin_effect_future_desc` | Anticipated effect of the risk on the financial position, financial performance and cash flows of the organization in the selected future time horizons | text |
| `can_quantify_risk` | Are you able to quantify the financial effect of the risk? | yes/no |
| `fin_effect_now` | Financial effect figure in the reporting year (currency) | decimal |
| `fin_effect_st_min` | Anticipated financial effect figure in the short-term - minimum (currency) | decimal |
| `fin_effect_st_max` | Anticipated financial effect figure in the short-term - maximum (currency) | decimal |
| `fin_effect_mt_min` | Anticipated financial effect figure in the medium-term - minimum (currency) | decimal |
| `fin_effect_mt_max` | Anticipated financial effect figure in the medium-term - maximum (currency) | decimal |
| `fin_effect_lt_min` | Anticipated financial effect figure in the long-term - minimum (currency) | decimal |
| `fin_effect_lt_max` | Anticipated financial effect figure in the long-term - maximum (currency) | decimal |
| `fin_impact_expl` | Explanation of financial effect figure | text |
| `response_type` | Primary response to risk | grouped category |
| `response_cost` | Cost of response to risk | decimal |
| `response_cost_expl` | Explanation of cost calculation | text |
| `risk_response` | Description of response | text |

All 30 source columns accounted for; climate-inapplicable columns explicitly marked. Do not combine current and future financial effects with pre-2024 potential-impact fields.

**2.1 — How does your organization define short-, medium-, and long-term time horizons in relation to the identification, assessment, and management of your environmental dependencies, impacts, risks, and opportunities?** (PDF p. 62)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `horizon` | Time horizon | category |
| `horizon_from_yrs` | From (years) | integer |
| `horizon_to_yrs` | To (years) | integer |
| `horizon_open_ended` | Is your long-term time horizon open ended? | yes/no; long-term only |
| `horizon_planning_link` | How this time horizon is linked to strategic and/or financial planning | text |

Required following the clarified sheet scope. Short-, medium-, and long-term fixed rows; preserve the organization-specific definitions.

**SME questionnaire.** Source: [2024 - Corporate Questionnaire - SME Modules 14 to 21.pdf](<C:/Users/scelik/OneDrive - Tilburg University/TRACE3Code/data/raw/CDP/CDP Questionnaires/2024 - Corporate Questionnaire - SME Modules 14 to 21.pdf>). Page references are 1-based PDF pages, including the cover.

**15.1 — Does your organization have a process for identifying, assessing, and managing environmental risks and opportunities?** (PDF p. 16)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_op_process_raw` | Process in place | category |
| `is_risk_op_assessed` | Derived from Process in place | nullable boolean |
| `process_scope` | Risks and/or opportunities evaluated in this process | category |
| `assess_freq` | Frequency of assessment | category |
| `assess_process` | Please explain the process | text |

No separate structured assessment-stage or risk-type assessment table.

**16.1 — Are you aware of any risks created by environmental issues which have had a substantive effect on your organization in the reporting year or may in the future?** (PDF p. 19)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `env_issue` | Environmental issue | category |
| `climate_risk_raw` | Environmental risks identified | category |
| `has_climate_risk` | Derived from explicit Yes variant / No | nullable boolean |
| `no_risk_reason` | Primary reason why your organization does not consider itself to have environmental risks in your direct operations and/or upstream/downstream value chain | category |

Climate change row. No separate Please explain column in this SME table.

**16.1.1 — Provide details of the risks created by environmental issues which have had a substantive effect on your organization in the reporting year or may in the future.** (PDF p. 21)

Dependency: Any Yes option in 16.1; select Climate change risk rows.

| Short name | Source field / meaning | Type |
|---|---|---|
| `env_issue` | Environmental issue the risk relates to | category |
| `risk_id` | Risk identifier | category |
| `commodity` | Commodity | multiselect; climate N/A |
| `risk_driver_raw` | Risk type and primary source of the environmental risk | grouped category |
| `risk_stage` | Value chain stage where the risk occurs | category |
| `risk_country` | Country/area where the risk occurs | multiselect |
| `risk_basin` | River basin where the risk occurs | multiselect; climate N/A |
| `risk_desc` | Organization-specific description of risk | text |
| `fin_impact_type` | Primary financial effect of the risk | category |
| `risk_horizons` | Time horizon over which the risk is anticipated to have a substantive effect on the organization | multiselect |
| `risk_likelihood` | Likelihood of the risk having an effect within the anticipated time horizon | category |
| `risk_magnitude` | Magnitude | category |
| `can_quantify_risk` | Are you able to quantify the financial effect of the risk? | yes/no |
| `fin_effect_min` | Potential financial effect figure - minimum (currency) | decimal |
| `fin_effect_max` | Potential financial effect figure - maximum (currency) | decimal |
| `fin_impact_expl` | Explanation of financial effect figure | text |
| `response_type` | Primary response to risk | grouped category |
| `response_cost` | Cost of response to risk | decimal |
| `response_cost_expl` | Explanation of cost calculation | text |
| `risk_response` | Description of response | text |

All 20 SME source columns accounted for. No separate current/ST/MT/LT financial estimates.

### 2025

**FULL questionnaire.** Source: [2025_Full_Corporate_Questionnaire_Modules_1-6.pdf](<C:/Users/scelik/OneDrive - Tilburg University/TRACE3Code/data/raw/CDP/CDP Questionnaires/2025_Full_Corporate_Questionnaire_Modules_1-6.pdf>). Page references are 1-based PDF pages, including the cover.

**2025 change:** tools/methods and risk-types/criteria use grouped selections instead of separate 2024 group and option columns.

**2.2.1 — Does your organization have a process for identifying, assessing, and managing environmental risks and/or opportunities?** (PDF p. 72)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_op_process_raw` | Process in place | category |
| `is_risk_op_assessed` | Derived from Process in place | nullable boolean |
| `process_scope` | Risks and/or opportunities evaluated in this process | category |
| `process_dep_link` | Is this process informed by the dependencies and/or impacts process? | yes/no |
| `no_process_reason` | Primary reason for not evaluating risks and/or opportunities | category |
| `no_process_expl` | Explain why you do not evaluate risks and/or opportunities and describe any plans to do so in the future | text |
| `process_link_expl` | Explain why you do not have a process for evaluating both risks and opportunities that is informed by a dependencies and/or impacts process | text |

Environmental process, not proof of climate-risk assessment. Process scope: Risks only / Opportunities only / Both. Preserve Yes / No planned / No not planned.

**2.2.2 — Provide details of your organization’s process for identifying, assessing, and managing environmental dependencies, impacts, risks, and/or opportunities.** (PDF p. 74)

Dependency: Process in place = Yes in either 2.2 or 2.2.1; select rows including Climate change AND Risks.

| Short name | Source field / meaning | Type |
|---|---|---|
| `env_issue` | Environmental issue | multiselect |
| `process_covers` | Indicate which of dependencies, impacts, risks, and opportunities are covered by the process for this environmental issue | multiselect |
| `assess_stages` | Value chain stages covered | multiselect |
| `assess_coverage` | Coverage | category |
| `supplier_tiers` | Supplier tiers covered | multiselect |
| `mining_projects` | Mining projects covered | multiselect; sector-specific |
| `assess_method` | Type of assessment | category |
| `assess_freq` | Frequency of assessment | category |
| `assess_horizons` | Time horizons covered | multiselect |
| `process_type` | Integration of risk management process | category |
| `assess_location` | Location-specificity used | multiselect |
| `assess_tools` | Tools and methods used | grouped multiselect |
| `risk_types_criteria` | Risk types and criteria considered | grouped multiselect |
| `assess_stakeholders` | Partners and stakeholders considered | multiselect |
| `process_changed` | Has this process changed since the previous reporting year? | yes/no |
| `assess_process` | Further details of process | text |
| `assess_direct` | Derived membership of Direct operations in assessment stages | nullable boolean |
| `assess_upstream` | Derived membership of Upstream in assessment stages | nullable boolean |
| `assess_downstream` | Derived membership of Downstream in assessment stages | nullable boolean |

Not equivalent to the earlier six-category risk-type relevance/inclusion table. In 2025 risk types and criteria form one grouped field.

1 if selected; 0 only for an applicable, complete, nonblank response not selecting it; otherwise blank. Hidden FS Downstream is not 0.

**3.1 — Have you identified any environmental risks which have had a substantive effect on your organization in the reporting year, or are anticipated to have a substantive effect on your organization in the future?** (PDF p. 137)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `env_issue` | Environmental issue | category |
| `climate_risk_raw` | Environmental risks identified | category |
| `has_climate_risk` | Derived from explicit Yes variant / No | nullable boolean |
| `no_risk_reason` | Primary reason why your organization does not consider itself to have environmental risks in your direct operations and/or upstream/downstream value chain | category |
| `no_risk_expl` | Please explain | text |

Keep Climate change row. Retain detailed Yes variants for operations/value-chain/portfolio; no-risk reason/explanation are in this same table.

**3.1.1 — Provide details of the environmental risks identified which have had a substantive effect on your organization in the reporting year, or are anticipated to have a substantive effect on your organization in the future.** (PDF p. 139)

Dependency: Any Yes option in 3.1; select Climate change risk rows.

| Short name | Source field / meaning | Type |
|---|---|---|
| `env_issue` | Environmental issue the risk relates to | category |
| `risk_id` | Risk identifier | category |
| `commodity` | Commodity | multiselect; climate N/A |
| `risk_driver_raw` | Risk type and primary environmental risk driver | grouped category |
| `risk_stage` | Value chain stage where the risk occurs | category |
| `risk_fs_class` | Risk type mapped to traditional financial services industry risk classification | multiselect; FS only |
| `risk_country` | Country/area where the risk occurs | multiselect |
| `risk_basin` | River basin where the risk occurs | multiselect; climate N/A |
| `mining_project` | Mining project ID | multiselect; climate N/A |
| `risk_desc` | Organization-specific description of risk | text |
| `portfolio_risk_pct` | % of portfolio value vulnerable to this risk | percentage band; FS only |
| `fin_impact_type` | Primary financial effect of the risk | category |
| `risk_horizons` | Time horizon over which the risk is anticipated to have a substantive effect on the organization | multiselect |
| `risk_likelihood` | Likelihood of the risk having an effect within the anticipated time horizon | category |
| `risk_magnitude` | Magnitude | category |
| `fin_effect_now_desc` | Effect of the risk on the financial position, financial performance and cash flows of the organization in the reporting year | text |
| `fin_effect_future_desc` | Anticipated effect of the risk on the financial position, financial performance and cash flows of the organization in the selected future time horizons | text |
| `can_quantify_risk` | Are you able to quantify the financial effect of the risk? | yes/no |
| `fin_effect_now` | Financial effect figure in the reporting year (currency) | decimal |
| `fin_effect_st_min` | Anticipated financial effect figure in the short-term - minimum (currency) | decimal |
| `fin_effect_st_max` | Anticipated financial effect figure in the short-term - maximum (currency) | decimal |
| `fin_effect_mt_min` | Anticipated financial effect figure in the medium-term - minimum (currency) | decimal |
| `fin_effect_mt_max` | Anticipated financial effect figure in the medium-term - maximum (currency) | decimal |
| `fin_effect_lt_min` | Anticipated financial effect figure in the long-term - minimum (currency) | decimal |
| `fin_effect_lt_max` | Anticipated financial effect figure in the long-term - maximum (currency) | decimal |
| `fin_impact_expl` | Explanation of financial effect figure | text |
| `response_type` | Primary response to risk | grouped category |
| `response_cost` | Cost of response to risk | decimal |
| `response_cost_expl` | Explanation of cost calculation | text |
| `risk_response` | Description of response | text |

All 30 source columns accounted for; climate-inapplicable columns explicitly marked. Do not combine current and future financial effects with pre-2024 potential-impact fields.

**2.1 — How does your organization define short-, medium-, and long-term time horizons in relation to the identification, assessment, and management of your environmental dependencies, impacts, risks, and opportunities?** (PDF p. 69)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `horizon` | Time horizon | category |
| `horizon_from_yrs` | From (years) | integer |
| `horizon_to_yrs` | To (years) | integer |
| `horizon_open_ended` | Is your long-term time horizon open ended? | yes/no; long-term only |
| `horizon_planning_link` | How this time horizon is linked to strategic and/or financial planning | text |

Required following the clarified sheet scope. Short-, medium-, and long-term fixed rows; preserve the organization-specific definitions.

**SME questionnaire.** Source: [2025_SME_Questionnaire_Modules_14-21.pdf](<C:/Users/scelik/OneDrive - Tilburg University/TRACE3Code/data/raw/CDP/CDP Questionnaires/2025_SME_Questionnaire_Modules_14-21.pdf>). Page references are 1-based PDF pages, including the cover.

**15.1 — Does your organization have a process for identifying, assessing, and managing environmental risks and opportunities?** (PDF p. 16)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `risk_op_process_raw` | Process in place | category |
| `is_risk_op_assessed` | Derived from Process in place | nullable boolean |
| `process_scope` | Risks and/or opportunities evaluated in this process | category |
| `assess_freq` | Frequency of assessment | category |
| `assess_process` | Please explain the process | text |

No separate structured assessment-stage or risk-type assessment table.

**16.1 — Are you aware of any risks created by environmental issues which have had a substantive effect on your organization in the reporting year or may in the future?** (PDF p. 19)

Dependency: Company-level question; do not infer an answer from missing data.

| Short name | Source field / meaning | Type |
|---|---|---|
| `env_issue` | Environmental issue | category |
| `climate_risk_raw` | Environmental risks identified | category |
| `has_climate_risk` | Derived from explicit Yes variant / No | nullable boolean |
| `no_risk_reason` | Primary reason why your organization does not consider itself to have environmental risks in your direct operations and/or upstream/downstream value chain | category |

Climate change row. No separate Please explain column in this SME table.

**16.1.1 — Provide details of the risks created by environmental issues which have had a substantive effect on your organization in the reporting year or may in the future.** (PDF p. 21)

Dependency: Any Yes option in 16.1; select Climate change risk rows.

| Short name | Source field / meaning | Type |
|---|---|---|
| `env_issue` | Environmental issue the risk relates to | category |
| `risk_id` | Risk identifier | category |
| `commodity` | Commodity | multiselect; climate N/A |
| `risk_driver_raw` | Risk type and primary source of the environmental risk | grouped category |
| `risk_stage` | Value chain stage where the risk occurs | category |
| `risk_country` | Country/area where the risk occurs | multiselect |
| `risk_basin` | River basin where the risk occurs | multiselect; climate N/A |
| `risk_desc` | Organization-specific description of risk | text |
| `fin_impact_type` | Primary financial effect of the risk | category |
| `risk_horizons` | Time horizon over which the risk is anticipated to have a substantive effect on the organization | multiselect |
| `risk_likelihood` | Likelihood of the risk having an effect within the anticipated time horizon | category |
| `risk_magnitude` | Magnitude | category |
| `can_quantify_risk` | Are you able to quantify the financial effect of the risk? | yes/no |
| `fin_effect_min` | Potential financial effect figure - minimum (currency) | decimal |
| `fin_effect_max` | Potential financial effect figure - maximum (currency) | decimal |
| `fin_impact_expl` | Explanation of financial effect figure | text |
| `response_type` | Primary response to risk | grouped category |
| `response_cost` | Cost of response to risk | decimal |
| `response_cost_expl` | Explanation of cost calculation | text |
| `risk_response` | Description of response | text |

All 20 SME source columns accounted for. No separate current/ST/MT/LT financial estimates.

## Supporting questions and review files

Time-horizon definitions and 2020-2023 substantive-impact definitions are included after the clarified workbook scope. The additional financial-metrics question 3.1.2 remains outside this C2.3a-equivalent scope.

`risk_questions_2016_2025.csv`: parent-question wording, year, dependency, PDF page and source. `risk_field_mapping_2016_2025.csv`: full field mappings, types, notes and source availability. Each annual folder contains a field dictionary and empty CSV table templates. The requested 2020 opportunity sheet is included as an example; the full cross-year opportunity review remains next.

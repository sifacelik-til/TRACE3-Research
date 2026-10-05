# CDP risks and opportunities, 2016–2025

Populated dataset: 393,723 records. It uses the same matched-company sample as the other four sections. All 2,886,788 retained source values were verified after writing the CSV.

[Open the populated CSV](<C:/Users/scelik/OneDrive - Tilburg University/TRACE3Code/data/processed/cdp_section_datasets/cdp_risks_opportunities_2016_2025.csv>)

[Question inventory](questions_2016_2025.csv) · [Exact field mappings](field_mapping_2016_2025.csv) · [Field dictionary](field_dictionary.csv) · [Field coverage](field_coverage.csv)

## Included records

| Record type | Rows |
|---|---:|
| `assessment` | 23,686 |
| `assessment_status` | 20,525 |
| `horizon` | 51,263 |
| `materiality` | 8,800 |
| `no_assessment` | 611 |
| `no_opportunity` | 2,433 |
| `no_risk` | 2,707 |
| `opportunity` | 59,835 |
| `opportunity_status` | 20,282 |
| `prioritization` | 2,707 |
| `process_detail` | 5,591 |
| `risk` | 74,312 |
| `risk_management` | 2,864 |
| `risk_status` | 20,301 |
| `risk_type_assessed` | 97,806 |

Includes process existence, assessment stages/frequency/horizons, assessed risk types, substantive-impact definitions, individual risks and opportunities, financial effects, response strategies and costs, and reasons for no process, risks or opportunities.

The 2020 source scope includes the C2 overview, C2.1a, C2.2, C2.3a and C2.4a sheets requested earlier, plus C2.2a, C2.2g, C2.3b and C2.4b for risk-type assessments and negative branches.

## Interpreting the fields

- One row represents one source question row, keyed by disclosure year, CDP account and record ID. A company can have many risk/opportunity rows. Filter `record_type` before analysis. `item_id` identifies the disclosed risk/opportunity when the source supplies an identifier.
- Shared names such as `driver`, `description`, `time_horizon` and financial-effect fields refer to the risk or opportunity identified by `record_type`. They do not combine different risks or opportunities into a single answer.
- `is_risk_op_assessed` retains the source process-existence answer. It is categorical, not a normalized Boolean or evidence that an assessment was completed. In 2016–2019 it can describe integrated/dedicated/no documented processes; in recent years it can include Yes/No and future plans.
- In 2024–2025, `process_scope` distinguishes Risks only, Opportunities only and Both. Use `process_covers` and `env_issue` on assessment rows to establish climate-risk versus climate-opportunity coverage. A general environmental process does not prove climate-specific assessment.
- `assess_stages` is the coverage of the assessment process. `value_chain_stage` is the location of an individual risk/opportunity. For horizon records, the source `row_label` identifies Short-, Medium- or Long-term. For risk-type assessments, it identifies the assessed risk category.
- For 2020–2023 risk details, the grouped `_G` source field is `risk_type`; its companion is `driver`. Recent exports combine type and driver in a single grouped answer, which remains together in `driver`.
- `potential_fin_effect`/`potential_fin_min`/`potential_fin_max` are potential impacts. `current_fin_effect` is a reporting-year effect. `future_st_*`, `future_mt_*` and `future_lt_*` hold anticipated short-, medium- and long-term amounts. Do not add these different measures together.
- Legacy financial implications and management costs can be narrative text and remain in `financial_effect_text` and `response_cost_text`. All monetary values retain the company reporting currency. No inflation adjustments, currency conversions or interpretation of narrative amounts were applied.
- Explicit Yes variants, including opportunities identified but not currently realizable, are preserved. Blank does not mean No or zero. Useful conditional fields are retained without the earlier 65% missingness cutoff.
- Answer cells contain only answers. Multi-select answers use JSON lists. Source headers/files are stored in the mapping and separate provenance file. Sector and industry are included where available in the matched panel.

## Year-specific sources

| Years | Process/assessment | Risks | Opportunities |
|---|---|---|---|
| 2016–2017 | CC2.1 and branches | CC5.1 and branches | CC6.1 and branches |
| 2018–2019 | C2.2 and branches; C2.1 horizons | C2.3/a/b | C2.4/a/b |
| 2020–2023 | C2.1/a/b; C2.2/a/g | C2.3/a/b | C2.4/a/b |
| 2024–2025 Full | 2.1; 2.2.1; 2.2.2 | 3.1; 3.1.1 | 3.6; 3.6.1 |
| 2024–2025 SME | 15.1 | 16.1; 16.1.1 | 16.3; 16.3.1 |

Explicitly non-climate environmental records are excluded. Recent general process/horizon answers without an explicit issue remain marked `environmental_unspecified`. Climate-specific records are marked `explicit_climate`; older climate-questionnaire records use `climate_questionnaire`.
The original 2016–2017 exports supply CC5.1d/e/f and CC6.1d/e/f for no-risk/no-opportunity explanations. These actual export codes are preserved even where the PDF prints the prose under the parent question instead of displaying a separate subcode.
Additional financial-metric tables 3.1.2/3.6.2 and specialist portfolio-assessment families are outside the requested core scope. Commodity, river-basin and mining identifiers that are irrelevant to the climate records are excluded.
Validation, original-value provenance and exclusion logs are in `data/processed/cdp_section_datasets/risk_opportunity_support`.

## Annual blank templates

- [2016 template](2016_template.csv)
- [2017 template](2017_template.csv)
- [2018 template](2018_template.csv)
- [2019 template](2019_template.csv)
- [2020 template](2020_template.csv)
- [2021 template](2021_template.csv)
- [2022 template](2022_template.csv)
- [2023 template](2023_template.csv)
- [2024 template](2024_template.csv)
- [2025 template](2025_template.csv)

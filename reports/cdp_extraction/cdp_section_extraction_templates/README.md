# CDP section datasets, 2016–2025

Five populated CSV datasets use the same matched company sample as the existing CDP–Trucost–FactSet–LSEG panel. Each section has its own annual blank templates, field dictionary, question inventory and exact source-header mapping.

| Section | Records | Answer and derived fields |
|---|---:|---:|
| [Targets Performance](targets_performance/field_mapping_2016_2025.csv) | 346,532 | 64 |
| [Verification](verification/field_mapping_2016_2025.csv) | 155,228 | 12 |
| [Carbon Pricing](carbon_pricing/field_mapping_2016_2025.csv) | 92,825 | 39 |
| [Engagement](engagement/field_mapping_2016_2025.csv) | 113,269 | 49 |
| Risks and Opportunities | 393,723 | 78 |

## Reading the data

- One row is one source question row for a CDP account and disclosure year. A company can have several targets, initiatives, verification statements or schemes. Filter `record_type` before calculating totals.
- Join on `year` and `cdp_account_number`. `company_year_links.csv` links accounts to the existing FactSet/Trucost/LSEG panel. Account-level data are not duplicated when an account links to multiple panel companies.
- Company name, primary sector and primary industry come from the existing matched panel. Currency comes from the annual CDP response and is not converted.
- Answer cells contain only source answers. Multi-select answers are stored as JSON lists of answer values. Original question headers and source files are stored separately in the mappings and `answer_provenance.jsonl.gz`.
- Blank means unavailable in that source row. It does not mean zero or No. Useful conditional fields are retained, including fields exceeding 65% missingness, following the requested preference. Field coverage is reported within year and record type.
- Rows containing only CDP inapplicability placeholders are excluded. Individual source answers such as Not applicable are preserved when part of a substantive record.
- `year` is the CDP disclosure year, not necessarily the financial/emissions reporting period. Read target date/year fields as supplied; no date or currency conversions were made.

## Targets and performance

Includes active-target flags, absolute/intensity/energy/other/net-zero targets, coverage, base and target years/dates, science-based status, emissions or intensity levels, target progress and selected implementation plans. Detailed scope-category emissions columns are omitted in favor of reported totals and Scope 3 totals; totals are not reconstructed from components.
Emissions-reduction initiatives receive separate `initiative_status`, `initiative_stage`, `initiative`, `investment_method` and `no_initiative` records. Initiative rows retain category/type, scopes, estimated annual CO2e savings, annual monetary savings, investment, payback, lifetime and explanatory comments. Recent questionnaires sometimes supply category and type as one combined answer, preserved in `initiative_type`.
**Savings are estimates.** Do not sum initiative-stage totals together with individual initiative savings. Stages are retained in `row_label` or `initiative_stage`. Neither target progress nor estimated savings establishes a realized company-wide emissions reduction.

## Verification

Includes assurance status, cycle, reporting-year status, assurance level, verification standard, verified percentage, emissions scope and Scope 3 category. C10.1a covers Scope 1 and 2 jointly in 2018–2019; explicit source scope is preserved. Later questionnaires split these scopes. Verification attachments and page references are excluded.

## Carbon pricing

Includes regulatory coverage, ETS allowances and verified emissions, carbon tax coverage/payment, internal pricing objectives/type/scopes/application/prices, and carbon-credit activity and volumes. The 2016–2017 regulatory flag refers to ETS participation, while later flags also encompass carbon taxes; consult `question_code` and the question inventory.
Credit purchases/origination and canceled/retired credits are different measures and remain in separate fields. `credit_activity_raw` retains the original answer to the year-specific question. From 2024, `internal_pricing_raw` asks about environmental externalities generally; inspect `externalities_priced` or carbon-specific detail records before interpreting it as carbon pricing.

## Engagement

Focuses on value-chain engagement, supplier/customer coverage and Scope 3 coverage, supplier requirements, compliance monitoring, non-compliance response and effects. Policy lobbying, trade-association memberships, public communications and attachments are excluded.
From 2024, CDP combines environmental topics. Explicitly non-climate records are excluded; cross-environment records without an explicit issue remain marked `environmental_unspecified`. `climate_relevance` distinguishes these from explicit climate answers. SME questions supply less detail; absent SME carbon-pricing records do not mean No.
A source quirk in 2016–2017 labels some no-engagement explanations CC14.4c although the questionnaire uses CC14.4d. The data preserve the supplied question code and map the answer by its full header.

## Validation and sources

All 6,056,013 retained source answer values were checked against separate source provenance after CSV serialization. Record identifiers are unique, and every account-year belongs to the matched sample.
Sources are the local annual CDP Excel exports (2016–2023), response parquet exports (2024–2025), and annual questionnaire PDFs. Question mappings include the original headers and PDF page references where a matching heading was found. A missing PDF heading is explicitly marked for review.
The populated CSV files are in `data/processed/cdp_section_datasets`. This folder also contains coverage, exclusions, source-field audit and validation files.

## Risks and opportunities

[Populated dataset and annual templates](<C:/Users/scelik/OneDrive - Tilburg University/TRACE3Code/reports/cdp_extraction/cdp_section_extraction_templates/risks_opportunities/README.md>) cover assessment processes, risk and opportunity details, financial effects, responses and negative branches. The accompanying validation and provenance files are in `risk_opportunity_support`.

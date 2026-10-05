# TRACE3Code Project

A comprehensive Python project for analyzing multiple ESG data sources: CDP, FactSet, and Trucost.

## Project Overview

This project integrates and analyzes multiple corporate ESG data sources:

### CDP Data (2010-2025)
- **Climate Change (ISIN and non-ISIN)**: Corporate climate change disclosures and responses
- **Biodiversity (ISIN and non-ISIN)**: Biodiversity-related disclosures and commitments

### FactSet Data
- **Supply Chain Relationships**: Supply chain network analysis and entity relationships
- **Entity Data**: Company reference information and identifiers
- **Hub Data**: Financial and operational metrics
- **Symbol Data**: Security identifiers (ISIN, CUSIP, ticker symbols)

### Trucost Data (via WRDS)
- **GHG Data**: Greenhouse gas emissions data (2011-2024)
- **Non-GHG Data**: Environmental cost and impact metrics (2011-2024)

## Data Sources

### Primary Paths

**CDP Data**: `C:\Users\scelik\OneDrive - Tilburg University\Desktop\TRACE3\Data\CDP`

**FactSet Data**: `C:\Users\scelik\OneDrive - Tilburg University\Desktop\TRACE3\Data\FactSet`

**Trucost Data**: `C:\Users\scelik\OneDrive - Tilburg University\Desktop\TRACE3\Data\Trucost (Access through WRDS)`

### CDP Structure

```
CDP/
├── 2010-2025/ (Year-organized folders)
│   ├── RD.U.002.01 - Climate Change (isin)/
│   │   ├── *.xlsx (Excel data files)
│   │   └── *.parquet (Parquet data files)
│   ├── RD.U.002.02 - Climate Change (noisin)/
│   ├── RD.U.002.07 - Biodiversity (isin)/
│   ├── RD.U.002.08 - Biodiversity (noisin)/
│   └── *_RawDataGlossary_*.xlsx (Data dictionary)
├── CDP Questionnaire Changes Documents/
├── CDP Questionnaires/
└── [Various documentation files]
```

### FactSet Structure

```
FactSet/
├── ent_scr_* (Entity Scorecard data)
├── ent_supply_chain_* (Supply chain relationships)
├── ref_* (Reference data)
├── sym_* (Security symbols and identifiers)
│   ├── sym_cusip_* (CUSIP identifiers)
│   ├── sym_isin_* (ISIN identifiers)
│   ├── sym_ticker_* (Ticker symbols)
│   └── sym_entity_* (Entity relationships)
└── [Documentation PDFs]
```

### Trucost Structure

```
Trucost/
├── 260710 trucost pulic-ghg-2011to24.csv (GHG emissions data)
├── 260710 trucost pulic-ghg-2011to24.dta (Same as CSV in Stata format)
├── 260710 trucost pulic-nonghg-2011to24.csv (Non-GHG environmental metrics)
└── 260710 trucost pulic-nonghg-2011to24.dta (Same as CSV in Stata format)
```

## Project Structure

```
CDP-Data-Analysis/
├── README.md (this file)
├── SETUP.md (quick start guide)
├── requirements.txt
├── .gitignore
├── notebooks/
│   ├── 01_data_exploration.ipynb
│   ├── 02_climate_analysis.ipynb
│   ├── 03_biodiversity_analysis.ipynb
│   ├── 04_temporal_trends.ipynb
│   └── 05_factset_trucost_analysis.ipynb (NEW!)
├── src/
│   ├── data_loader.py (CDP, FactSet, Trucost loaders)
│   ├── data_processor.py
│   └── utils.py
├── data/
│   ├── raw/ (Links to source data)
│   ├── processed/ (Cleaned data exports)
│   └── outputs/ (Analysis results)
└── docs/
    ├── data_dictionary.md
    ├── analysis_notes.md
    └── methodology.md
```

## Setup Instructions

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Data Path

Update the data path in your notebooks or scripts to point to:
```
C:\Users\scelik\OneDrive - Tilburg University\Desktop\TRACE3\Data\CDP
```

### 3. Launch Jupyter

```bash
jupyter notebook
```

Then open notebooks from the `notebooks/` folder.

## Key Analysis Areas

### Missing-data audit report

Run the LSEG/Trucost audit from any working directory with:

```bash
py src\audit.py
```

The command writes detailed CSVs, a log, and a print-friendly HTML report to
`reports\missing_analysis\missing_data_report.html`. The report includes a
latest-year gap ranking, completeness trends, policy-coverage heatmap, and
cross-source ISIN overlap when both extracts contain ISINs. Use
`--start-year`, `--end-year`, `--lseg-path`, `--trucost-path`, or `--out` to
run a scoped audit or point to replacement extracts.

```bash
py src\supply_chain_emissions_detail.py --factset_id <ID> --build_both
```

```bash
py src\extract_cdp_org_answers_2014_2024.py --factset-id "000VJS-E" --start-year 2014 --end-year 2024
```

```bash
py src\extract_cdp_org_answers_2014_2024.py --org-name "ASM International" --start-year 2014 --end-year 2024
```

### CDP Analysis
- **Temporal Analysis**: Track disclosure trends over 2010-2025
- **Climate Change**: Corporate commitments, targets, and emissions data
- **Biodiversity**: Conservation initiatives and impact assessments
- **Geographic Distribution**: Regional patterns in disclosures
- **Sector Analysis**: Industry-specific trends

### FactSet Analysis
- **Supply Chain Networks**: Entity relationships and supply chain structures
- **Company Hierarchies**: Parent-subsidiary relationships
- **Entity Resolution**: Matching entities across datasets
- **Supplier-composition clustering**: Categorize companies by the weighted
  industry mix of their suppliers instead of by the companies' own industries:

```bash
py src\supplier_composition_clustering.py --clusters 8 --min-suppliers 3
```

This writes long and wide company composition tables, company cluster
assignments, and cluster profiles under
`data\processed\supplier_composition`. The default weighting uses FactSet
`REVENUE_PCT` when available and equal weights when a company has no reported
relationship percentages. `REVENUE_PCT` is a supply-chain importance proxy, not
verified procurement spend; use `--weighting equal` when that distinction is
not suitable.

### Trucost Analysis
- **Emissions Trends**: GHG emissions patterns (2011-2024)
- **Environmental Costs**: Non-GHG environmental impact metrics
- **Longitudinal Tracking**: Company-level emission changes over time
- **Comparative Analysis**: Cross-company environmental performance

### Integration Analysis
- **Multi-source Matching**: Link CDP, FactSet, and Trucost data
- **Holistic ESG Profiles**: Combine voluntary (CDP) and quantitative (Trucost) metrics
- **Validation Checks**: Cross-validate metrics across sources
- **Supply Chain ESG**: Analyze ESG through supply chain networks

## CDP initiative coding and sector labels

The development review in `data\outputs\cdp_field_chunks_minilm_development`
uses `src\data_engine\cdp_initiative_review.json` for evidence-linked suggestions
for the 182 nonblank initiative comments (`longitudinal_initiative` and
`q7_55_2`). Reproduce it from the repository root with:

```powershell
python src\data_engine\review_cdp_initiatives.py
```

`coding_candidates.jsonl` contains revised initiative suggestions with exact
character offsets into `fields.jsonl`; other datasets retain their original
retrieval suggestions. `coding_template.csv` is populated with one row per
suggested code, still **pending human review**. Enter a reviewer ID and change
the status to `accepted` only after checking the evidence. Nonblank template
work is preserved on reruns, including pending edits. To refresh a field's
suggestions, clear its code, evidence, notes and reviewer fields and set its
status to `pending`.

`initiative_cluster_labels.csv` provides canonical action names and grouping
keys. Use `initiative_cluster_key` to group the same mechanism across sectors,
or `sector_initiative_cluster_key` to group within a reported CDP industry.
These are suggested categorical groupings, **not newly fitted model clusters**
or matches between named initiative entities. Multiple codes can describe one
initiative; count distinct `field_id` values when counting initiatives.

`sector_label` uses the broad **reported CDP primary industry**, joined by exact
source record, company and year. Detailed `primary_sector_reported` remains
separate because it is not consistently available across years. Missing
classifications stay `unknown` and have no sector-specific grouping key.
`reported_initiative_name` preserves the original selection even when it
conflicts with the comment. Short comments without a supported mechanism are
flagged `insufficient_information`, not assigned a guessed action.

The expanded codebook distinguishes lighting, HVAC, IT efficiency, solar
generation, renewable procurement, fleet electrification, heat recovery and
other mechanisms. Parent codes support broader groupings. Codes do not imply
that an initiative is completed or that projected savings were realised.
Original candidates, template and codebook are retained as `*.original.*`;
original similarities still refer to that archived codebook. Revised
suggestions have no invented similarity scores. Embeddings, fitted clusters,
benchmark metrics and experiment metadata are unchanged.
`initiative_review_summary.json` records coverage, provenance and limitations.
Both training and holdout comments in this development sample informed the
vocabulary; use a separate untouched sample to evaluate coding accuracy.

### Sector-specific model clusters

The full field-separated sample now has a separate sector-specific clustering
stage, described in `reports\cdp_field_chunking_workflow.tex`. Using the configured
project Python environment:

```powershell
python src\data_engine\cluster_cdp_fields_by_sector.py
```

This reuses the full run in `data\outputs\cdp_field_chunks_20261001` and writes
`data\outputs\cdp_field_chunks_sector_specific_20261001`. Models are fitted
separately by dataset, source field and reported CDP primary industry.
Complete-text embeddings are combined with training-only TF-IDF words and
bigrams; cluster counts are selected per sector with minimum text/company
support instead of imposing twelve clusters everywhere.

Use the new `cluster_assignments.csv` and `cluster_summary.csv` for sector-specific
model groups and names, and `representative_fields.csv` to inspect their meaning.
For the finer **sector + reviewed mechanism** groups, use
`initiative_specific_groups.csv` and `initiative_specific_group_summary.csv`.
These keep IT efficiency separate from paper reduction even if a learned topic
mixes them. They are overlapping, evidence-guided categories, not additional
fitted models; `specific_initiative_group_ids` links them from the assignment table.
Missing-sector, sparse, blank and unsupported records have explicit unclustered
statuses. Reviewed initiative codes remain separate pending suggestions: they
do not train the model or get propagated to unreviewed cluster members.
`cohort_metrics.csv`, `granularity_search.csv` and saved models provide the
selection diagnostics and reproducibility details. Original model outputs and
human coding work are not overwritten.

## CDP section encoder benchmark, 2020-2025

`src\data_engine\benchmark_cdp_sections.py` runs the four-encoder comparison on
the targets/performance, risks/opportunities and engagement section datasets.
Use the configured project Python environment with the installed encoder
dependencies and pinned local model weights:

```powershell
python src\data_engine\benchmark_cdp_sections.py --stage all
```

The output is `data\outputs\cdp_sections_benchmark_2020_2025`.
The exact-field registry currently contains **329,994 nonblank narrative fields**
and **248,101 distinct texts** from 2020-2025. A matched sample of 768 fields
across 16 sector/field cohorts compares MiniLM, E5-base, BGE-M3 and Qwen3-0.6B.
Connected company identifiers remain together across years and across
train/selection/verification splits. Selection uses common evaluation spaces;
the locked winner is checked on separate verification companies. An inconclusive
verification is reported as a provisional operational choice, not superiority.

Stages `prepare`, `encode`, `evaluate`, `figures`, `deploy` and `report` can be resumed
individually. Full deployment embeds every eligible exact text, reusing the
cache; it is not a TF-IDF surrogate. It is potentially a long CPU job.
`full\progress.json` reports progress; only `full\completion.json` establishes
full completion. Do not run concurrent encoders against the same cache.

Generate the completed-benchmark comparison figures without restarting full
deployment:

```powershell
python src\data_engine\benchmark_cdp_sections.py --stage figures
```

Vector PDFs and preview PNGs in `data\outputs\cdp_sections_benchmark_2020_2025\figures`
compare selection/verification scores, sector-field cohorts, complete text versus
truncated prefixes, and measured CPU time/truncation. Scores **include the -1
penalty** for undefined or unsupported partitions; the ablation chart shows how
many cohorts produced defined silhouettes. The figures are embedded in the
manuscript and do not assert human coding accuracy or completed full clustering.

The automatically updated manuscript is
`reports\cdp_sections_encoder_benchmark_msom.tex`. It is an anonymous,
MSOM-oriented methodological draft and explicitly marks missing results.
It does not claim human coding accuracy or publication-ready validation.
The 82-code section vocabulary includes engagement mechanisms; all generated
code/span suggestions remain pending human review. Environmental-unspecified
answers and missing/invalid sectors retain explicit flags.

## CDP item-level classification benchmark

The validated workbook
`data\processed\cdp_section_datasets\cdp_classification_all_details.xlsx`
defines the item-level output contract. One answer may produce several rows.
Reduction, engagement, risk and opportunity use separate schemas, matching the
four detail sheets in the workbook exactly.

Extract the labels and validate the workbook before a benchmark run:

```powershell
python src\data_engine\cdp_detail_output.py extract-validation `
  --workbook data\processed\cdp_section_datasets\cdp_classification_all_details.xlsx `
  --output data\processed\cdp_section_datasets\cdp_validation_detail_labels.jsonl.gz `
  --contract data\processed\cdp_section_datasets\cdp_detail_output_contract.json
```

The command creates 256 answer records and 972 validated item records. Six
reduction answers contain no identifiable reduction measure and therefore have
no action row. Engagement, risk and opportunity retain context rows when no
core item is supported.

`benchmark_cdp_detail_models.py` works with any OpenAI-compatible
chat-completions endpoint. For a local Ollama endpoint, start Ollama and make
the required models available, then run a small smoke test:

```powershell
$env:CDP_LLM_API_KEY = "ollama"
python src\data_engine\benchmark_cdp_detail_models.py `
  --base-url http://localhost:11434/v1 `
  --models <local-model-name> `
  --limit 8 `
  --output data\outputs\cdp_detail_model_benchmark_smoke
```

If the endpoint does not accept `response_format`, add
`--no-response-format`. After the smoke test succeeds, run the complete
company-grouped five-fold benchmark:

```powershell
python src\data_engine\benchmark_cdp_detail_models.py `
  --base-url http://localhost:11434/v1 `
  --models <model-one> <model-two> <model-three> `
  --folds 5 `
  --examples 2 `
  --output data\outputs\cdp_detail_model_benchmark
```

For another compatible endpoint, change `--base-url` and place its API key in
the environment variable named by `--api-key-env`. The benchmark is resumable:
each completed answer is appended to the model's checkpoint and is skipped on
the next run.

`model_comparison.csv` reports schema-validity, item precision/recall/F1,
item-count error, verbatim-evidence rate and field accuracy by response type
and industry. Each model directory also contains `detail_csv`, whose four
compressed CSV files use the exact headers and column order of Reduction
actions, Engagement details, Risk details and Opportunity details.

## Requirements

- Python 3.8+
- pandas
- openpyxl (for Excel files)
- pyarrow (for Parquet files)
- matplotlib/seaborn (for visualization)
- jupyter (for notebooks)

## Next Steps

1. Explore the data using the notebooks
2. Load and examine the glossary/data dictionary
3. Clean and standardize data for analysis
4. Develop custom analysis workflows
5. Generate visualizations and reports

## Notes

- Data files are large (Parquet format recommended for efficiency)
- ISIN versions contain company ticker information; non-ISIN versions are anonymized
- Multiple response types per company per year are possible

---

Last Updated: 2026-08-18

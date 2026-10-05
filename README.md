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
src/
├── dataset_readers/       # CDP, FactSet, LSEG and Trucost readers/integration
├── cdp_extraction/        # CDP answer extraction and dataset preparation
├── cdp_classification/    # Supervised CDP text coding and benchmarks
├── MDP/                   # MDP state-variable analysis
├── audit.py               # Cross-source missing-data audit
├── supply_chain_emissions_detail.py
├── target_emissions_profile.py
└── utils.py
```

See [`src/README.md`](src/README.md) for package details and the recommended
command-line invocation pattern.

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
py -m src.cdp_extraction.extract_cdp_org_answers_2014_2024 --factset-id "000VJS-E" --start-year 2014 --end-year 2024
```

```bash
py -m src.cdp_extraction.extract_cdp_org_answers_2014_2024 --org-name "ASM International" --start-year 2014 --end-year 2024
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
py -m src.dataset_readers.supplier_composition_clustering --clusters 8 --min-suppliers 3
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

## CDP supervised text classification

The active text-mining workflow uses predefined, validated labels for
reduction actions, risks, opportunities, and engagement activities. The
models are evaluated separately for each response type using company-grouped
out-of-fold validation. This prevents records from the same company from
appearing in both training and test folds.

The validation workbook is
`data\processed\cdp_section_datasets\cdp_classification_all_details.xlsx`.
The second reduction-training round is stored in
`data\raw\CDP\cdp_reduction_training_round_2_validated.xlsx`.

Run the workflow from PowerShell:

```powershell
.\scripts\run_cdp_classification.ps1 -Task prepare-reduction
.\scripts\run_cdp_classification.ps1 -Task encode-reduction -Device cpu -Offline
.\scripts\run_cdp_classification.ps1 -Task benchmark-reduction
.\scripts\run_cdp_classification.ps1 -Task benchmark-other
```

See [`CDP_CLASSIFICATION.md`](CDP_CLASSIFICATION.md) for the package layout,
model environment, and output locations. The earlier unsupervised clustering
and BERTopic experiments have been removed from the active source tree.

## Requirements
- Python 3.8+
- pandas
- openpyxl (for Excel files)
- pyarrow (for Parquet files)
- matplotlib/seaborn (for visualization)
- jupyter (for notebooks)



Last Updated: 2026-10-05

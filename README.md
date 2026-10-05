# TRACE3Code Project

A Python research project for integrating CDP, FactSet, LSEG, and S&P Global
Trucost data to study corporate emissions, supply chains, and decarbonisation
decisions.

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

### LSEG Data
- **Firm characteristics**: Revenue, profitability, employment, and industry classifications
- **Sustainability indicators**: ESG scores, environmental policies, targets, and governance measures

### Trucost Data (via WRDS)
- **Current research extract**: `trucost_2026_2015_onward.csv.gz`, filtered from `trucost_2026_new.dta`
- **GHG measures**: Absolute and intensity measures for Scope 1, location- and market-based Scope 2, and upstream and downstream Scope 3
- **Analysis window**: The maintained integration pipeline targets fiscal years 2015–2025

## Data Sources

### Primary Paths

Paths are resolved relative to the repository root:

- **CDP**: `data/raw/CDP`
- **FactSet**: `data/raw/FactSet`
- **LSEG**: `data/raw/LSEG/lseg_full_universe.csv`
- **Trucost**: `data/raw/Trucost (Access through WRDS)`

The large licensed source files are local inputs and are not expected to be
stored in Git.

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
├── trucost_2026_new.dta                  # Full 2026 WRDS delivery
├── trucost_2026_2015_onward.csv.gz       # Preferred filtered research input
├── trucost_environmental_data_item_list.xlsx
├── 260710 trucost pulic-ghg-2011to24.*    # Earlier GHG extract
└── 260710 trucost pulic-nonghg-2011to24.* # Earlier non-GHG extract
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
└── utils.py
```

See [`src/README.md`](src/README.md) for package details and the recommended
command-line invocation pattern.

## Data readers and integration

The maintained integration entry point is
[`src/dataset_readers/common_companies_by_year.py`](src/dataset_readers/common_companies_by_year.py).
It reads Trucost and LSEG in chunks, resolves company identifiers, matches
FactSet entities, and optionally adds CDP records. Expensive Trucost–LSEG–
FactSet matches are cached in
`data/processed/trucost_lseg_factset_matched_2015_2025.csv.gz`.

| Module | Role |
| --- | --- |
| `common_companies_by_year.py` | Maintained cross-source matching and panel construction command |
| `common_company_names_for_year.py` | Inspect matched company names for one year |
| `cdp_read.py` | Shared parsers for legacy CDP Excel files and recent Parquet extracts |
| `cdp_reader.py` | Export one organization's CDP answers across years |
| `cdp_theme_taxonomy.py` | Shared mapping from CDP questions and text to climate themes |
| `lseg_esg_extract_api.py` | Refresh the local LSEG ESG extract through the LSEG API |
| `company_panel_persistence.py` | Measure continuous company coverage across sources |
| `plot_company_year_venn.py` | Report annual overlap among CDP, FactSet, LSEG, and Trucost |
| `supplier_factset_lseg_analysis.py` | Construct supplier characteristics from FactSet and matched ESG/emissions data |
| `supplier_composition_clustering.py` | Build supplier-sector composition groups |
| `report_builder.py` | Shared data access for company-level emissions reports |
| `target_emissions_profile.py` | Command-line wrapper for company emissions-profile reports |

Build the default 2015–2025 Trucost–LSEG–FactSet panel:

```powershell
python -m src.dataset_readers.common_companies_by_year --refresh-matched-panel-cache
```

Subsequent runs reuse the cache unless the refresh flag is supplied. Other
supported operations include:

```powershell
# Build the 2016–2025 CDP–Trucost–FactSet intersection.
python -m src.dataset_readers.common_companies_by_year --build-cdp-trucost-factset-common

# Build the four-source climate panel.
python -m src.dataset_readers.common_companies_by_year --build-cdp-climate-panel

# Add separate location- and market-based Scope 2 values to the cache.
python -m src.dataset_readers.common_companies_by_year --refresh-cached-trucost-scope-2

# Extract one organization's CDP answers.
python -m src.dataset_readers.cdp_reader --org-name "ASM International" --start-year 2016 --end-year 2025
```

### Trucost fields used by the maintained reader

The preferred filtered Trucost file contains 37 columns. The integration
pipeline selects company identifiers, fiscal year, reporting date, industry,
revenue, and the following emissions measures:

| Measure | Trucost field |
| --- | --- |
| Revenue | `di_319522` |
| Scope 1 absolute emissions | `di_319413` |
| Scope 2 location-based absolute emissions | `di_319414` |
| Scope 2 market-based absolute emissions | `di_367750` |
| Scope 3 upstream absolute emissions | `di_319415` |
| Scope 3 downstream absolute emissions | `di_326737` |
| Scope 1 intensity | `di_319407` |
| Scope 2 location-based intensity | `di_319408` |
| Scope 2 market-based intensity | `di_368314` |
| Scope 3 upstream intensity | `di_319409` |
| Scope 3 downstream intensity | `di_326738` |

Absolute emissions are measured in metric tons of carbon dioxide equivalent.
The code retains location- and market-based Scope 2 as separate measures;
`scope_2_emissions` remains an alias for the location-based value for
compatibility with earlier outputs. `suppliers_emissions` is an alias for
upstream Scope 3 and does not allocate a supplier's emissions to an individual
buyer.

## Setup Instructions

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Add licensed source data

Place source files under `data/raw/<source>`. The maintained readers resolve
these paths from the repository root. Command-line options can override CDP
and output paths when needed.

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
- **Emissions trends**: Scope-specific GHG emissions over the 2015–2025 research window
- **Alternative Scope 2 accounting**: Separate location- and market-based measures
- **Value-chain emissions**: Separate upstream and downstream Scope 3 measures
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

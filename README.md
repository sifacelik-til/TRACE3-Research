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

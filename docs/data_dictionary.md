# Data Dictionary and Metadata

## TRACE3 Data Sources Overview

This project integrates three major ESG/corporate data sources:

1. **CDP** - Voluntary corporate climate and biodiversity disclosures
2. **FactSet** - Supply chain networks and entity relationships
3. **Trucost** - Quantified environmental metrics (via WRDS)

---

## CDP Data Structure Overview

### Directory Organization

The CDP data is organized hierarchically by year and topic:

```
CDP/
├── 2010-2025/
│   ├── RD.U.002.01 - Climate Change (isin)
│   ├── RD.U.002.02 - Climate Change (noisin)
│   ├── RD.U.002.07 - Biodiversity (isin)
│   ├── RD.U.002.08 - Biodiversity (noisin)
│   └── *_RawDataGlossary_*.xlsx
├── CDP Questionnaire Changes Documents
├── CDP Questionnaires
└── [Supporting documents]
```

### File Types

| Extension | Format | Description | Tool |
|-----------|--------|-------------|------|
| .xlsx | Excel Spreadsheet | Main data tables | pandas.read_excel() |
| .parquet | Apache Parquet | Columnar data (compressed) | pandas.read_parquet() |
| .pdf | PDF Documents | Documentation, questionnaires | - |

### ISIN vs Non-ISIN Versions

- **ISIN**: Data includes company identifiers (ticker symbols, ISIN codes)
- **Non-ISIN**: Anonymized version without company identification

Choose ISIN version when:
- You need company-level analysis
- Creating company profiles or comparisons

Choose Non-ISIN version when:
- Working with aggregated sector/geographic data
- Doing trend analysis without company identification

## Common Column Patterns

### Climate Change Data

Expected columns may include:
- Company identifiers (ISIN version only)
- Year of disclosure
- Emissions data (Scope 1, 2, 3)
- Climate targets and commitments
- Renewable energy usage
- Climate governance information

### Biodiversity Data

Expected columns may include:
- Company identifiers (ISIN version only)
- Biodiversity impacts assessment
- Conservation activities
- Supply chain biodiversity considerations
- Biodiversity targets
- Regulatory compliance information

## Data Quality Notes

- **MISSING VALUES**: Expected in some columns (not all companies report all metrics)
- **DUPLICATES**: Possible for companies with multiple responses
- **INCONSISTENT FORMATS**: Field definitions may evolve over years
- **ENCODING**: Files typically use UTF-8 encoding

## How to Use the Data Glossary

1. Open the `*_RawDataGlossary_*.xlsx` file for a specific year
2. Refer to field definitions before analysis
3. Note data type conversions (e.g., percentage strings to floats)
4. Check unit information for numeric fields

## Loading Data with Metadata

```python
from data_engine.data_loader import CDPDataLoader

loader = CDPDataLoader()

# Get year range
years = loader.get_year_folders()  # Returns [2010, 2011, ..., 2025]

# Load climate data for 2024
climate_data = loader.load_year_data(2024, category="climate")

# Access individual datasets
df_climate_isin = climate_data.get('climate_isin_full_extract_...')
```

## Tips for Data Analysis

1. **Start with latest year**: 2024 data is most complete and standardized
2. **Compare across versions**: ISIN vs non-ISIN for company vs. aggregate analysis
3. **Use Parquet for large files**: Better performance than Excel for data > 100MB
4. **Document transformations**: Keep track of data cleaning steps
5. **Verify assumptions**: Check glossary for field meanings before analysis

---

## FactSet Data Structure and Loading

### Overview

FactSet provides:
- **Supply Chain Relationships**: Network of companies, suppliers, and customers
- **Entity Data**: Company reference information and hierarchies
- **Symbol Mappings**: ISIN, CUSIP, ticker, and other security identifiers
- **Reference Data**: Calendar, hub, and metadata information

### Organization

Data is stored in folders named with patterns like:
- `sym_ticker_v1_full_13697`: Security symbols (ticker)
- `sym_isin_v1_full_11256`: Security symbols (ISIN)
- `ent_supply_chain_v1_full_3856`: Supply chain relationships
- `ref_hub_v2_full_3565`: Reference hub data

Each folder contains multiple tab-delimited text files (.txt).

### File Format

- **Delimiter**: Tab (\t)
- **Encoding**: UTF-8
- **Header**: Column headers in first row
- **Size**: Large files split across multiple .txt files per folder

### Loading FactSet Data

```python
from data_engine.data_loader import FactSetDataLoader

fs_loader = FactSetDataLoader()

# List available categories
categories = fs_loader.get_categories()  # ['sym', 'ent', 'ref', ...]

# Load all files from a category (e.g., symbol data)
symbol_data = fs_loader.load_category('sym_entity', encoding='utf-8')

# Load a specific folder (all files concatenated)
supply_chain = fs_loader.load_folder('ent_supply_chain_v1_full_3856')
```

### Common Use Cases

**Entity Linking:**
- Use `sym_entity` to link ISINs, tickers, and entity IDs
- Useful for matching companies across datasets

**Supply Chain Analysis:**
- `ent_supply_chain_v1_full_3856`: Supplier-customer relationships
- `ent_supply_chain_parent_v1_full_3860`: Parent-subsidiary relationships
- Enables supply chain ESG tracing

**Company Hierarchies:**
- Identify corporate structures
- Track ownership relationships
- Analyze consolidated vs. standalone entities

### Data Quality Notes

- **Large Files**: May be split into parts for manageability
- **Identifiers**: Multiple identifier types per company
- **Relationships**: May have time-dependent validity
- **Updates**: Data reflects state at time of export

---

## Trucost Data Structure and Loading

### Overview

Trucost provides quantified environmental metrics accessed through WRDS:
- **GHG Emissions**: Scope 1, 2, 3 emissions data (2011-2024)
- **Non-GHG Environmental Metrics**: Water use, waste, environmental costs
- **Company-Level Data**: Annual metrics by company
- **WRDS Access**: Data maintained via Wharton Research Data Services

### File Structure

```
Trucost/
├── 260710 trucost pulic-ghg-2011to24.csv
├── 260710 trucost pulic-ghg-2011to24.dta
├── 260710 trucost pulic-nonghg-2011to24.csv
└── 260710 trucost pulic-nonghg-2011to24.dta
```

### File Formats

| Format | Description | Tool |
|--------|-------------|------|
| .csv | Comma-separated values | pandas.read_csv() |
| .dta | Stata format | pandas.read_stata() |

**Note**: CSV and .dta versions contain identical data; choose format based on preference.

### Data Coverage

- **Time Period**: 2011-2024 (13 years)
- **GHG Data**: Scope 1, 2, and 3 emissions
- **Non-GHG Data**: Water, waste, environmental costs
- **Company-Year Observations**: Multiple years per company

### Loading Trucost Data

```python
from data_engine.data_loader import TrucostDataLoader

trucost_loader = TrucostDataLoader()

# Check available files
files = trucost_loader.get_available_files()

# Load GHG data (CSV or Stata format)
ghg_df = trucost_loader.load_ghg_data(file_type='csv')

# Load non-GHG data
nonghg_df = trucost_loader.load_nonghg_data(file_type='csv')

# Load all Trucost data
all_data = trucost_loader.load_all_data(file_type='csv')
```

### Common Columns (GHG Data)

Typical columns may include:
- Company identifier (name, ticker, ISIN, Permid, etc.)
- Year
- Scope 1 Emissions
- Scope 2 Emissions (Location/Market-based)
- Scope 3 Emissions
- Total Emissions
- Emissions intensity metrics

### Common Columns (Non-GHG Data)

Typical columns may include:
- Company identifier
- Year
- Water consumption
- Waste generation
- Waste recycling
- Environmental costs
- Regulatory fines/penalties
- Etc.

### Data Quality Notes

- **Missing Values**: Not all metrics available for all companies/years
- **Scope 3 Challenges**: More difficult to quantify, higher uncertainty
- **Intensity Metrics**: May be calculated by Trucost or provider
- **Validation**: Cross-check with company disclosures (CDP)
- **WRDS Standardization**: Data standardized and checked by Wharton

### Linking Trucost to Other Data

Use company identifiers for matching:
- **Permid**: Refinitiv permanent identifier (most reliable)
- **Ticker**: Stock exchange ticker (check for changes over time)
- **ISIN**: International Security Identification Number
- **Company Name**: Last resort (subject to name changes)

---

## Multi-Source Data Integration

### Key Linking Fields

| Data Source | Primary ID | Secondary IDs |
|-------------|-----------|---|
| CDP | Company Name, ISIN | Ticker, Non-ISIN ID |
| FactSet | Entity ID (Permid) | ISIN, CUSIP, Ticker |
| Trucost | Permid (if available) | Ticker, ISIN, Company Name |

### Integration Challenges

1. **Company Name Variations**: "Microsoft" vs "Microsoft Corp" vs "MSFT"
2. **ISIN Changes**: Companies may have multiple ISINs (bonds vs equity)
3. **Ticker Changes**: Different exchanges, delistings, ticker changes
4. **Time-Sensitivity**: Relationships and identifiers change over time
5. **Duplicate Entries**: Same company appears multiple times in raw data

### Best Practices

1. **Fuzzy Matching**: Use company name similarity for initial linking
2. **Permid Matching**: FactSet Permid is most reliable linking key
3. **Multiple Identifiers**: Cross-validate using multiple IDs
4. **Temporal Tracking**: Track changes in identifiers over time
5. **Validation**: Manually check sample matches before bulk integration

---

For more information, refer to the official documentation in the respective data folders.


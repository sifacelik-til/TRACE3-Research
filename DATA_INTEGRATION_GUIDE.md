# TRACE3Code Data Integration Guide

## Summary of Changes

The TRACE3Code project has been enhanced to include **FactSet** and **Trucost** data sources alongside CDP, enabling comprehensive multi-source ESG analysis.

---

## What Was Added

### 1. Enhanced Data Loader (`src/data_engine/data_loader.py`)

Added two new loader classes:

#### **FactSetDataLoader**

```python
from data_engine.data_loader import FactSetDataLoader

fs_loader = FactSetDataLoader()

# List available categories
categories = fs_loader.get_categories()  # e.g., ['sym', 'ent', 'ref']

# Load supply chain data
supply_chain = fs_loader.load_folder('ent_supply_chain_v1_full_3856')

# Load specific category (all files)
entity_data = fs_loader.load_category('sym_entity')
```

**Methods:**
- `get_categories()` - List data categories
- `list_folders()` - List all available folders
- `load_category(category)` - Load all files for a category
- `load_folder(folder_name)` - Load and concatenate all files from a folder

#### **TrucostDataLoader**

```python
from data_engine.data_loader import TrucostDataLoader

trucost_loader = TrucostDataLoader()

# Get available files
files = trucost_loader.get_available_files()

# Load GHG data
ghg = trucost_loader.load_ghg_data(file_type='csv')

# Load non-GHG data
nonghg = trucost_loader.load_nonghg_data(file_type='csv')

# Load all data
all_data = trucost_loader.load_all_data()
```

**Methods:**
- `get_available_files()` - List CSV and Stata files
- `load_ghg_data(file_type)` - Load emissions data
- `load_nonghg_data(file_type)` - Load environmental metrics
- `load_all_data(file_type)` - Load all Trucost files

### 2. New Analysis Notebook

**05_factset_trucost_analysis.ipynb** provides:
- FactSet data exploration and loading examples
- Trucost emissions data analysis
- Multi-source data integration patterns
- Templates for supply chain analysis
- Examples of linking data across sources

### 3. Updated Documentation

#### **README.md**
- Added FactSet and Trucost to project overview
- Updated data sources section with all three sources
- Added file structure for each data source
- Expanded analysis areas for multi-source work

#### **data_dictionary.md**
- Complete FactSet data structure documentation
- Trucost data coverage and fields reference
- Multi-source integration best practices
- Data linking and matching strategies

#### **SETUP.md**
- Updated notebook list with new Notebook 05
- Added all three data sources with paths
- Expanded code examples for all loaders
- Updated workflow to include data linking

---

## Data Source Details

### FactSet
- **Location**: `C:\Users\scelik\OneDrive - Tilburg University\Desktop\TRACE3\Data\FactSet`
- **Format**: Tab-delimited text files (.txt)
- **Key Folders**:
  - Supply chain: `ent_supply_chain_v1_full_3856`
  - Entity links: `sym_entity_v1_full_12328`
  - Symbols: `sym_ticker_v1_full_13697`, `sym_isin_v1_full_11256`
- **Use Cases**: Supply chain analysis, entity linking, company hierarchies

### Trucost (WRDS)
- **Location**: `C:\Users\scelik\OneDrive - Tilburg University\Desktop\TRACE3\Data\Trucost (Access through WRDS)`
- **Format**: CSV and Stata (.dta)
- **Files**:
  - `260710 trucost pulic-ghg-2011to24.csv` - Emissions data
  - `260710 trucost pulic-nonghg-2011to24.csv` - Environmental metrics
- **Coverage**: 2011-2024 (13 years)
- **Use Cases**: Emissions analysis, environmental costs, trend tracking

---

## Quick Start Examples

### Load FactSet Supply Chain Data

```python
import sys

sys.path.insert(0, 'src')
from data_engine.data_loader import FactSetDataLoader

fs_loader = FactSetDataLoader()
supply_chain = fs_loader.load_folder('ent_supply_chain_v1_full_3856')

print(f"Supply chain data shape: {supply_chain.shape}")
print(f"Columns: {supply_chain.columns.tolist()}")
```

### Load Trucost Emissions Data

```python
from data_engine.data_loader import TrucostDataLoader

trucost_loader = TrucostDataLoader()
ghg = trucost_loader.load_ghg_data(file_type='csv')

print(f"GHG data shape: {ghg.shape}")
print(f"Year range: {ghg['year'].min()}-{ghg['year'].max()}")
```

### Integrate CDP and Trucost

```python
from data_engine.data_loader import CDPDataLoader, TrucostDataLoader

# Load CDP data
cdp_loader = CDPDataLoader()
cdp_2024 = cdp_loader.load_year_data(2024)

# Load Trucost data
trucost_loader = TrucostDataLoader()
trucost = trucost_loader.load_ghg_data()

# Link by company identifier (example)
# merged = cdp_2024.merge(trucost, on='company_id', how='inner')
```

---

## Key Differences Between Data Sources

| Feature | CDP | FactSet | Trucost |
|---------|-----|---------|---------|
| **Type** | Voluntary Disclosure | Network/Reference | Quantified Metrics |
| **Coverage** | Climate & Biodiversity | Supply chains & Entities | GHG & Environmental |
| **Years** | 2010-2025 | Point-in-time | 2011-2024 |
| **Level** | Company | Entity relationships | Company-year |
| **Format** | Excel/Parquet | Tab-delimited text | CSV/Stata |
| **Identifiers** | ISIN (optional) | ISIN, CUSIP, Permid | Name, Ticker, ISIN |

---

## Next Steps

1. **Explore Notebook 05**: Open and run the new analysis notebook
2. **Test Loaders**: Try loading each data source in your notebooks
3. **Link Data**: Use company identifiers to match records across sources
4. **Build Analysis**: Create integrated ESG profiles combining all sources
5. **Export Results**: Save processed data and analysis outputs

---

## Troubleshooting

**Issue**: FactSet text files failing to load
- Check encoding (UTF-8 assumed)
- Verify delimiter is tab (\t)
- Check file exists in specified folder

**Issue**: Trucost .dta files not loading
- Install Stata support: `pip install pyreadstat`
- Verify file not corrupted
- Try CSV version instead

**Issue**: Out of memory with large FactSet folders
- Load files one at a time instead of full folder
- Use `load_category()` to filter by type
- Consider processing in chunks

**Issue**: Company matching across sources failing
- Normalize company names (lowercase, trim whitespace)
- Use Permid from FactSet when available
- Cross-validate with multiple identifiers
- Check time-period overlap

---

## Resources

- **Notebook 05**: `notebooks/05_factset_trucost_analysis.ipynb`
- **Data Dictionary**: `docs/data_dictionary.md`
- **Setup Guide**: `SETUP.md`
- **README**: `README.md`

Enjoy working with your integrated ESG data! 🎉

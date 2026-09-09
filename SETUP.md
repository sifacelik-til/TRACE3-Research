# Getting Started Guide

## 📂 Project Location
```
C:\Users\scelik\Desktop\TRACE3Code
```

## 🚀 Quick Start

### Step 1: Open the Project in VS Code
```bash
code C:\Users\scelik\Desktop\TRACE3Code
```

### Step 2: Install Dependencies
In VS Code terminal:
```bash
pip install -r requirements.txt
```

### Step 3: Start Jupyter Lab
```bash
jupyter lab
```

Then open notebooks from the `notebooks/` folder.

## 📊 Project Contents

### 📓 Notebooks (Start Here!)
Located in: `notebooks/`

1. **01_data_exploration.ipynb** ⭐ START HERE
   - Understand the CDP data structure
   - Load and inspect datasets
   - Get basic statistics

2. **02_climate_analysis.ipynb**
   - Climate change disclosure trends
   - Emissions analysis
   - Climate targets tracking

3. **03_biodiversity_analysis.ipynb**
   - Biodiversity commitments
   - Conservation initiatives
   - Supply chain considerations

4. **04_temporal_trends.ipynb**
   - Long-term trends (2010-2025)
   - Year-over-year changes
   - Growth analysis

5. **05_factset_trucost_analysis.ipynb** 🆕 NEW!
   - FactSet supply chain networks
   - Trucost environmental metrics
   - Multi-source data integration

### 🐍 Python Modules (in `src/`)
- **data_loader.py**: Load CDP, FactSet, and Trucost data
- **utils.py**: Helper functions for analysis and visualization

### 📚 Documentation (in `docs/`)
- **data_dictionary.md**: Field definitions and metadata

## 🔗 Data Source

Your project integrates three ESG data sources:

### CDP Data
```
C:\Users\scelik\OneDrive - Tilburg University\Desktop\TRACE3\Data\CDP
```
- Voluntary climate and biodiversity disclosures (2010-2025)
- Excel and Parquet formats

### FactSet Data
```
C:\Users\scelik\OneDrive - Tilburg University\Desktop\TRACE3\Data\FactSet
```
- Supply chain networks and entity relationships
- Tab-delimited text files
- ~40 folders with different entity/symbol/reference data

### Trucost Data
```
C:\Users\scelik\OneDrive - Tilburg University\Desktop\TRACE3\Data\Trucost (Access through WRDS)
```
- GHG and non-GHG environmental metrics (2011-2024)
- CSV and Stata formats
- Via Wharton Research Data Services (WRDS)

## 💡 Key Features

✅ **Automatic Data Loading**

```python
from data_engine.data_loader import CDPDataLoader, FactSetDataLoader, TrucostDataLoader

# Load CDP data
loader = CDPDataLoader()
data_2024 = loader.load_year_data(2024, category="climate")

# Load FactSet data
fs_loader = FactSetDataLoader()
supply_chain = fs_loader.load_folder('ent_supply_chain_v1_full_3856')

# Load Trucost data
trucost_loader = TrucostDataLoader()
ghg_data = trucost_loader.load_ghg_data(file_type='csv')
nonghg_data = trucost_loader.load_nonghg_data(file_type='csv')
```

✅ **Pre-built Visualization Functions**
```python
from utils import print_data_info, plot_numeric_distributions
print_data_info(df)
plot_numeric_distributions(df)
```

✅ **Support for Multiple File Types**
- Excel (.xlsx) files
- Parquet (.parquet) files
- Raw data glossaries

✅ **Organized Project Structure**
- `data/raw` - Links to source data
- `data/processed` - Your cleaned data
- `data/outputs` - Analysis results

## 🎯 Recommended Workflow

1. **Explore** - Run Notebook 01 to understand the CDP data
2. **Load** - Use appropriate loaders for each data source
3. **Link** - Integrate data across CDP, FactSet, and Trucost
4. **Clean** - Process and standardize data
5. **Analyze** - Run custom analyses in notebooks 02-05
6. **Visualize** - Create plots and charts
7. **Export** - Save results to `data/outputs/`

## 🔍 Example Analysis

```python
import sys

sys.path.insert(0, 'src')
from data_engine.data_loader import CDPDataLoader

loader = CDPDataLoader()

# List available years
years = loader.get_year_folders()
print(f"Available: {years}")

# Load latest climate data
climate_2024 = loader.load_year_data(2024, category="climate")

# Get first dataset
first_key = list(climate_2024.keys())[0]
df = climate_2024[first_key]

# Quick analysis
print(df.info())
print(df.describe())
```

## 📝 Tips

- **Large Files**: Use Parquet files for better performance
- **ISIN Data**: Contains company identifiers
- **Non-ISIN Data**: Anonymized version
- **Glossary**: Check `*_RawDataGlossary_*.xlsx` for field definitions
- **Memory**: Monitor large datasets with `.memory_usage(deep=True)`

## 🛠️ Troubleshooting

**Issue**: Module not found error
- **Solution**: Make sure `sys.path.insert(0, '../src')` is in your notebook

**Issue**: File path errors
- **Solution**: Verify the base data path exists in `data_loader.py`

**Issue**: Missing dependencies
- **Solution**: Run `pip install -r requirements.txt` again

## 📞 Next Steps

1. Open VS Code and load the project
2. Run Notebook 01 to explore the data
3. Modify and extend the notebooks for your analysis
4. Save processed data to `data/processed/`
5. Export final results to `data/outputs/`

Enjoy your data analysis! 🎉

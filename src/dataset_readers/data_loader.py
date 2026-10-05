"""
Data loader module for TRACE3 data analysis.
Handles loading data from CDP, FactSet, and Trucost sources.
Supports Excel, Parquet, CSV, and tab-delimited text files.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Union, Tuple
import pandas as pd
import warnings

warnings.filterwarnings('ignore')


class CDPDataLoader:
    """Load CDP data from various file formats."""
    
    def __init__(self, base_data_path: str = None):
        """
        Initialize the data loader.
        
        Args:
            base_data_path: Root path to CDP data directory
        """
        if base_data_path is None:
            self.base_data_path = r"C:\Users\scelik\OneDrive - Tilburg University\Desktop\TRACE3\Data\CDP"
        else:
            self.base_data_path = base_data_path
            
        if not os.path.exists(self.base_data_path):
            raise ValueError(f"Data path not found: {self.base_data_path}")
    
    def get_year_folders(self) -> List[int]:
        """Get list of available years in the data."""
        years = []
        for item in os.listdir(self.base_data_path):
            if item.isdigit() and len(item) == 4:
                years.append(int(item))
        return sorted(years)
    
    def load_excel_file(self, file_path: str, sheet_name: int = 0) -> pd.DataFrame:
        """
        Load data from Excel file.
        
        Args:
            file_path: Path to Excel file
            sheet_name: Sheet name or index to load
            
        Returns:
            pandas DataFrame
        """
        try:
            df = pd.read_excel(file_path, sheet_name=sheet_name)
            print(f"Loaded: {os.path.basename(file_path)} - Shape: {df.shape}")
            return df
        except Exception as e:
            print(f"Error loading {file_path}: {str(e)}")
            return None
    
    def load_parquet_file(self, file_path: str) -> pd.DataFrame:
        """
        Load data from Parquet file.
        
        Args:
            file_path: Path to Parquet file
            
        Returns:
            pandas DataFrame
        """
        try:
            df = pd.read_parquet(file_path)
            print(f"Loaded: {os.path.basename(file_path)} - Shape: {df.shape}")
            return df
        except Exception as e:
            print(f"Error loading {file_path}: {str(e)}")
            return None
    
    def load_year_data(self, year: int, category: str = "all") -> Dict[str, pd.DataFrame]:
        """
        Load all data files for a specific year.
        
        Args:
            year: Year to load (e.g., 2024)
            category: Data category - "climate", "biodiversity", or "all"
            
        Returns:
            Dictionary with dataframes
        """
        year_path = os.path.join(self.base_data_path, str(year))
        data = {}
        
        if not os.path.exists(year_path):
            print(f"Year {year} not found in data directory")
            return data
        
        # Map categories to folder names
        categories_map = {
            "climate_isin": "RD.U.002.01 - Climate Change (isin)",
            "climate_noisin": "RD.U.002.02 - Climate Change (noisin)",
            "biodiversity_isin": "RD.U.002.07 - Biodiversity (isin)",
            "biodiversity_noisin": "RD.U.002.08 - Biodiversity (noisin)",
        }
        
        if category == "all":
            categories_to_load = categories_map.keys()
        else:
            categories_to_load = [cat for cat in categories_map.keys() if category in cat]
        
        for cat_key, cat_folder in categories_map.items():
            if cat_key not in categories_to_load:
                continue
                
            cat_path = os.path.join(year_path, cat_folder)
            if os.path.exists(cat_path):
                # Try to load files from the category folder
                for file in os.listdir(cat_path):
                    if file.endswith(".xlsx"):
                        file_key = f"{cat_key}_{file.replace('.xlsx', '')}"
                        data[file_key] = self.load_excel_file(os.path.join(cat_path, file))
                    elif file.endswith(".parquet"):
                        file_key = f"{cat_key}_{file.replace('.parquet', '')}"
                        data[file_key] = self.load_parquet_file(os.path.join(cat_path, file))
        
        return data


class FactSetDataLoader:
    """Load FactSet data from tab-delimited text files."""
    
    def __init__(self, base_data_path: str = None):
        """
        Initialize the FactSet data loader.
        
        Args:
            base_data_path: Root path to FactSet data directory
        """
        if base_data_path is None:
            self.base_data_path = r"C:\Users\scelik\OneDrive - Tilburg University\Desktop\TRACE3\Data\FactSet"
        else:
            self.base_data_path = base_data_path
            
        if not os.path.exists(self.base_data_path):
            raise ValueError(f"Data path not found: {self.base_data_path}")
    
    def get_categories(self) -> List[str]:
        """Get list of available FactSet data categories."""
        categories = set()
        for folder in os.listdir(self.base_data_path):
            folder_path = os.path.join(self.base_data_path, folder)
            if os.path.isdir(folder_path):
                # Extract category from folder name (prefix before underscore or number)
                parts = folder.split('_')
                if len(parts) > 0:
                    categories.add(parts[0])
        return sorted(list(categories))
    
    def list_folders(self) -> List[str]:
        """List all available FactSet data folders."""
        folders = []
        for item in os.listdir(self.base_data_path):
            if os.path.isdir(os.path.join(self.base_data_path, item)):
                folders.append(item)
        return sorted(folders)
    
    def load_category(self, category: str, encoding: str = 'utf-8', separator: str = '\t') -> Dict[str, pd.DataFrame]:
        """
        Load all files for a specific category.
        
        Args:
            category: Category prefix (e.g., 'sym', 'ent', 'ref')
            encoding: File encoding
            separator: Delimiter for text files
            
        Returns:
            Dictionary with dataframes
        """
        data = {}
        
        for folder in os.listdir(self.base_data_path):
            folder_path = os.path.join(self.base_data_path, folder)
            if not os.path.isdir(folder_path):
                continue
            
            # Check if folder starts with category
            if not folder.lower().startswith(category.lower()):
                continue
            
            # Load all text files in this folder
            for file in os.listdir(folder_path):
                if file.endswith('.txt'):
                    file_path = os.path.join(folder_path, file)
                    try:
                        df = pd.read_csv(file_path, sep=separator, encoding=encoding, low_memory=False)
                        key = f"{folder}_{file.replace('.txt', '')}"
                        data[key] = df
                        print(f"Loaded: {key} - Shape: {df.shape}")
                    except Exception as e:
                        print(f"Error loading {file_path}: {str(e)}")
        
        return data
    
    def load_folder(self, folder_name: str, encoding: str = 'utf-8', separator: str = '\t') -> pd.DataFrame:
        """
        Load a specific FactSet folder's text files (concatenated).
        
        Args:
            folder_name: Name of the FactSet folder
            encoding: File encoding
            separator: Delimiter for text files
            
        Returns:
            Concatenated dataframe
        """
        folder_path = os.path.join(self.base_data_path, folder_name)
        
        if not os.path.exists(folder_path):
            print(f"Folder not found: {folder_name}")
            return None
        
        dfs = []
        for file in sorted(os.listdir(folder_path)):
            if file.endswith('.txt'):
                file_path = os.path.join(folder_path, file)
                try:
                    df = pd.read_csv(file_path, sep=separator, encoding=encoding, low_memory=False)
                    dfs.append(df)
                    print(f"Loaded: {file} - Shape: {df.shape}")
                except Exception as e:
                    print(f"Error loading {file}: {str(e)}")
        
        if dfs:
            return pd.concat(dfs, ignore_index=True)
        else:
            return None


class TrucostDataLoader:
    """Load Trucost data from CSV and Stata files."""
    
    def __init__(self, base_data_path: str = None):
        """
        Initialize the Trucost data loader.
        
        Args:
            base_data_path: Root path to Trucost data directory
        """
        if base_data_path is None:
            self.base_data_path = r"C:\Users\scelik\OneDrive - Tilburg University\Desktop\TRACE3\Data\Trucost (Access through WRDS)"
        else:
            self.base_data_path = base_data_path
            
        if not os.path.exists(self.base_data_path):
            raise ValueError(f"Data path not found: {self.base_data_path}")
    
    def get_available_files(self) -> Dict[str, List[str]]:
        """Get available Trucost data files organized by type."""
        files_by_type = {'csv': [], 'dta': []}
        
        for file in os.listdir(self.base_data_path):
            file_path = os.path.join(self.base_data_path, file)
            if os.path.isfile(file_path):
                if file.endswith('.csv'):
                    files_by_type['csv'].append(file)
                elif file.endswith('.dta'):
                    files_by_type['dta'].append(file)
        
        return files_by_type
    
    def load_ghg_data(self, file_type: str = 'csv') -> pd.DataFrame:
        """
        Load Trucost GHG data.
        
        Args:
            file_type: 'csv' or 'dta'
            
        Returns:
            pandas DataFrame
        """
        files = self.get_available_files()
        
        # Find GHG file
        for file in files.get(file_type, []):
            if 'ghg' in file.lower():
                file_path = os.path.join(self.base_data_path, file)
                return self._load_file(file_path, file_type)
        
        print(f"No GHG file found with type {file_type}")
        return None
    
    def load_nonghg_data(self, file_type: str = 'csv') -> pd.DataFrame:
        """
        Load Trucost non-GHG data.
        
        Args:
            file_type: 'csv' or 'dta'
            
        Returns:
            pandas DataFrame
        """
        files = self.get_available_files()
        
        # Find non-GHG file
        for file in files.get(file_type, []):
            if 'nonghg' in file.lower():
                file_path = os.path.join(self.base_data_path, file)
                return self._load_file(file_path, file_type)
        
        print(f"No non-GHG file found with type {file_type}")
        return None
    
    def load_all_data(self, file_type: str = 'csv') -> Dict[str, pd.DataFrame]:
        """
        Load all Trucost data files.
        
        Args:
            file_type: 'csv' or 'dta'
            
        Returns:
            Dictionary with dataframes
        """
        data = {}
        files = self.get_available_files()
        
        for file in files.get(file_type, []):
            file_path = os.path.join(self.base_data_path, file)
            key = file.replace(f'.{file_type}', '')
            data[key] = self._load_file(file_path, file_type)
        
        return data
    
    def _load_file(self, file_path: str, file_type: str) -> pd.DataFrame:
        """
        Load a single Trucost file.
        
        Args:
            file_path: Full path to file
            file_type: 'csv' or 'dta'
            
        Returns:
            pandas DataFrame
        """
        try:
            if file_type == 'csv':
                df = pd.read_csv(file_path)
            elif file_type == 'dta':
                df = pd.read_stata(file_path)
            else:
                print(f"Unsupported file type: {file_type}")
                return None
            
            print(f"Loaded: {os.path.basename(file_path)} - Shape: {df.shape}")
            return df
        except Exception as e:
            print(f"Error loading {file_path}: {str(e)}")
            return None


def get_data_summary(df: pd.DataFrame) -> Dict:
    """
    Generate a summary of the dataframe.
    
    Args:
        df: Input dataframe
        
    Returns:
        Dictionary with summary statistics
    """
    if df is None or df.empty:
        return {}
    
    return {
        "shape": df.shape,
        "columns": list(df.columns),
        "dtypes": dict(df.dtypes),
        "missing_values": dict(df.isnull().sum()),
        "memory_usage_mb": df.memory_usage(deep=True).sum() / 1024**2,
    }

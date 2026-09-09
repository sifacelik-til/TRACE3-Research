"""
Utility functions for data analysis and visualization.
"""

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from typing import List, Optional


def set_analysis_style():
    """Set matplotlib and seaborn style for consistent visualizations."""
    sns.set_style("whitegrid")
    plt.rcParams['figure.figsize'] = (14, 8)
    plt.rcParams['font.size'] = 10


def print_data_info(df: pd.DataFrame, name: str = "DataFrame") -> None:
    """
    Print comprehensive information about a dataframe.
    
    Args:
        df: Input dataframe
        name: Name for display
    """
    print(f"\n{'='*60}")
    print(f"Dataset: {name}")
    print(f"{'='*60}")
    print(f"Shape: {df.shape[0]} rows × {df.shape[1]} columns")
    print(f"\nColumn Names and Types:")
    print(df.dtypes)
    print(f"\nMissing Values:")
    print(df.isnull().sum())
    print(f"\nMemory Usage: {df.memory_usage(deep=True).sum() / 1024**2:.2f} MB")
    print(f"\nFirst Few Rows:")
    print(df.head())
    print(f"{'='*60}\n")


def find_numeric_columns(df: pd.DataFrame) -> List[str]:
    """
    Find numeric columns in a dataframe.
    
    Args:
        df: Input dataframe
        
    Returns:
        List of numeric column names
    """
    return df.select_dtypes(include=['number']).columns.tolist()


def find_categorical_columns(df: pd.DataFrame) -> List[str]:
    """
    Find categorical columns in a dataframe.
    
    Args:
        df: Input dataframe
        
    Returns:
        List of categorical column names
    """
    return df.select_dtypes(include=['object', 'category']).columns.tolist()


def plot_missing_data(df: pd.DataFrame, title: str = "Missing Data Heatmap") -> None:
    """
    Visualize missing data in a dataframe.
    
    Args:
        df: Input dataframe
        title: Plot title
    """
    plt.figure(figsize=(14, 6))
    sns.heatmap(df.isnull(), cbar=True, cmap='RdYlGn_r', yticklabels=False)
    plt.title(title)
    plt.tight_layout()
    plt.show()


def plot_numeric_distributions(df: pd.DataFrame, title: str = "Numeric Data Distributions") -> None:
    """
    Plot distributions of numeric columns.
    
    Args:
        df: Input dataframe
        title: Plot title
    """
    numeric_cols = find_numeric_columns(df)
    
    if not numeric_cols:
        print("No numeric columns found")
        return
    
    n_cols = len(numeric_cols)
    n_rows = (n_cols + 2) // 3
    
    fig, axes = plt.subplots(n_rows, 3, figsize=(15, 5*n_rows))
    axes = axes.flatten() if n_cols > 1 else [axes]
    
    for idx, col in enumerate(numeric_cols):
        axes[idx].hist(df[col].dropna(), bins=30, edgecolor='black', alpha=0.7)
        axes[idx].set_title(f'Distribution of {col}')
        axes[idx].set_xlabel(col)
        axes[idx].set_ylabel('Frequency')
    
    # Hide empty subplots
    for idx in range(n_cols, len(axes)):
        axes[idx].set_visible(False)
    
    fig.suptitle(title, fontsize=16, y=1.00)
    plt.tight_layout()
    plt.show()


def get_column_stats(df: pd.DataFrame, numeric_only: bool = True) -> pd.DataFrame:
    """
    Get descriptive statistics for dataframe columns.
    
    Args:
        df: Input dataframe
        numeric_only: Only include numeric columns
        
    Returns:
        DataFrame with statistics
    """
    if numeric_only:
        return df.describe(include=['number']).T
    else:
        return df.describe(include='all').T

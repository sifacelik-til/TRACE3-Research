#!/usr/bin/env python3
"""
Build company network profiles for 15 target companies.
Since FactSet supply chain data is limited, creates company profiles with:
  - Company node with all emissions data
  - Structure ready for adding supplier/customer data
  - All required columns from the brief
"""

import pandas as pd
import numpy as np
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# Company mappings: (Name, FactSet ID, Category)
TARGET_COMPANIES = [
    # KMWE
    ('ASM International NV', '090MZM-E', 'KMWE'),
    ('The Japan Steel Works, Ltd.', '05WJNY-E', 'KMWE'),
    ('Mitsubishi Heavy Industries, Ltd.', '05ZL2M-E', 'KMWE'),
    ('Sumitomo Heavy Industries, Ltd.', '05HWKZ-E', 'KMWE'),
    ('IHI Corporation', '06HHG4-E', 'KMWE'),
    # Vanderlande
    ('KONE Oyj', '05HZJ9-E', 'Vanderlande'),
    ('Rockwell Automation, Inc.', '000VJS-E', 'Vanderlande'),
    ('Mitsubishi Electric Corporation', '05ZL2M-E', 'Vanderlande'),
    # Neways
    ('Flex Ltd.', '0015XK-E', 'Neways'),
    ('Foxconn Industrial Internet Co., Ltd.', '05J213-E', 'Neways'),
    ('Hon Hai Precision Industry Co., Ltd.', '003JW8-E', 'Neways'),
]

def get_all_trucost_columns():
    """Return list of all Trucost emissions columns to include."""
    return [
        'di_319413',  # Scope 1 Gross
        'di_319414',  # Scope 2 Location-based
        'di_319415',  # Scope 3 Upstream total
        'di_326737',  # Scope 3 Downstream total
        # Additional Scope 3 categories (40+ columns)
        'di_378680', 'di_378681', 'di_378682', 'di_378683', 'di_378684',
        'di_378685', 'di_378686', 'di_378687', 'di_378688', 'di_378689',
        'di_378690', 'di_378691', 'di_378692', 'di_378693', 'di_378694',
        'di_378695', 'di_378696', 'di_378697', 'di_378698', 'di_378699',
        'di_378700', 'di_378701', 'di_378702', 'di_378703', 'di_378704',
        'di_378705', 'di_378706', 'di_378707', 'di_378708', 'di_378709',
        'di_378710', 'di_378711', 'di_378712', 'di_378713', 'di_378714',
        'di_378715', 'di_378716', 'di_378717', 'di_378718', 'di_378719',
        'di_378720'
    ]

def main():
    print("\n" + "="*90)
    print("BUILDING COMPANY NETWORK PROFILES FOR 15 COMPANIES")
    print("="*90)
    
    # Load source data
    print("\n[1/3] Loading source data...")
    
    common_file = Path("data/outputs/dataset_readers/common_companies_by_year_cdp_trucost_factset_lseg_with_trucost_emissions.csv")
    trucost_file = Path("data/raw/Trucost (Access through WRDS)/260710 trucost pulic-ghg-2011to24.csv")
    
    common_df = pd.read_csv(common_file, low_memory=False)
    trucost_df = pd.read_csv(trucost_file, low_memory=False)
    
    print(f"  Loaded {len(common_df):,} company mappings")
    print(f"  Loaded {len(trucost_df):,} Trucost records")
    
    # Get all possible emissions columns from Trucost
    available_cols = [col for col in trucost_df.columns if col.startswith('di_')]
    print(f"  Available emissions columns in Trucost: {len(available_cols)}")
    
    # Process each company
    print("\n[2/3] Processing 11 companies...")
    
    processed_count = 0
    
    for company_name, factset_id, category in TARGET_COMPANIES:
        print(f"\n  {company_name:45s} ({category:15s})")
        print(f"  FactSet ID: {factset_id}")
        
        # Create output directory
        network_dir = Path(f"data/processed/network_{factset_id.replace('-', '_').lower()}")
        network_dir.mkdir(parents=True, exist_ok=True)
        
        # Create nodes list
        all_nodes = []
        
        # Find company in common_df
        company_match = common_df[common_df['factset_entity_id'] == factset_id]
        
        if len(company_match) == 0:
            print(f"    WARNING: Company not found in common mappings")
            continue
        
        # Get company info
        company_row = company_match.iloc[0]
        trucost_id = company_row['trucost_companyid']
        industry_code = company_row.get('factset_industry_code', None)
        industry_desc = company_row.get('factset_industry_desc', None)
        sector_bucket = company_row.get('factset_sector_bucket', None)
        
        print(f"  Sector: {sector_bucket}")
        
        # Get Trucost data
        if pd.notna(trucost_id):
            trucost_data = trucost_df[trucost_df['companyid'] == trucost_id].sort_values('fiscalyear', ascending=False)
            
            if len(trucost_data) > 0:
                # Get latest year data
                latest_year = trucost_data.iloc[0]
                emissions_year = latest_year.get('fiscalyear')
                
                print(f"  Emissions data available: Year {int(emissions_year) if pd.notna(emissions_year) else 'N/A'}")
                
                # Create target company node
                target_node = {
                    'node_id': factset_id,
                    'node_name': company_name,
                    'industry_code': industry_code,
                    'industry_desc': industry_desc,
                    'sector_bucket': sector_bucket,
                    'is_target': True,
                    'tier_upstream': np.nan,
                    'tier_downstream': np.nan,
                    'trucost_companyid': trucost_id,
                    'emissions_year': emissions_year
                }
                
                # Add all available emissions columns
                for col in get_all_trucost_columns():
                    target_node[col] = latest_year.get(col, np.nan)
                
                all_nodes.append(target_node)
                
                # Get all historical data (2014-2024)
                print(f"  Creating historical emissions data...")
                
                # Create yearly versions
                all_yearly_nodes = []
                for _, year_row in trucost_data.iterrows():
                    year = year_row.get('fiscalyear')
                    
                    node_entry = {
                        'node_id': f"{factset_id}_Y{int(year)}",  # Unique ID per year
                        'node_name': company_name,
                        'industry_code': industry_code,
                        'industry_desc': industry_desc,
                        'sector_bucket': sector_bucket,
                        'is_target': True,
                        'tier_upstream': np.nan,
                        'tier_downstream': np.nan,
                        'trucost_companyid': trucost_id,
                        'emissions_year': year
                    }
                    
                    # Add emissions for this year
                    for col in get_all_trucost_columns():
                        node_entry[col] = year_row.get(col, np.nan)
                    
                    all_yearly_nodes.append(node_entry)
                
                print(f"    Historical records: {len(all_yearly_nodes)} years")
                
                # Save to CSV
                nodes_df = pd.DataFrame(all_nodes)
                nodes_file = network_dir / "nodes.csv"
                nodes_df.to_csv(nodes_file, index=False)
                
                print(f"    Saved nodes.csv ({len(nodes_df)} rows, {len(nodes_df.columns)} columns)")
                
                # Save historical data
                historical_df = pd.DataFrame(all_yearly_nodes)
                historical_file = network_dir / "nodes_historical.csv"
                historical_df.to_csv(historical_file, index=False)
                
                print(f"    Saved nodes_historical.csv ({len(historical_df)} rows)")
                
                # Create template edges file
                edges_df = pd.DataFrame(columns=[
                    'root_target_id', 'root_target_name', 'direction', 'tier',
                    'source_id', 'target_id', 'source_name', 'target_name', 'relationship_type'
                ])
                
                edges_file = network_dir / "edges.csv"
                edges_df.to_csv(edges_file, index=False)
                
                print(f"    Created edges.csv (template, 0 relationships)")
                
                processed_count += 1
            else:
                print(f"    ERROR: No Trucost data found for ID {trucost_id}")
        else:
            print(f"    ERROR: No Trucost ID in mappings")
    
    print(f"\n[3/3] Summary")
    print(f"      Successfully processed: {processed_count} companies")
    
    print("\n" + "="*90)
    print("COMPANY NETWORK PROFILES CREATED")
    print("="*90)
    
    print("\nEach company has:")
    print("  - nodes.csv: Company node with latest emissions data")
    print("  - nodes_historical.csv: Historical emissions (2014-2024)")
    print("  - edges.csv: Template for supplier/customer relationships")
    print("\nColumn structure includes:")
    print("  - node_id, node_name: Identifiers")
    print("  - industry_code, industry_desc, sector_bucket: Industry classification")
    print("  - is_target, tier_upstream, tier_downstream: Network position")
    print("  - trucost_companyid, emissions_year: Trucost linking")
    print(f"  - {len(get_all_trucost_columns())} emissions columns (di_*)")
    print("\nDirectories created:")
    
    for company_name, factset_id, category in TARGET_COMPANIES:
        network_dir = Path(f"data/processed/network_{factset_id.replace('-', '_').lower()}")
        if network_dir.exists():
            nodes_file = network_dir / "nodes.csv"
            if nodes_file.exists():
                print(f"  - data/processed/{network_dir.name}/")

if __name__ == "__main__":
    main()

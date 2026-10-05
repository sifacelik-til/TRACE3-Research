#!/usr/bin/env python3
"""
Build complete supply chain networks for 11 companies.
Includes all direct suppliers and customers with revenue_pct weighting.
Populates both nodes.csv and edges.csv with full data.
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
        'di_319413', 'di_319414', 'di_319415', 'di_326737',
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

def get_company_emissions_data(company_id, trucost_df):
    """Get latest emissions data for a company from Trucost."""
    if pd.isna(company_id):
        emissions_cols = get_all_trucost_columns()
        return {col: np.nan for col in ['fiscalyear'] + emissions_cols}
    
    company_data = trucost_df[trucost_df['companyid'] == company_id].copy()
    
    if len(company_data) == 0:
        emissions_cols = get_all_trucost_columns()
        return {col: np.nan for col in ['fiscalyear'] + emissions_cols}
    
    # Get latest year
    company_data = company_data.sort_values('fiscalyear', ascending=False)
    latest = company_data.iloc[0]
    
    result = {'fiscalyear': latest.get('fiscalyear')}
    
    for col in get_all_trucost_columns():
        result[col] = latest.get(col, np.nan)
    
    return result

def get_industry_data(entity_id, common_df):
    """Get industry classification from common_df."""
    if pd.isna(entity_id):
        return {'industry_code': None, 'industry_desc': None, 'sector_bucket': None}
    
    match = common_df[common_df['factset_entity_id'] == entity_id]
    if len(match) > 0:
        row = match.iloc[0]
        return {
            'industry_code': row.get('factset_industry_code', None),
            'industry_desc': row.get('factset_industry_desc', None),
            'sector_bucket': row.get('factset_sector_bucket', None)
        }
    
    return {'industry_code': None, 'industry_desc': None, 'sector_bucket': None}

def main():
    print("\n" + "="*100)
    print("BUILDING COMPLETE SUPPLY CHAIN NETWORKS WITH SUPPLIERS AND CUSTOMERS")
    print("Including all direct relationships weighted by revenue_pct")
    print("="*100)
    
    # Load source data
    print("\n[1/4] Loading source data...")
    
    factset_file = Path("data/processed/targets_suppliers_factset.csv")
    common_file = Path("data/outputs/common_companies_by_year_cdp_trucost_factset_lseg_with_trucost_emissions.csv")
    trucost_file = Path("data/raw/Trucost (Access through WRDS)/260710 trucost pulic-ghg-2011to24.csv")
    
    factset_df = pd.read_csv(factset_file)
    common_df = pd.read_csv(common_file, low_memory=False)
    trucost_df = pd.read_csv(trucost_file, low_memory=False)
    
    print(f"  FactSet relationships: {len(factset_df):,}")
    print(f"  Company mappings: {len(common_df):,}")
    print(f"  Trucost records: {len(trucost_df):,}")
    
    # Process each company
    print("\n[2/4] Processing 11 companies with suppliers and customers...")
    
    processed_count = 0
    total_nodes = 0
    total_edges = 0
    
    for company_name, factset_id, category in TARGET_COMPANIES:
        print(f"\n  [PROCESSING] {company_name:45s} ({category:15s})")
        
        # Create output directory
        network_dir = Path(f"data/processed/network_{factset_id.replace('-', '_').lower()}")
        network_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize collections
        all_nodes = {}  # Use dict to avoid duplicates
        all_edges = []
        
        # Get target company info
        target_industry = get_industry_data(factset_id, common_df)
        target_trucost_match = common_df[common_df['factset_entity_id'] == factset_id]
        target_trucost_id = target_trucost_match.iloc[0]['trucost_companyid'] if len(target_trucost_match) > 0 else None
        target_emissions = get_company_emissions_data(target_trucost_id, trucost_df)
        
        # Add target company as node
        all_nodes[factset_id] = {
            'node_id': factset_id,
            'node_name': company_name,
            'industry_code': target_industry['industry_code'],
            'industry_desc': target_industry['industry_desc'],
            'sector_bucket': target_industry['sector_bucket'],
            'is_target': True,
            'tier_upstream': np.nan,
            'tier_downstream': np.nan,
            'trucost_companyid': target_trucost_id,
            'emissions_year': target_emissions['fiscalyear']
        }
        
        # Add emissions columns
        for col in get_all_trucost_columns():
            all_nodes[factset_id][col] = target_emissions.get(col, np.nan)
        
        # Get direct suppliers (rows where this company is target)
        suppliers_data = factset_df[factset_df['target_factset_id'] == factset_id]
        
        # Get direct customers (rows where this company is supplier)
        customers_data = factset_df[factset_df['supplier_factset_id'] == factset_id]
        
        print(f"    Suppliers: {len(suppliers_data):4d} | Customers: {len(customers_data):4d}")
        
        # Process suppliers
        supplier_count = 0
        supplier_edge_count = 0
        for _, row in suppliers_data.iterrows():
            supplier_id = row['supplier_factset_id']
            supplier_name = row['supplier_factset_name']
            revenue_pct = row.get('revenue_pct')
            
            if pd.isna(supplier_id):
                continue
            
            # Add supplier node if not already added
            if supplier_id not in all_nodes:
                supplier_industry = get_industry_data(supplier_id, common_df)
                supplier_trucost_match = common_df[common_df['factset_entity_id'] == supplier_id]
                supplier_trucost_id = supplier_trucost_match.iloc[0]['trucost_companyid'] if len(supplier_trucost_match) > 0 else None
                supplier_emissions = get_company_emissions_data(supplier_trucost_id, trucost_df)
                
                all_nodes[supplier_id] = {
                    'node_id': supplier_id,
                    'node_name': supplier_name,
                    'industry_code': supplier_industry['industry_code'],
                    'industry_desc': supplier_industry['industry_desc'],
                    'sector_bucket': supplier_industry['sector_bucket'],
                    'is_target': False,
                    'tier_upstream': 1.0,
                    'tier_downstream': np.nan,
                    'trucost_companyid': supplier_trucost_id,
                    'emissions_year': supplier_emissions['fiscalyear']
                }
                
                for col in get_all_trucost_columns():
                    all_nodes[supplier_id][col] = supplier_emissions.get(col, np.nan)
                
                supplier_count += 1
            
            # Add edge
            all_edges.append({
                'root_target_id': factset_id,
                'root_target_name': company_name,
                'direction': 'upstream',
                'tier': 1,
                'source_id': supplier_id,
                'target_id': factset_id,
                'source_name': supplier_name,
                'target_name': company_name,
                'relationship_type': 'supplies',
                'revenue_pct': revenue_pct
            })
            supplier_edge_count += 1
        
        # Process customers
        customer_count = 0
        customer_edge_count = 0
        for _, row in customers_data.iterrows():
            customer_id = row['target_factset_id']
            customer_name = row['target_factset_name']
            revenue_pct = row.get('revenue_pct')
            
            if pd.isna(customer_id):
                continue
            
            # Add customer node if not already added
            if customer_id not in all_nodes:
                customer_industry = get_industry_data(customer_id, common_df)
                customer_trucost_match = common_df[common_df['factset_entity_id'] == customer_id]
                customer_trucost_id = customer_trucost_match.iloc[0]['trucost_companyid'] if len(customer_trucost_match) > 0 else None
                customer_emissions = get_company_emissions_data(customer_trucost_id, trucost_df)
                
                all_nodes[customer_id] = {
                    'node_id': customer_id,
                    'node_name': customer_name,
                    'industry_code': customer_industry['industry_code'],
                    'industry_desc': customer_industry['industry_desc'],
                    'sector_bucket': customer_industry['sector_bucket'],
                    'is_target': False,
                    'tier_upstream': np.nan,
                    'tier_downstream': 1.0,
                    'trucost_companyid': customer_trucost_id,
                    'emissions_year': customer_emissions['fiscalyear']
                }
                
                for col in get_all_trucost_columns():
                    all_nodes[customer_id][col] = customer_emissions.get(col, np.nan)
                
                customer_count += 1
            
            # Add edge
            all_edges.append({
                'root_target_id': factset_id,
                'root_target_name': company_name,
                'direction': 'downstream',
                'tier': 1,
                'source_id': factset_id,
                'target_id': customer_id,
                'source_name': company_name,
                'target_name': customer_name,
                'relationship_type': 'sells_to',
                'revenue_pct': revenue_pct
            })
            customer_edge_count += 1
        
        # Create DataFrames and save
        nodes_df = pd.DataFrame(list(all_nodes.values()))
        edges_df = pd.DataFrame(all_edges)
        
        # Save files
        nodes_file = network_dir / "nodes.csv"
        edges_file = network_dir / "edges.csv"
        
        nodes_df.to_csv(nodes_file, index=False)
        edges_df.to_csv(edges_file, index=False)
        
        print(f"    Saved: nodes.csv ({len(nodes_df)} nodes), edges.csv ({len(edges_df)} edges)")
        print(f"            Added {supplier_count} suppliers, {customer_count} customers")
        
        total_nodes += len(nodes_df)
        total_edges += len(edges_df)
        processed_count += 1
    
    print(f"\n[3/4] Summary")
    print(f"      Companies processed: {processed_count}")
    print(f"      Total nodes across all networks: {total_nodes:,}")
    print(f"      Total edges across all networks: {total_edges:,}")
    
    print(f"\n[4/4] Complete networks created:")
    
    edge_counts = []
    for company_name, factset_id, category in TARGET_COMPANIES:
        network_dir = Path(f"data/processed/network_{factset_id.replace('-', '_').lower()}")
        if network_dir.exists():
            edges_file = network_dir / "edges.csv"
            if edges_file.exists():
                edges = pd.read_csv(edges_file)
                edge_counts.append(len(edges))
                if len(edges) > 0:
                    print(f"      {company_name:40s} - {len(edges):4d} relationships")
    
    print("\n" + "="*100)
    print("[OK] Complete supply chain networks built with suppliers, customers, and revenue weighting!")
    print("="*100)

if __name__ == "__main__":
    main()

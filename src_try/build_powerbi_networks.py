#!/usr/bin/env python3
"""
Build PowerBI-ready supply chain networks for 15 target companies.
Extracts direct suppliers and customers only (Tier 1).
"""

import pandas as pd
import numpy as np
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# Target companies from the user's image
TARGET_COMPANIES = {
    'KMWE': [
        "ASM International NV",
        "The Japan Steel Works, Ltd.",
        "Mitsubishi Heavy Industries, Ltd.",
        "Sumitomo Heavy Industries, Ltd.",
        "IHI Corporation"
    ],
    'Vanderlande': [
        "KONE Oyj",
        "Fanuc Corporation",
        "Rockwell Automation, Inc.",
        "OMRON Corporation",
        "Mitsubishi Electric Corporation"
    ],
    'Neways': [
        "Celestica Inc.",
        "Sanmina Corporation",
        "Flex Ltd.",
        "Foxconn Industrial Internet Co., Ltd.",
        "Hon Hai Precision Industry Co., Ltd."
    ]
}

def normalize_name(name):
    """Normalize company names for matching."""
    if not isinstance(name, str):
        return ""
    return name.strip().lower()

def match_company(target_name, factset_df):
    """Match a target company to FactSet data."""
    target_norm = normalize_name(target_name)
    
    # Try exact match on target_factset_name
    exact_target = factset_df[factset_df['target_factset_name'].str.lower() == target_norm]
    if len(exact_target) > 0:
        return exact_target.iloc[0]['target_factset_id'], 'exact_target'
    
    # Try exact match on supplier_factset_name
    exact_supplier = factset_df[factset_df['supplier_factset_name'].str.lower() == target_norm]
    if len(exact_supplier) > 0:
        return exact_supplier.iloc[0]['supplier_factset_id'], 'exact_supplier'
    
    # Try partial match (first word) on target
    first_word = target_norm.split()[0] if target_name else ""
    partial_target = factset_df[factset_df['target_factset_name'].str.lower().str.contains(first_word, na=False)]
    if len(partial_target) > 0:
        return partial_target.iloc[0]['target_factset_id'], 'partial_target'
    
    partial_supplier = factset_df[factset_df['supplier_factset_name'].str.lower().str.contains(first_word, na=False)]
    if len(partial_supplier) > 0:
        return partial_supplier.iloc[0]['supplier_factset_id'], 'partial_supplier'
    
    return None, 'not_found'

def get_latest_emissions(company_id, trucost_df):
    """Get latest available emissions for a company."""
    company_data = trucost_df[trucost_df['companyid'] == company_id].copy()
    
    if len(company_data) == 0:
        return None
    
    # Get latest year
    company_data = company_data.sort_values('fiscalyear', ascending=False)
    latest = company_data.iloc[0]
    
    return {
        'companyid': company_id,
        'fiscalyear': latest.get('fiscalyear'),
        'scope1': latest.get('di_319413'),
        'scope2': latest.get('di_319414'),
        'scope3_upstream': latest.get('di_319415'),
        'scope3_downstream': latest.get('di_326737')
    }

def main():
    print("\n" + "="*80)
    print("BUILDING POWERBI NETWORKS FOR 15 COMPANIES")
    print("="*80)
    
    # Create output directory
    output_dir = Path("data/outputs/powerbi_networks")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load FactSet supply chain data from processed folder
    print("\n[1/4] Loading FactSet supply chain relationships...")
    factset_file = Path("data/processed/targets_suppliers_factset.csv")
    if not factset_file.exists():
        print(f"ERROR: FactSet file not found at {factset_file}")
        return
    
    factset = pd.read_csv(factset_file)
    print(f"  Loaded {len(factset):,} relationships")
    
    # Load Trucost emissions data
    print("\n[2/4] Loading Trucost emissions data...")
    trucost_file = Path("data/raw/Trucost (Access through WRDS)/260710 trucost pulic-ghg-2011to24.csv")
    if not trucost_file.exists():
        print(f"ERROR: Trucost file not found at {trucost_file}")
        return
    
    trucost = pd.read_csv(trucost_file, low_memory=False)
    print(f"  Loaded {len(trucost):,} emissions records")
    
    # Match all target companies
    print("\n[3/4] Matching target companies to FactSet entities...")
    all_companies = []
    for category, companies in TARGET_COMPANIES.items():
        for company in companies:
            entity_id, match_type = match_company(company, factset)
            status = "[OK]" if entity_id else "[FAIL]"
            print(f"  {status} {company:45s} ({category:15s}) -> {entity_id if entity_id else 'NOT FOUND'}")
            all_companies.append({
                'category': category,
                'company_name': company,
                'entity_id': entity_id,
                'match_type': match_type
            })
    
    matched_df = pd.DataFrame(all_companies)
    matched_df.to_csv(output_dir / "matched_companies.csv", index=False)
    
    # Build networks for each company
    print("\n[4/4] Building direct supplier/customer networks...")
    
    all_nodes = []
    all_edges = []
    processed_nodes = set()
    
    for idx, row in matched_df.iterrows():
        company_name = row['company_name']
        entity_id = row['entity_id']
        category = row['category']
        
        if pd.isna(entity_id):
            print(f"  SKIP: {company_name} (no entity ID)")
            continue
        
        # Get all suppliers (rows where this company is the target)
        suppliers_data = factset[factset['target_factset_id'] == entity_id]
        
        # Get all customers (rows where this company is the supplier)
        customers_data = factset[factset['supplier_factset_id'] == entity_id]
        
        print(f"  {company_name:45s}: {len(suppliers_data)} suppliers, {len(customers_data)} customers")
        
        # Add target company as node (if not already added)
        if entity_id not in processed_nodes:
            emissions = get_latest_emissions(entity_id, trucost)
            all_nodes.append({
                'node_id': entity_id,
                'node_name': company_name,
                'entity_type': 'target_company',
                'category': category,
                'node_type': 'focal',
                'relationship': 'focal_company',
                'scope1_emissions': emissions['scope1'] if emissions else None,
                'scope2_emissions': emissions['scope2'] if emissions else None,
                'scope3_upstream': emissions['scope3_upstream'] if emissions else None,
                'scope3_downstream': emissions['scope3_downstream'] if emissions else None,
                'emissions_year': emissions['fiscalyear'] if emissions else None
            })
            processed_nodes.add(entity_id)
        
        # Add suppliers as nodes and create edges
        for _, supplier_row in suppliers_data.iterrows():
            supplier_id = supplier_row['supplier_factset_id']
            supplier_name = supplier_row['supplier_factset_name']
            
            if pd.isna(supplier_id):
                continue
            
            # Add supplier node if not already added
            if supplier_id not in processed_nodes:
                emissions = get_latest_emissions(supplier_id, trucost)
                all_nodes.append({
                    'node_id': supplier_id,
                    'node_name': supplier_name,
                    'entity_type': 'supplier',
                    'category': category,
                    'node_type': 'direct',
                    'relationship': 'direct_supplier',
                    'scope1_emissions': emissions['scope1'] if emissions else None,
                    'scope2_emissions': emissions['scope2'] if emissions else None,
                    'scope3_upstream': emissions['scope3_upstream'] if emissions else None,
                    'scope3_downstream': emissions['scope3_downstream'] if emissions else None,
                    'emissions_year': emissions['fiscalyear'] if emissions else None
                })
                processed_nodes.add(supplier_id)
            
            # Add edge
            all_edges.append({
                'source_id': supplier_id,
                'source_name': supplier_name,
                'target_id': entity_id,
                'target_name': company_name,
                'relationship_type': 'supplies',
                'direction': 'upstream',
                'category': category,
                'revenue_percent': None,
                'flow_type': 'material'
            })
        
        # Add customers as nodes and create edges
        for _, customer_row in customers_data.iterrows():
            customer_id = customer_row['target_factset_id']
            customer_name = customer_row['target_factset_name']
            
            if pd.isna(customer_id):
                continue
            
            # Add customer node if not already added
            if customer_id not in processed_nodes:
                emissions = get_latest_emissions(customer_id, trucost)
                all_nodes.append({
                    'node_id': customer_id,
                    'node_name': customer_name,
                    'entity_type': 'customer',
                    'category': category,
                    'node_type': 'direct',
                    'relationship': 'direct_customer',
                    'scope1_emissions': emissions['scope1'] if emissions else None,
                    'scope2_emissions': emissions['scope2'] if emissions else None,
                    'scope3_upstream': emissions['scope3_upstream'] if emissions else None,
                    'scope3_downstream': emissions['scope3_downstream'] if emissions else None,
                    'emissions_year': emissions['fiscalyear'] if emissions else None
                })
                processed_nodes.add(customer_id)
            
            # Add edge
            all_edges.append({
                'source_id': entity_id,
                'source_name': company_name,
                'target_id': customer_id,
                'target_name': customer_name,
                'relationship_type': 'sells_to',
                'direction': 'downstream',
                'category': category,
                'revenue_percent': None,
                'flow_type': 'material'
            })
    
    # Create DataFrames
    nodes_df = pd.DataFrame(all_nodes).drop_duplicates(subset=['node_id'])
    edges_df = pd.DataFrame(all_edges)
    
    print(f"\n  Total unique nodes: {len(nodes_df):,}")
    print(f"  Total relationships: {len(edges_df):,}")
    
    # Save to Excel with multiple sheets
    excel_file = output_dir / "supply_chain_networks_powerbi.xlsx"
    with pd.ExcelWriter(excel_file, engine='openpyxl') as writer:
        nodes_df.to_excel(writer, sheet_name='Nodes', index=False)
        edges_df.to_excel(writer, sheet_name='Edges', index=False)
        matched_df.to_excel(writer, sheet_name='Company_Matches', index=False)
    
    print(f"\n✓ Excel file saved: {excel_file}")
    
    # Also save as CSV files
    nodes_df.to_csv(output_dir / "supply_chain_nodes.csv", index=False)
    edges_df.to_csv(output_dir / "supply_chain_edges.csv", index=False)
    
    print(f"✓ CSV files saved:")
    print(f"  - supply_chain_nodes.csv ({len(nodes_df):,} rows)")
    print(f"  - supply_chain_edges.csv ({len(edges_df):,} rows)")
    
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"\nTarget Companies Analyzed: 15")
    print(f"Successfully Matched: {len(matched_df[matched_df['entity_id'].notna()])}")
    print(f"\nNetwork Statistics:")
    print(f"  Total Nodes: {len(nodes_df):,}")
    print(f"    - Target Companies: {len(nodes_df[nodes_df['entity_type'] == 'target_company'])}")
    print(f"    - Direct Suppliers: {len(nodes_df[nodes_df['entity_type'] == 'supplier'])}")
    print(f"    - Direct Customers: {len(nodes_df[nodes_df['entity_type'] == 'customer'])}")
    print(f"  Total Edges: {len(edges_df):,}")
    print(f"\nEmissions Coverage:")
    print(f"  Nodes with emissions data: {len(nodes_df[nodes_df['scope1_emissions'].notna()])}")
    print(f"  Coverage: {(len(nodes_df[nodes_df['scope1_emissions'].notna()]) / len(nodes_df) * 100):.1f}%")
    
    print("\n✓ Ready for PowerBI visualization!")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Create enhanced PowerBI-ready supply chain data for 15 companies.
Includes:
  - All 15 companies (matched and unmatched)
  - Emissions data where available
  - Proper formatting for PowerBI visualization
"""

import pandas as pd
import numpy as np
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# Company list from user's image
COMPANIES = {
    'KMWE': [
        ('ASM International NV', '002T5L-E'),
        ('The Japan Steel Works, Ltd.', None),
        ('Mitsubishi Heavy Industries, Ltd.', None),
        ('Sumitomo Heavy Industries, Ltd.', '05HYZ6-E'),
        ('IHI Corporation', '06HHG4-E')
    ],
    'Vanderlande': [
        ('KONE Oyj', '05HZJ9-E'),
        ('Fanuc Corporation', None),
        ('Rockwell Automation, Inc.', '000VJS-E'),
        ('OMRON Corporation', None),
        ('Mitsubishi Electric Corporation', None)
    ],
    'Neways': [
        ('Celestica Inc.', None),
        ('Sanmina Corporation', None),
        ('Flex Ltd.', '0015XK-E'),
        ('Foxconn Industrial Internet Co., Ltd.', '05J213-E'),
        ('Hon Hai Precision Industry Co., Ltd.', '05H5DH-E')
    ]
}

def get_trucost_data(factset_id, trucost_df):
    """Get emissions data for a company from Trucost by Trucost ID."""
    if pd.isna(factset_id):
        return None
    
    # Since we need to match FactSet ID to Trucost data, 
    # let's use the common matching file
    return None  # Placeholder

def main():
    print("\n" + "="*80)
    print("BUILDING ENHANCED POWERBI NETWORKS")
    print("Companies: 15 (5 KMWE + 5 Vanderlande + 5 Neways)")
    print("="*80)
    
    output_dir = Path("data/outputs/powerbi_networks")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load common company mappings
    print("\n[1/2] Loading company and emissions data...")
    common_df = pd.read_csv("data/outputs/common_factset_trucost_cdp_tickers_extended.csv", low_memory=False)
    trucost_df = pd.read_csv("data/raw/Trucost (Access through WRDS)/260710 trucost pulic-ghg-2011to24.csv", low_memory=False)
    
    print(f"  Loaded {len(common_df)} company mappings")
    print(f"  Loaded {len(trucost_df)} Trucost records")
    
    # Build nodes and edges
    print("\n[2/2] Building PowerBI data structure...")
    
    all_nodes = []
    node_counter = 0
    company_to_nodeid = {}
    
    # Process all 15 companies
    for category, companies in COMPANIES.items():
        for company_name, factset_id in companies:
            node_counter += 1
            node_id = f"COMP_{node_counter:03d}"
            
            # Try to find Trucost emissions data
            emissions = {
                'scope1': None,
                'scope2': None,
                'scope3_upstream': None,
                'scope3_downstream': None,
                'year': None
            }
            
            # Look for company in common mappings
            matching = common_df[common_df['factset_company_name'].str.contains(company_name.split()[0], case=False, na=False)]
            if len(matching) > 0:
                company_match = matching.iloc[0]
                trucost_id = company_match['trucost_companyid']
                
                # Get Trucost emissions
                if pd.notna(trucost_id):
                    tc_data = trucost_df[trucost_df['companyid'] == trucost_id].sort_values('fiscalyear', ascending=False)
                    if len(tc_data) > 0:
                        latest = tc_data.iloc[0]
                        emissions['scope1'] = latest.get('di_319413')
                        emissions['scope2'] = latest.get('di_319414')
                        emissions['scope3_upstream'] = latest.get('di_319415')
                        emissions['scope3_downstream'] = latest.get('di_326737')
                        emissions['year'] = latest.get('fiscalyear')
                
                factset_id = company_match['factset_entity_id']
                factset_ticker = company_match['factset_ticker']
            else:
                factset_ticker = None
            
            status = "[OK]" if factset_id else "[NO_MATCH]"
            
            all_nodes.append({
                'node_id': node_id,
                'company_name': company_name,
                'category': category,
                'node_type': 'target_company',
                'entity_type': 'focal',
                'factset_id': factset_id if pd.notna(factset_id) else '',
                'factset_ticker': factset_ticker if pd.notna(factset_ticker) else '',
                'data_available': 'Yes' if factset_id else 'No',
                'scope1_emissions': emissions['scope1'],
                'scope2_emissions': emissions['scope2'],
                'scope3_upstream': emissions['scope3_upstream'],
                'scope3_downstream': emissions['scope3_downstream'],
                'emissions_year': emissions['year']
            })
            
            company_to_nodeid[company_name] = node_id
            print(f"  {status} {company_name:45s} ({category:15s})")
    
    # Create DataFrame
    nodes_df = pd.DataFrame(all_nodes)
    
    print(f"\nNetwork Summary:")
    print(f"  Total Companies: {len(nodes_df)}")
    print(f"  Matched to Data: {len(nodes_df[nodes_df['factset_id'] != ''])}")
    print(f"  No Match: {len(nodes_df[nodes_df['factset_id'] == ''])}")
    print(f"  With Emissions Data: {len(nodes_df[nodes_df['scope1_emissions'].notna()])}")
    
    # Create sample edges for demonstration
    # These would connect suppliers -> target company -> customers
    # Since we don't have actual supply chain data, create template structure
    edges_df = pd.DataFrame({
        'source_id': [],
        'source_name': [],
        'target_id': [],
        'target_name': [],
        'relationship_type': [],
        'direction': [],
        'category': []
    })
    
    # Save to Excel
    excel_file = output_dir / "supply_chain_networks_powerbi.xlsx"
    
    with pd.ExcelWriter(excel_file, engine='openpyxl') as writer:
        # Nodes sheet
        nodes_df.to_excel(writer, sheet_name='Nodes', index=False)
        
        # Edges sheet (template)
        edges_df.to_excel(writer, sheet_name='Edges', index=False)
        
        # Company list sheet
        company_list = []
        for category, companies in COMPANIES.items():
            for company_name, _ in companies:
                node_info = nodes_df[nodes_df['company_name'] == company_name].iloc[0]
                company_list.append({
                    'Category': category,
                    'Company_Name': company_name,
                    'Node_ID': node_info['node_id'],
                    'FactSet_ID': node_info['factset_id'],
                    'Matched': node_info['data_available'],
                    'Has_Emissions': 'Yes' if pd.notna(node_info['scope1_emissions']) else 'No'
                })
        
        company_df = pd.DataFrame(company_list)
        company_df.to_excel(writer, sheet_name='Company_List', index=False)
        
        # Summary sheet
        summary_text = f"""
POWERBI SUPPLY CHAIN NETWORK DATA
Generated for 15 Target Companies

NODES (Companies):
  Total Companies: {len(nodes_df)}
  Matched to FactSet: {len(nodes_df[nodes_df['factset_id'] != ''])} ({len(nodes_df[nodes_df['factset_id'] != '']) / len(nodes_df) * 100:.0f}%)
  With Emissions Data: {len(nodes_df[nodes_df['scope1_emissions'].notna()])} ({len(nodes_df[nodes_df['scope1_emissions'].notna()]) / len(nodes_df) * 100:.0f}%)

EDGES (Relationships):
  Supplier-to-Company: [To be populated with actual data]
  Company-to-Customer: [To be populated with actual data]
  Total Relationships: {len(edges_df)}

DATA STRUCTURE:
  Nodes table contains:
    - node_id: Unique identifier for PowerBI
    - company_name: Company name as provided
    - category: KMWE / Vanderlande / Neways
    - factset_id, factset_ticker: FactSet identifiers
    - scope1/2/3_emissions: Latest available emissions data

  Edges table contains:
    - source_id, target_id: Node connections
    - relationship_type: supplies / sells_to
    - direction: upstream / downstream
    - category: Company category

NEXT STEPS IN POWERBI:
  1. Import Nodes table as main data source
  2. Import Edges table for relationships
  3. Use 'node_id' as unique identifier
  4. Color by 'category' or 'data_available'
  5. Size by emissions values (scope1_emissions, scope3_upstream, etc.)
  6. Create network visualization with source -> target relationships

TO ADD SUPPLIER/CUSTOMER DATA:
  - Fill in the Edges sheet with actual relationships
  - Use format: source_id, source_name, target_id, target_name, relationship_type, direction, category
  - relationship_type: 'supplies' for upstream, 'sells_to' for downstream
  - direction: 'upstream' for suppliers, 'downstream' for customers
"""
        
        summary_df = pd.DataFrame({'Summary': [summary_text]})
        summary_df.to_excel(writer, sheet_name='Summary', index=False)
    
    # Also save as CSV
    nodes_df.to_csv(output_dir / "nodes.csv", index=False)
    edges_df.to_csv(output_dir / "edges.csv", index=False)
    
    print(f"\n[OK] Excel file created: {excel_file}")
    print(f"[OK] CSV files created: nodes.csv, edges.csv")
    
    # Print sample data
    print("\n" + "="*80)
    print("NODES DATA (Sample)")
    print("="*80)
    print(nodes_df[['node_id', 'company_name', 'category', 'factset_id', 'data_available']].head(15).to_string(index=False))
    
    print("\n" + "="*80)
    print("POWERBI READY - NEXT STEPS:")
    print("="*80)
    print("""
1. Open: data/outputs/powerbi_networks/supply_chain_networks_powerbi.xlsx
2. Import into Power BI Desktop
3. Sheet 'Nodes' = Company data with emissions
4. Sheet 'Edges' = Supplier/customer relationships (add your data here)
5. Sheet 'Company_List' = Quick reference

NOTE: The Edges sheet is currently a template. Add your supplier/customer
relationships using the format provided in the Summary sheet.
""")

if __name__ == "__main__":
    main()

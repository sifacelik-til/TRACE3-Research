"""
Build Tier 1-3 supply chain networks for warehouse automation companies.
Enriched with Trucost emissions data and formatted for PowerBI visualization.
"""

import pandas as pd
import numpy as np
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# Configuration
DATA_DIR = Path("data/processed")
OUTPUT_DIR = Path("data/processed/warehouse_networks")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

WAREHOUSE_COMPANIES = {
    'beumer': {
        'name': 'BEUMER',
        'factset_id': 'TBD',  # Will be discovered from CSV
        'filepath': DATA_DIR / 'beumer_supplychain.csv'
    },
    'daifuku': {
        'name': 'Daifuku',
        'factset_id': 'TBD',
        'filepath': DATA_DIR / 'daifuku_supplychain.csv'
    },
    'dematic': {
        'name': 'Dematic',
        'factset_id': 'TBD',
        'filepath': DATA_DIR / 'dematic_supplychain.csv'
    },
    'knapp': {
        'name': 'KNAPP',
        'factset_id': 'TBD',
        'filepath': DATA_DIR / 'knapp_supplychain.csv'
    },
    'ssi': {
        'name': 'SSI Schäfer',
        'factset_id': 'TBD',
        'filepath': DATA_DIR / 'ssi_sch_fer_supplychain.csv'
    },
    'swisslog': {
        'name': 'Swisslog',
        'factset_id': 'TBD',
        'filepath': DATA_DIR / 'swisslog_supplychain.csv'
    },
    'tgw': {
        'name': 'TGW',
        'factset_id': 'TBD',
        'filepath': DATA_DIR / 'tgw_supplychain.csv'
    }
}

# Emissions columns to include
EMISSIONS_COLUMNS = [
    'di_319410', 'di_319411', 'di_319413', 'di_376883',  # Scope 1
    'di_319414', 'di_376884', 'di_367750', 'di_376886',  # Scope 2
    'di_378459', 'di_368653', 'di_377767', 'di_368654', 'di_377768',  # Scope 3 - categories
    'di_368655', 'di_377405', 'di_368704', 'di_377406', 'di_368705',
    'di_377407', 'di_368706', 'di_377408', 'di_378680', 'di_378681',
    'di_378682', 'di_378683', 'di_378684', 'di_378685', 'di_368652',
    'di_377766', 'di_326737', 'di_368707', 'di_377409', 'di_378686',
    'di_319415', 'di_319412'  # Scope 3 totals
]

def load_common_mapping():
    """Load FactSet-Trucost-CDP mapping."""
    try:
        # Try data/outputs first, then data/processed
        output_file = Path("data/outputs/common_companies_by_year_cdp_trucost_factset_lseg_with_trucost_emissions.csv")
        processed_file = Path("data/processed/common_companies_by_year_cdp_trucost_factset_lseg_with_trucost_emissions.csv")
        
        if output_file.exists():
            df = pd.read_csv(output_file)
        elif processed_file.exists():
            df = pd.read_csv(processed_file)
        else:
            print(f"Common mapping not found in data/outputs or data/processed")
            return pd.DataFrame()
        
        print(f"Loaded common mapping: {len(df)} records")
        return df
    except Exception as e:
        print(f"Error loading common mapping: {e}")
        return pd.DataFrame()

def load_trucost_emissions():
    """Load Trucost emissions data."""
    try:
        trucost_file = "data/raw/Trucost (Access through WRDS)/260710 trucost pulic-ghg-2011to24.csv"
        if not Path(trucost_file).exists():
            print(f"Trucost file not found: {trucost_file}")
            return pd.DataFrame()
        
        df = pd.read_csv(trucost_file, low_memory=False)
        print(f"Loaded Trucost data: {len(df)} records")
        return df
    except Exception as e:
        print(f"Error loading Trucost: {e}")
        return pd.DataFrame()

def expand_tier_network(target_id, target_name, edges_df, common_df, all_suppliers, all_customers, current_tier=1, max_tier=3, direction='upstream'):
    """
    Recursively expand supply chain network to reach multiple tiers.
    Returns list of (node_id, node_name, tier, direction) tuples
    """
    nodes = []
    
    if current_tier > max_tier:
        return nodes
    
    if direction == 'upstream':
        # Find suppliers of current node
        tier_edges = edges_df[edges_df['related_factset_id'] == target_id].copy()
        
        for _, row in tier_edges.iterrows():
            supplier_id = row['related_factset_id']
            supplier_name = row['related_factset_name']
            
            if supplier_id not in all_suppliers:
                all_suppliers.add(supplier_id)
                nodes.append((supplier_id, supplier_name, current_tier, 'upstream'))
                
                # Recursively find tier 2, 3
                if current_tier < max_tier:
                    sub_nodes = expand_tier_network(
                        supplier_id, supplier_name, edges_df, common_df,
                        all_suppliers, all_customers, current_tier + 1, max_tier, 'upstream'
                    )
                    nodes.extend(sub_nodes)
    
    else:  # downstream
        # Find customers of current node
        tier_edges = edges_df[edges_df['target_factset_id'] == target_id].copy()
        
        for _, row in tier_edges.iterrows():
            customer_id = row['related_factset_id']
            customer_name = row['related_factset_name']
            
            if customer_id not in all_customers:
                all_customers.add(customer_id)
                nodes.append((customer_id, customer_name, current_tier, 'downstream'))
                
                # Recursively find tier 2, 3
                if current_tier < max_tier:
                    sub_nodes = expand_tier_network(
                        customer_id, customer_name, edges_df, common_df,
                        all_suppliers, all_customers, current_tier + 1, max_tier, 'downstream'
                    )
                    nodes.extend(sub_nodes)
    
    return nodes

def get_latest_emissions(company_id, trucost_df, common_df):
    """Get latest available emissions data for a company."""
    if trucost_df.empty or common_df.empty:
        return {}
    
    # Map company ID through common mapping (use factset_entity_id)
    mapping = common_df[common_df['factset_entity_id'] == company_id]
    if mapping.empty:
        return {}
    
    trucost_id = mapping['trucost_companyid'].iloc[0]
    
    if pd.isna(trucost_id):
        return {}
    
    # Get latest year data
    company_data = trucost_df[trucost_df['companyid'] == trucost_id].copy()
    if company_data.empty:
        return {}
    
    # Get latest year (use fiscalyear column)
    latest_year = company_data['fiscalyear'].max()
    latest_data = company_data[company_data['fiscalyear'] == latest_year].iloc[0]
    
    emissions = {'emissions_year': int(latest_year) if not pd.isna(latest_year) else np.nan}
    for col in EMISSIONS_COLUMNS:
        if col in latest_data.index:
            emissions[col] = latest_data[col]
        else:
            emissions[col] = np.nan
    
    return emissions

def build_network_for_company(company_key, company_info, common_df, trucost_df):
    """Build complete Tier 1-3 network for a warehouse company."""
    
    company_name = company_info['name']
    filepath = company_info['filepath']
    
    print(f"\n{'='*80}")
    print(f"Building network for {company_name}")
    print(f"{'='*80}")
    
    # Load supply chain data
    try:
        edges_raw = pd.read_csv(filepath)
        print(f"  Loaded {len(edges_raw)} direct relationships")
    except Exception as e:
        print(f"  ERROR loading {filepath}: {e}")
        return False
    
    # Discover target company ID and name
    if edges_raw.empty:
        print(f"  ERROR: No supply chain data")
        return False
    
    target_id = edges_raw['target_factset_id'].iloc[0]
    target_name = edges_raw['target_factset_name'].iloc[0]
    company_info['factset_id'] = target_id
    
    print(f"  Target: {target_name} ({target_id})")
    
    # Build complete node list
    all_nodes = {target_id: (target_name, 0, None)}  # target is tier 0
    all_suppliers = {target_id}
    all_customers = {target_id}
    
    # Expand upstream (Tier 1-3 suppliers)
    print(f"  Expanding upstream suppliers...")
    upstream_nodes = expand_tier_network(target_id, target_name, edges_raw, common_df, all_suppliers, all_customers, 1, 3, 'upstream')
    for node_id, node_name, tier, direction in upstream_nodes:
        if node_id not in all_nodes:
            all_nodes[node_id] = (node_name, tier, 'upstream')
    
    # Expand downstream (Tier 1-3 customers)
    print(f"  Expanding downstream customers...")
    downstream_nodes = expand_tier_network(target_id, target_name, edges_raw, common_df, all_suppliers, all_customers, 1, 3, 'downstream')
    for node_id, node_name, tier, direction in downstream_nodes:
        if node_id not in all_nodes:
            all_nodes[node_id] = (node_name, tier, 'downstream')
    
    print(f"  Total nodes collected: {len(all_nodes)}")
    
    # Build nodes dataframe
    nodes_data = []
    for node_id, (node_name, tier, direction) in all_nodes.items():
        node_row = {
            'node_id': node_id,
            'node_name': node_name,
            'is_target': (node_id == target_id),
            'tier_upstream': tier if direction == 'upstream' else np.nan,
            'tier_downstream': tier if direction == 'downstream' else np.nan,
        }
        
        # Add emissions data
        emissions = get_latest_emissions(node_id, trucost_df, common_df)
        node_row.update(emissions)
        nodes_data.append(node_row)
    
    nodes_df = pd.DataFrame(nodes_data)
    
    # Build edges dataframe
    edges_data = []
    
    # Add all direct edges from raw data with tiers
    for _, row in edges_raw.iterrows():
        target_id_edge = row['target_factset_id']
        supplier_id = row['related_factset_id']
        
        edge_row = {
            'root_target_id': target_id,
            'root_target_name': target_name,
            'source_id': supplier_id,
            'target_id': target_id_edge,
            'source_name': row['related_factset_name'],
            'target_name': row['target_factset_name'],
            'direction': 'upstream',
            'tier': 1,
            'relationship_type': row.get('role', 'supplier'),
            'revenue_pct': row.get('relation_revenue_pct', np.nan),
            'relation_start_date': row.get('relation_start_date', ''),
            'relation_end_date': row.get('relation_end_date', ''),
        }
        edges_data.append(edge_row)
    
    edges_df = pd.DataFrame(edges_data)
    
    # Save files
    network_dir = OUTPUT_DIR / f"network_{company_key}"
    network_dir.mkdir(parents=True, exist_ok=True)
    
    nodes_file = network_dir / 'nodes.csv'
    edges_file = network_dir / 'edges.csv'
    
    nodes_df.to_csv(nodes_file, index=False)
    edges_df.to_csv(edges_file, index=False)
    
    print(f"  SAVED:")
    print(f"    - {nodes_file.relative_to('.')} ({len(nodes_df)} nodes)")
    print(f"    - {edges_file.relative_to('.')} ({len(edges_df)} edges)")
    
    return True

def main():
    print("\n" + "="*80)
    print("BUILDING TIER 1-3 SUPPLY CHAIN NETWORKS FOR WAREHOUSE COMPANIES")
    print("Enriched with Trucost emissions data, formatted for PowerBI")
    print("="*80)
    
    print("\n[1/3] Loading source data...")
    common_df = load_common_mapping()
    trucost_df = load_trucost_emissions()
    
    if common_df.empty or trucost_df.empty:
        print("ERROR: Missing critical source data")
        return
    
    print("\n[2/3] Building networks for each warehouse company...")
    
    success_count = 0
    for company_key, company_info in WAREHOUSE_COMPANIES.items():
        if build_network_for_company(company_key, company_info, common_df, trucost_df):
            success_count += 1
    
    print("\n[3/3] Summary")
    print(f"  Companies processed: {success_count}/{len(WAREHOUSE_COMPANIES)}")
    print(f"  Networks saved to: {OUTPUT_DIR.relative_to('.')}")
    
    # Create index file
    index_file = OUTPUT_DIR / 'INDEX.txt'
    with open(index_file, 'w') as f:
        f.write("WAREHOUSE COMPANY NETWORKS (Tier 1-3)\n")
        f.write("="*60 + "\n\n")
        for company_key, company_info in WAREHOUSE_COMPANIES.items():
            f.write(f"{company_info['name']:25s} ({company_info['factset_id']})\n")
            f.write(f"  Network: network_{company_key}/\n")
            f.write(f"    - nodes.csv: Company + all suppliers/customers (Tier 1-3)\n")
            f.write(f"    - edges.csv: All relationships with revenue_pct weights\n\n")
    
    print(f"\n  Index file: {index_file.relative_to('.')}")
    print("\n[SUCCESS] Supply chain networks ready for PowerBI import")

if __name__ == "__main__":
    main()

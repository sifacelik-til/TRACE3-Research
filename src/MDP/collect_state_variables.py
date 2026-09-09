"""
Collect state variables for MDP modeling from CDP, Trucost, FactSet, and LSEG data.
Output: A single DataFrame with all state variables for each company-year.
"""
from pathlib import Path
import pandas as pd
import numpy as np
import re
from typing import Dict, List, Optional

# ==========================================
# CONFIGURATION
# ==========================================
# Paths to your data files
CDP_DIR = Path(r"C:\Users\scelik\Desktop\TRACE3Code\data\outputs")
TRUCOST_FILE = Path(r"C:\Users\scelik\Desktop\TRACE3Code\data\raw\Trucost (Access through WRDS)\trucost_data.csv")
FACTSET_DIR = Path(r"C:\Users\scelik\Desktop\TRACE3Code\data\raw\FactSet")
LSEG_FILE = Path(r"C:\Users\scelik\Desktop\TRACE3Code\data\raw\LSEG\lseg_active_universe_10y.csv")

# Output file
OUTPUT_FILE = Path(r"C:\Users\scelik\Desktop\TRACE3Code\data\outputs\mdp_state_variables.csv")

# ==========================================
# HELPERS
# ==========================================

def load_cdp_data() -> pd.DataFrame:
    """Load all CDP answers and extract state variables."""
    cdp_files = list(CDP_DIR.glob("cdp_org_answers_*_long.csv"))
    if not cdp_files:
        raise FileNotFoundError(f"No CDP files found in {CDP_DIR}")

    dfs = []
    for f in cdp_files:
        df = pd.read_csv(f, dtype=str)
        dfs.append(df)

    cdp_df = pd.concat(dfs, ignore_index=True)
    return cdp_df

def load_trucost_data() -> pd.DataFrame:
    """Load Trucost supply chain emissions data."""
    if not TRUCOST_FILE.exists():
        raise FileNotFoundError(f"Trucost file not found: {TRUCOST_FILE}")

    df = pd.read_csv(TRUCOST_FILE, dtype=str, low_memory=False)
    return df

def load_factset_data() -> pd.DataFrame:
    """Load FactSet company data (revenue, capex, etc.)."""
    # Load sym_isin.txt for ISIN to company mapping
    sym_isin = pd.read_csv(
        FACTSET_DIR / "sym_isin_v1_full_11256" / "sym_isin.txt",
        sep="|", dtype=str, encoding="utf-8", low_memory=False
    )

    # Load sym_entity.txt for company details
    sym_entity = pd.read_csv(
        FACTSET_DIR / "sym_entity_v1_full_12328" / "sym_entity.txt",
        sep="|", dtype=str, encoding="utf-8", low_memory=False
    )

    # Load fundamental data (revenue, capex)
    try:
        fundamentals = pd.read_csv(
            FACTSET_DIR / "fundamentals_v1_full_12328" / "fundamentals.txt",
            sep="|", dtype=str, encoding="utf-8", low_memory=False
        )
    except FileNotFoundError:
        fundamentals = pd.DataFrame()

    # Merge data
    factset_df = sym_isin.merge(sym_entity, on="FSYM_ID", how="left")
    if not fundamentals.empty:
        factset_df = factset_df.merge(fundamentals, on="FSYM_ID", how="left")

    return factset_df

def load_lseg_data() -> pd.DataFrame:
    """Load LSEG ESG scores."""
    if not LSEG_FILE.exists():
        raise FileNotFoundError(f"LSEG file not found: {LSEG_FILE}")

    df = pd.read_csv(LSEG_FILE, dtype=str, low_memory=False)
    return df

def extract_emissions(df: pd.DataFrame, org_name: str, year: int) -> Dict[str, float]:
    """Extract emissions data from CDP answers."""
    org_df = df[(df["org_name_matched"].str.contains(org_name, case=False, na=False)) &
                (df["year"] == year)]

    current_emissions = 0.0
    emissions_intensity = 0.0
    renewable_pct = 0.0

    # Extract total emissions (Scope 1 + 2 + 3)
    emissions_cols = ["Scope 1", "Scope 2", "Scope 3", "Total GHG emissions"]
    for col in emissions_cols:
        matches = org_df[org_df["question_text"].str.contains(col, case=False, na=False)]
        for _, row in matches.iterrows():
            try:
                val = float(re.sub(r"[^\d.]", "", str(row["answer"])))
                current_emissions += val
            except ValueError:
                pass

    # Extract emissions intensity
    intensity_cols = ["emissions intensity", "tCO2e per $ revenue"]
    for col in intensity_cols:
        matches = org_df[org_df["question_text"].str.contains(col, case=False, na=False)]
        for _, row in matches.iterrows():
            try:
                emissions_intensity = float(re.sub(r"[^\d.]", "", str(row["answer"])))
            except ValueError:
                pass

    # Extract renewable energy percentage
    renewable_cols = ["renewable energy", "% renewable electricity"]
    for col in renewable_cols:
        matches = org_df[org_df["question_text"].str.contains(col, case=False, na=False)]
        for _, row in matches.iterrows():
            try:
                renewable_pct = float(re.sub(r"[^\d.]", "", str(row["answer"])))
            except ValueError:
                pass

    return {
        "current_emissions": current_emissions,
        "emissions_intensity": emissions_intensity,
        "renewable_energy_pct": renewable_pct,
    }

def extract_targets(df: pd.DataFrame, org_name: str, year: int) -> Dict[str, str]:
    """Extract target ambition and coverage from CDP answers."""
    org_df = df[(df["org_name_matched"].str.contains(org_name, case=False, na=False)) &
                (df["year"] == year)]

    target_ambition = "None"
    target_coverage = 0.0

    # Extract target ambition (e.g., net-zero, SBTi)
    target_cols = ["target", "net-zero", "SBTi", "science-based target"]
    for col in target_cols:
        matches = org_df[org_df["question_text"].str.contains(col, case=False, na=False)]
        for _, row in matches.iterrows():
            if "net-zero" in str(row["answer"]).lower():
                target_ambition = "Net-zero"
            elif "sbt" in str(row["answer"]).lower() or "science-based" in str(row["answer"]).lower():
                target_ambition = "SBTi"

    # Extract target coverage (% of emissions covered)
    coverage_cols = ["target coverage", "% emissions covered"]
    for col in coverage_cols:
        matches = org_df[org_df["question_text"].str.contains(col, case=False, na=False)]
        for _, row in matches.iterrows():
            try:
                target_coverage = float(re.sub(r"[^\d.]", "", str(row["answer"])))
            except ValueError:
                pass

    return {
        "target_ambition": target_ambition,
        "target_coverage": target_coverage,
    }

def extract_supplier_data(df: pd.DataFrame, org_name: str, year: int) -> Dict[str, float]:
    """Extract supplier-related state variables from CDP answers."""
    org_df = df[(df["org_name_matched"].str.contains(org_name, case=False, na=False)) &
                (df["year"] == year)]

    num_suppliers = 0
    suppliers_with_targets_pct = 0.0
    suppliers_disclosing_pct = 0.0
    suppliers_emissions = 0.0
    suppliers_engagement_level = "None"

    # Extract number of suppliers
    supplier_cols = ["number of suppliers", "total suppliers"]
    for col in supplier_cols:
        matches = org_df[org_df["question_text"].str.contains(col, case=False, na=False)]
        for _, row in matches.iterrows():
            try:
                num_suppliers = int(re.sub(r"[^\d]", "", str(row["answer"])))
            except ValueError:
                pass

    # Extract % of suppliers with targets
    targets_cols = ["% suppliers with targets", "suppliers with science-based targets"]
    for col in targets_cols:
        matches = org_df[org_df["question_text"].str.contains(col, case=False, na=False)]
        for _, row in matches.iterrows():
            try:
                suppliers_with_targets_pct = float(re.sub(r"[^\d.]", "", str(row["answer"])))
            except ValueError:
                pass

    # Extract % of suppliers disclosing
    disclosing_cols = ["% suppliers disclosing", "suppliers disclosing emissions"]
    for col in disclosing_cols:
        matches = org_df[org_df["question_text"].str.contains(col, case=False, na=False)]
        for _, row in matches.iterrows():
            try:
                suppliers_disclosing_pct = float(re.sub(r"[^\d.]", "", str(row["answer"])))
            except ValueError:
                pass

    # Extract supplier engagement level
    engagement_cols = ["supplier engagement", "engagement level"]
    for col in engagement_cols:
        matches = org_df[org_df["question_text"].str.contains(col, case=False, na=False)]
        for _, row in matches.iterrows():
            answer = str(row["answer"]).lower()
            if "advanced" in answer or "collaborative" in answer:
                suppliers_engagement_level = "Advanced"
            elif "basic" in answer:
                suppliers_engagement_level = "Basic"
            elif "none" in answer:
                suppliers_engagement_level = "None"

    return {
        "num_suppliers": num_suppliers,
        "suppliers_with_targets_pct": suppliers_with_targets_pct,
        "suppliers_disclosing_pct": suppliers_disclosing_pct,
        "suppliers_emissions": suppliers_emissions,
        "suppliers_engagement_level": suppliers_engagement_level,
    }

def extract_esg_score(df: pd.DataFrame, org_name: str, year: int) -> Dict[str, float]:
    """Extract ESG score from LSEG data."""
    org_df = df[df["lseg_company_name"].str.contains(org_name, case=False, na=False)]
    if org_df.empty:
        return {"esg_score": np.nan}

    # Filter by year (if available)
    if "lseg_year" in org_df.columns:
        org_df = org_df[org_df["lseg_year"] == year]

    if org_df.empty:
        return {"esg_score": np.nan}

    esg_score = org_df["lseg_esg_score"].iloc[0]
    try:
        esg_score = float(esg_score)
    except (ValueError, TypeError):
        esg_score = np.nan

    return {"esg_score": esg_score}

def extract_financials(df: pd.DataFrame, org_name: str, year: int) -> Dict[str, float]:
    """Extract revenue and capex from FactSet data."""
    org_df = df[df["ENTITY_PROPER_NAME"].str.contains(org_name, case=False, na=False)]
    if org_df.empty:
        return {"revenue": np.nan, "capex_budget": np.nan}

    # Extract revenue
    revenue = org_df.get("REVENUE", np.nan).iloc[0]
    try:
        revenue = float(re.sub(r"[^\d.]", "", str(revenue)))
    except (ValueError, TypeError):
        revenue = np.nan

    # Extract capex (if available)
    capex = org_df.get("CAPEX", np.nan).iloc[0]
    try:
        capex = float(re.sub(r"[^\d.]", "", str(capex)))
    except (ValueError, TypeError):
        capex = np.nan

    return {
        "revenue": revenue,
        "capex_budget": capex,
    }

def extract_trucost_supplier_emissions(df: pd.DataFrame, org_name: str, year: int) -> Dict[str, float]:
    """Extract supplier emissions from Trucost data."""
    org_df = df[df["trucost_companyname"].str.contains(org_name, case=False, na=False)]
    if org_df.empty:
        return {"suppliers_emissions": np.nan, "suppliers_emissions_intensity": np.nan}

    # Extract total supplier emissions
    emissions = org_df.get("total_emissions", np.nan).iloc[0]
    try:
        suppliers_emissions = float(emissions)
    except (ValueError, TypeError):
        suppliers_emissions = np.nan

    # Extract supplier emissions intensity
    intensity = org_df.get("emissions_intensity", np.nan).iloc[0]
    try:
        suppliers_emissions_intensity = float(intensity)
    except (ValueError, TypeError):
        suppliers_emissions_intensity = np.nan

    return {
        "suppliers_emissions": suppliers_emissions,
        "suppliers_emissions_intensity": suppliers_emissions_intensity,
    }

# ==========================================
# MAIN LOGIC
# ==========================================

def main():
    # Load all data sources
    print("Loading data sources...")
    cdp_df = load_cdp_data()
    trucost_df = load_trucost_data()
    factset_df = load_factset_data()
    lseg_df = load_lseg_data()

    # Get unique organizations and years
    orgs = cdp_df["org_name_matched"].unique()
    years = range(2019, 2026)  # 2019-2025

    all_states = []

    for org in orgs:
        for year in years:
            print(f"Processing {org} ({year})...")

            # Initialize state
            state = {
                "organization": org,
                "year": year,
            }

            # --- Focal Company Variables ---
            # Emissions, targets, etc.
            emissions_data = extract_emissions(cdp_df, org, year)
            state.update(emissions_data)

            targets_data = extract_targets(cdp_df, org, year)
            state.update(targets_data)

            # Financials (revenue, capex)
            financials_data = extract_financials(factset_df, org, year)
            state.update(financials_data)

            # ESG score
            esg_data = extract_esg_score(lseg_df, org, year)
            state.update(esg_data)

            # --- Supply Chain Variables ---
            supplier_data = extract_supplier_data(cdp_df, org, year)
            state.update(supplier_data)

            # Trucost supplier emissions
            trucost_data = extract_trucost_supplier_emissions(trucost_df, org, year)
            state.update(trucost_data)

            # Add to results
            all_states.append(state)

    # Convert to DataFrame
    state_df = pd.DataFrame(all_states)

    # Save to CSV
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    state_df.to_csv(OUTPUT_FILE, index=False)

    print(f"✅ Saved state variables to: {OUTPUT_FILE}")
    print(f"Total states: {len(state_df)}")

if __name__ == "__main__":
    main()
#
# state_df = pd.read_csv("mdp_state_variables.csv")
# state_df["emissions_bin"] = pd.cut(state_df["current_emissions"], bins=[0, 10000, 50000, 100000, np.inf])
# state_df["renewable_bin"] = pd.cut(state_df["renewable_energy_pct"], bins=[0, 25, 50, 75, 100])
# states = state_df.to_dict("records")
# from mdptoolbox import MDP
# import numpy as np
#
# # Define transition probabilities, rewards, etc.
# P = np.random.rand(len(states), len(actions), len(states))  # Example
# R = np.random.rand(len(states), len(actions))  # Example
#
# mdp = MDP(transitions=P, reward=R, discount=0.9)
# mdp.run()
# policy = mdp.policy
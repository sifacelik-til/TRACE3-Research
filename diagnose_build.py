#!/usr/bin/env python3
"""Diagnostic script to check if build can run."""

import sys
from pathlib import Path

print("=" * 60)
print("BUILD SCRIPT DIAGNOSTICS")
print("=" * 60)

# Check if files exist
files_to_check = [
    "data/raw/FactSet/ent_supply_chain_v1_full_3856/ent_scr_relationships.txt",
    "data/raw/FactSet/sym_entity_v1_full_12328/sym_entity.txt",
    "data/raw/Trucost (Access through WRDS)/260710 trucost pulic-ghg-2011to24.csv",
]

print("\n1. Checking required files:")
for f in files_to_check:
    exists = Path(f).exists()
    size = Path(f).stat().st_size if exists else 0
    status = "OK" if exists else "MISSING"
    print(f"  [{status}] {f} ({size:,} bytes)")

# Check if build script exists
print(f"\n2. Build script: {'OK' if Path('src_try/build_tier3_supply_network.py').exists() else 'MISSING'}")

# Try to import
print("\n3. Importing build script...")
try:
    from src_try.build_tier3_supply_network import read_pipe, normalize_cols, main
    print("  [OK] Successfully imported functions and main")
    
    # Load and check entity
    sym_file = "data/raw/FactSet/sym_entity_v1_full_12328/sym_entity.txt"
    print(f"\n4. Checking entity 05J58S-E in {sym_file}...")
    
    sym = normalize_cols(read_pipe(sym_file))
    print(f"  Loaded {len(sym)} entities")
    
    # Check if entity exists
    entity_col = sym.iloc[:, 0]
    if "05J58S-E" in entity_col.values:
        print(f"  [OK] Entity 05J58S-E found!")
        idx = sym[entity_col == "05J58S-E"].index[0]
        print(f"       Name: {sym.iloc[idx, 1]}")
    else:
        print(f"  [NOT FOUND] Entity 05J58S-E NOT found")
        similar = sym[entity_col.str.contains("05J58", na=False)]
        print(f"  Found {len(similar)} similar entities starting with 05J58")
        if len(similar) > 0:
            print(f"  Examples: {list(similar.iloc[:3, 0])}")
            
    print("\n5. Running build_tier3_supply_network...")
    sys.argv = ['diagnose_build.py', '--target', '05J58S-E']
    main()
    print("  [OK] Build completed")
            
except Exception as e:
    print(f"  [ERROR] Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("Checking output...")
if Path("data/processed").exists():
    import os
    for root, dirs, files in os.walk("data/processed"):
        level = root.replace("data/processed", "").count(os.sep)
        indent = " " * 2 * level
        print(f'{indent}{os.path.basename(root)}/')
        subindent = " " * 2 * (level + 1)
        for file in files:
            fsize = Path(root) / file
            print(f'{subindent}{file} ({fsize.stat().st_size:,} bytes)')

print("\n" + "=" * 60)

"""Four-source Venn diagram of company-year coverage, 2016–2025.

Run from the project root::

    python -m src.dataset_readers.plot_company_year_venn

The FactSet universe is every buyer or supplier in the saved Tier-1 relationship
detail. LSEG requires a numeric ESG Score. Trucost requires nonmissing Scope 1,
location-based Scope 2, and upstream Scope 3; eligible upstream Scope 3 values
are retained between the year-specific 1st and 99th percentiles. The comparison
universe is CDP, FactSet, or LSEG company-years; Trucost coverage is checked
within that universe. Trucost-only records are not counted.
Matches use normalized company names and exact shared ISINs. A company observed
in two years contributes two company-year elements.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import math
import re
import sys
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

import pandas as pd
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from src.dataset_readers.common_companies_by_year import (  # noqa: E402
    CDP_RAW_ROOT,
    LSEG_RAW_PATH,
    TRUCOST_RAW_PATH,
    normalize_name,
    read_cdp_organizations_for_year,
)


YEARS = range(2016, 2025)
SOURCES = ("Trucost", "FactSet", "LSEG", "CDP")
FACTSET_DETAIL = (
    ROOT / "data/processed/supplier_factset_lseg/company_year_supplier_detail.csv.gz"
)
OUTPUT_DIR = ROOT / "data/outputs/dataset_readers/company_year_venn"
ISIN_RE = re.compile(r"\b[A-Z]{2}[A-Z0-9]{9}[0-9]\b")


def isins(value: object) -> set[str]:
    if isinstance(value, set):
        return {str(item).upper() for item in value if item}
    if pd.isna(value):
        return set()
    return set(ISIN_RE.findall(str(value).upper()))


def add_record(members, isin_names, source, year, name, isin_value=None, years=YEARS):
    if pd.isna(year) or int(year) not in years:
        return
    key = normalize_name(name)
    if not key:
        return
    year = int(year)
    members[source].add((year, key))
    for isin in isins(isin_value):
        isin_names[(year, isin)].add(key)


def load_members(years=YEARS, return_factset_ids=False):
    years = tuple(years)
    members = {source: set() for source in SOURCES}
    isin_names = defaultdict(set)
    factset_ids = defaultdict(set)

    for chunk in pd.read_csv(
        LSEG_RAW_PATH,
        usecols=["FiscalYear", "Company Common Name", "ISIN", "ESG Score"],
        chunksize=100_000,
        dtype="string",
        encoding="utf-8-sig",
        encoding_errors="replace",
    ):
        chunk["FiscalYear"] = pd.to_numeric(chunk["FiscalYear"], errors="coerce")
        chunk["ESG Score"] = pd.to_numeric(chunk["ESG Score"], errors="coerce")
        for year, name, isin in chunk.loc[
            chunk["FiscalYear"].isin(years) & chunk["ESG Score"].notna(),
            ["FiscalYear", "Company Common Name", "ISIN"],
        ].drop_duplicates().itertuples(index=False, name=None):
            add_record(members, isin_names, "LSEG", year, name, isin, years=years)

    # A FactSet company can occur on either side of a Tier-1 relationship.
    for chunk in pd.read_csv(
        FACTSET_DETAIL,
        usecols=[
            "year", "company_id", "company_name", "company_isins",
            "supplier_id", "supplier_name", "supplier_isin",
        ],
        compression="gzip",
        chunksize=100_000,
        dtype="string",
    ):
        chunk["year"] = pd.to_numeric(chunk["year"], errors="coerce")
        for year, buyer_id, buyer, buyer_isins, supplier_id, supplier, supplier_isin in chunk.loc[
            chunk["year"].isin(years),
            [
                "year", "company_id", "company_name", "company_isins",
                "supplier_id", "supplier_name", "supplier_isin",
            ],
        ].itertuples(index=False, name=None):
            add_record(members, isin_names, "FactSet", year, buyer, buyer_isins, years=years)
            add_record(members, isin_names, "FactSet", year, supplier, supplier_isin, years=years)
            for entity_id, name in ((buyer_id, buyer), (supplier_id, supplier)):
                if pd.notna(entity_id) and pd.notna(name):
                    entity_id = str(entity_id).strip()
                    name_key = normalize_name(name)
                    if entity_id and name_key:
                        factset_ids[(int(year), name_key)].add(entity_id)

    print("LSEG and FactSet source scans complete; reading CDP summaries.", flush=True)

    for year in years:
        cdp = read_cdp_organizations_for_year(year, CDP_RAW_ROOT)
        if cdp.empty:
            raise RuntimeError(f"No CDP Summary data found for {year}; cannot label it zero coverage.")
        for name, cdp_isins in cdp[["cdp_name", "cdp_isins"]].itertuples(index=False, name=None):
            add_record(members, isin_names, "CDP", year, name, cdp_isins, years=years)
        print(f"CDP {year}: {len(cdp):,} organizations", flush=True)

    # Trucost's full extract contains millions of unrelated records. Check
    # coverage only for names present in at least one of the other three
    # sources; this bounds memory without changing the four-way intersection.
    candidate_names = set().union(members["LSEG"], members["FactSet"], members["CDP"])

    @lru_cache(maxsize=100_000)
    def normalized(name):
        return normalize_name(name)

    opener = gzip.open if TRUCOST_RAW_PATH.suffix == ".gz" else open
    complete_trucost = {}

    def emission(row, index):
        try:
            value = float(row[index])
            return value if math.isfinite(value) else None
        except (ValueError, IndexError):
            return None

    with opener(TRUCOST_RAW_PATH, "rt", newline="", encoding="utf-8", errors="replace") as file:
        reader = csv.reader(file)
        header = next(reader)
        year_index, name_index = header.index("fiscalyear"), header.index("companyname")
        period_index = header.index("periodenddate")
        scope1_index = header.index("di_319413")
        scope2_index = header.index("di_319414")
        scope3_up_index = header.index("di_319415")
        valid_years = {str(year) for year in years}
        for row_number, row in enumerate(reader, start=1):
            if len(row) <= max(year_index, name_index, period_index, scope1_index, scope2_index, scope3_up_index):
                continue
            year_text = row[year_index][:4]
            if year_text in valid_years and row[name_index]:
                name_key = normalized(row[name_index])
                item = (int(year_text), name_key)
                if item in candidate_names:
                    scope1 = emission(row, scope1_index)
                    scope2 = emission(row, scope2_index)
                    scope3_up = emission(row, scope3_up_index)
                    if scope1 is not None and scope2 is not None and scope3_up is not None:
                        period = row[period_index]
                        if item not in complete_trucost or period > complete_trucost[item][0]:
                            complete_trucost[item] = (period, scope3_up)
            if row_number % 5_000_000 == 0:
                print(f"Trucost: scanned {row_number:,} rows", flush=True)
    del candidate_names

    filter_summary = []
    for year in years:
        year_values = np.fromiter(
            (scope3 for (item_year, _), (_, scope3) in complete_trucost.items() if item_year == year),
            dtype=float,
        )
        if year_values.size == 0:
            raise RuntimeError(f"No complete Trucost Scope 1/2/3-upstream rows for {year}.")
        lower, upper = np.quantile(year_values, [0.01, 0.99])
        kept = 0
        for item, (_, scope3) in complete_trucost.items():
            if item[0] == year and lower <= scope3 <= upper:
                members["Trucost"].add(item)
                kept += 1
        filter_summary.append({
            "year": year,
            "complete_candidate_company_years": int(year_values.size),
            "scope3_upstream_p01": float(lower),
            "scope3_upstream_p99": float(upper),
            "retained_after_trim": kept,
        })
    pd.DataFrame(filter_summary).to_csv(
        OUTPUT_DIR / f"trucost_filter_by_year_{min(years)}_{max(years)}.csv", index=False
    )
    del complete_trucost

    # Link differently spelled names only when they share an exact ISIN in
    # the same year. Names without an ISIN still match by normalized spelling.
    parent = {}

    def find(item):
        parent.setdefault(item, item)
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for (year, _), names in isin_names.items():
        ordered = sorted(names)
        if len(ordered) < 2:
            continue
        anchor = (year, ordered[0])
        for name in ordered[1:]:
            other = (year, name)
            parent[find(other)] = find(anchor)

    canonical = {
        source: {find(item) for item in source_members}
        for source, source_members in members.items()
    }
    for source in SOURCES:
        missing = set(years) - {year for year, _ in canonical[source]}
        if missing:
            raise RuntimeError(f"{source} has no records in years {sorted(missing)}")
    if not return_factset_ids:
        return canonical
    canonical_factset_ids = defaultdict(set)
    for item, entity_ids in factset_ids.items():
        canonical_factset_ids[find(item)].update(entity_ids)
    return canonical, canonical_factset_ids


def exact_regions(sets):
    universe = set().union(*sets.values())
    masks = Counter(
        sum((1 << index) for index, source in enumerate(SOURCES) if item in sets[source])
        for item in universe
    )
    rows = []
    for mask in range(1, 1 << len(SOURCES)):
        rows.append({
            "mask": mask,
            "sources": " + ".join(source for index, source in enumerate(SOURCES)
                                  if mask & (1 << index)),
            "company_years": masks[mask],
            "counted": mask != 1,
        })
    return rows


def plot_regions(regions):
    """Draw a schematic four-set Venn; geometry is not proportional to counts."""
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.patches import Ellipse

    # These ellipses have all 15 nonempty geometric regions. The accompanying
    # table gives exact counts when a small region cannot fit a long number.
    shapes = [
        (0.0434, 0.3714, 1.3153, 0.9592, -10.5943),
        (-0.3100, 0.1387, 1.8053, 0.7601, 60.5713),
        (0.2362, 0.0331, 1.8363, 0.6621, 72.6538),
        (-0.2662, -0.1927, 1.5392, 1.0001, 157.0358),
    ]
    colors = ["#4C78A8", "#F58518", "#54A24B", "#B279A2"]
    x, y = np.meshgrid(np.linspace(-2.2, 2.2, 701), np.linspace(-2.2, 2.2, 701))
    geometry = np.zeros(x.shape, dtype=np.uint8)
    for index, (cx, cy, a, b, angle) in enumerate(shapes):
        theta = np.deg2rad(angle)
        dx, dy = x - cx, y - cy
        u = dx * np.cos(theta) + dy * np.sin(theta)
        v = -dx * np.sin(theta) + dy * np.cos(theta)
        geometry |= (((u / a) ** 2 + (v / b) ** 2) <= 1).astype(np.uint8) << index

    fig, (ax, table_ax) = plt.subplots(
        1, 2, figsize=(17, 9), gridspec_kw={"width_ratios": [1.45, 1]}, facecolor="white"
    )
    ax.set_facecolor("white")
    for index, (cx, cy, a, b, angle) in enumerate(shapes):
        ax.add_patch(Ellipse(
            (cx, cy), 2 * a, 2 * b, angle=angle,
            facecolor=colors[index], edgecolor=colors[index], linewidth=2.2, alpha=0.18,
            label=SOURCES[index],
        ))
    counts = {}
    for row in regions:
        mask = row.get("mask")
        if mask is None:
            present = set(str(row["sources"]).split(" + "))
            mask = sum(1 << index for index, source in enumerate(SOURCES) if source in present)
        counts[int(mask)] = int(row["company_years"])
    for mask in range(1, 16):
        if mask == 1:
            continue  # Trucost-only company-years are outside the comparison universe.
        yy, xx = np.where(geometry == mask)
        if len(xx) == 0:
            raise RuntimeError(f"Diagram geometry has no region for mask {mask}.")
        middle_x, middle_y = x[yy, xx].mean(), y[yy, xx].mean()
        best = np.argmin((x[yy, xx] - middle_x) ** 2 + (y[yy, xx] - middle_y) ** 2)
        ax.text(
            x[yy[best], xx[best]], y[yy[best], xx[best]], f"{counts[mask]:,}",
            ha="center", va="center", fontsize=8, color="#16202A",
            bbox={"boxstyle": "round,pad=0.12", "facecolor": "white", "edgecolor": "none", "alpha": 0.8},
        )
    ax.set_xlim(-2.2, 2.2)
    ax.set_ylim(-2.2, 2.2)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.legend(loc="lower center", ncol=4, bbox_to_anchor=(0.5, -0.04), frameon=False)

    table_ax.axis("off")
    abbreviations = ("T", "F", "L", "C")
    rows = [
        [" + ".join(abbreviations[index] for index in range(4) if mask & (1 << index)),
         "not measured" if mask == 1 else f"{counts[mask]:,}"]
        for mask in range(1, 16)
    ]
    table = table_ax.table(
        cellText=rows, colLabels=["Exclusive region", "Company-years"],
        cellLoc="left", colLoc="left", loc="center", colWidths=[0.56, 0.38],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.6)
    for (row, _), cell in table.get_celld().items():
        cell.set_edgecolor("#E2E8EE")
        cell.set_facecolor("#EAF1F6" if row == 0 else "white" if row % 2 else "#F6F8FA")
    fig.suptitle("Company-year overlap across Trucost, FactSet, LSEG, and CDP (2016–2025)", fontsize=15)
    fig.text(
        0.5, 0.025,
        "Universe: CDP, FactSet, or LSEG company-years; Trucost-only records are not measured.\n"
        "LSEG requires ESG Score. Trucost requires Scope 1, location-based Scope 2, and upstream Scope 3; "
        "upstream Scope 3 is within each year's 1st–99th percentiles.\n"
        "Matches use normalized names and shared exact ISINs. Ellipse areas are schematic.",
        ha="center", fontsize=10,
    )
    fig.tight_layout(rect=[0, 0.12, 1, 0.94])
    fig.savefig(OUTPUT_DIR / "company_year_venn_2016_2024.pdf", bbox_inches="tight", facecolor="white")
    fig.savefig(OUTPUT_DIR / "company_year_venn_2016_2024.png", dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--counts-only", action="store_true", help="Calculate counts without plotting")
    parser.add_argument("--plot-existing", action="store_true", help="Plot the existing exact-region CSV")
    args = parser.parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    region_path = OUTPUT_DIR / "venn_exact_regions_2016_2024.csv"
    if args.plot_existing:
        plot_regions(pd.read_csv(region_path).to_dict("records"))
        return

    sets = load_members()

    regions = exact_regions(sets)
    with region_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["mask", "sources", "company_years", "counted"])
        writer.writeheader()
        writer.writerows(regions)

    rows = []
    for year in YEARS:
        yearly = {source: {item for item in sets[source] if item[0] == year} for source in SOURCES}
        rows.append({
            "year": year,
            **{source.lower(): len(yearly[source]) for source in SOURCES},
            "all_four": len(set.intersection(*yearly.values())),
        })
    pd.DataFrame(rows).to_csv(OUTPUT_DIR / "venn_by_year_2016_2025.csv", index=False)
    print(pd.DataFrame(rows).to_string(index=False))
    print("All four, pooled company-years:", len(set.intersection(*sets.values())))

    if not args.counts_only:
        plot_regions(regions)


if __name__ == "__main__":
    main()

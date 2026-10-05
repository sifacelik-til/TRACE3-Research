#!/usr/bin/env python3
"""
missing_by_year.py
==================

Per-year missing-data audit for the EXACT columns resolved by your
iter_lseg() and iter_trucost() functions.

LSEG (CSV) covers:
    keys        FiscalYear, Company Common Name, ISIN, Instrument, NAICS sector
    financials  Revenue (all variants), Inventory Turnover, Number of Employees,
                Gross Profit, Operating Profit
    ESG         ESG Score, Policy Emissions, Internal/Cross Carbon Pricing,
                renewable-energy columns, Energy Use Total, Emissions Target
                Type, long-term target coverage %, CSR Sustainability
                External Audit
    policies    the 27 policy/flag columns listed in iter_lseg()

Trucost (Stata .dta or CSV - auto-detected) covers:
    fiscalyear, companyname, isin, companyid, revenue (di_319522),
    Scope 1 (di_319413), Scope 2 (di_319414),
    Scope 3 upstream (di_319415), Scope 3 downstream (di_326737),
    Scope 1/2/3-up/3-down intensities (di_319407/319408/319409/326738).

Per year it reports:
    * % missing and # missing for every needed column
    * zero counts for numeric fields (emissions/revenue reported as 0)
    * share_true for flag fields (True/False policies among answered rows)
    * group coverage, e.g. % rows where ALL revenue variants are missing
    * policy coverage: average % missing across the 27 policy columns
    * YoY change in missing % per field, and a field-level summary
      (first-year vs last-year coverage, trend)
    * ISIN+Year overlap between Trucost and LSEG

Run:
    python missing_by_year.py --list-columns     # inspect headers first
    python missing_by_year.py
    python missing_by_year.py --start-year 2015 --end-year 2024

Outputs (in ../reports/missing_analysis/):
    lseg_missing_by_year_wide.csv        lseg_missing_by_year_long.csv
    lseg_policies_missing_long.csv       lseg_field_summary.csv
    lseg_missing_yoy_delta.csv
    trucost_missing_by_year_wide.csv     trucost_missing_by_year_long.csv
    trucost_field_summary.csv            trucost_missing_yoy_delta.csv
    coverage_overlap_by_year.csv
    lseg_missing_heatmap.png             lseg_policies_heatmap.png
    trucost_missing_heatmap.png          missing_by_year_lines.png
    missing_by_year.log
"""

from __future__ import annotations

import argparse
from datetime import datetime
from html import escape
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:  # plots are optional
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

# ============================================================================
# 1. CONFIG
# ============================================================================
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRUCOST_RAW_PATH = (PROJECT_ROOT / "data" / "raw" / "Trucost (Access through WRDS)"
                    / "260710 trucost pulic-ghg-2011to24.csv")
LSEG_RAW_PATH = PROJECT_ROOT / "data" / "raw" / "LSEG" / "lseg_full_universe.csv"
OUTPUT_DIR = PROJECT_ROOT / "reports" / "missing_analysis"

YEAR_RANGE = (2014, 2025)          # e.g. (2011, 2024); None = no filter

NA_TOKENS = ["na", "n/a", "n.a.", "-", "--", "null", "none", "nan",
             "#n/a", "not available", "unknown", "unavailable"]

TRUE_SET = {"true", "yes", "y", "1"}
FALSE_SET = {"false", "no", "n", "0"}

# The policy/flag columns from your iter_lseg()
POLICY_COLUMNS = [
    "Climate Policy Statement",
    "Policy Emissions",
    "Policy Energy Efficiency",
    "Resource Reduction Policy",
    "Policy Environmental Supply Chain",
    "Policy Sustainable Packaging",
    "Renewable/Clean Energy Products",
    "Take-back and Recycling Initiatives",
    "Hybrid Vehicles",
    "Percentage of Green Products",
    "Environmental Products",
    "Eco-Design Products",
    "CSR Sustainability Reporting",
    "Targets Energy Efficiency",
    "Transition Plan Offsets",
    "Internal Carbon Pricing",
    "Climate Change Risks and Opportunities Strategy",
    "Supplier Environmental Commitment",
    "Supplier Environmental Policy Communication",
    "Supplier Environmental Policy Training",
    "Supplier Environmental Risk Assessment",
    "Environmental Supply Chain Management",
    "Environmental Supply Chain Monitoring",
    "Env Supply Chain Partnership Termination",
    "Environmental Materials Sourcing",
    "ISO 14000 or EMS",
]

# Canonical fields that must be numeric (coerced with errors="coerce")
NUMERIC_CANONS = {
    "revenue", "inventory_turnover", "employees", "gross_profit",
    "operating_profit", "esg_score", "target_coverage", "carbon_price_numeric",
    "renewable_total", "renewable_components", "energy_use",
    "revenue_trucost", "scope1", "scope2", "scope3_upstream",
    "scope3_downstream", "scope1_intensity", "scope2_intensity",
    "scope3_upstream_intensity", "scope3_downstream_intensity",
}


# ============================================================================
# 2. Column-resolution helpers (same contract as your iter_* code)
# ============================================================================
def find_column(header, patterns, required=True):
    """First real column whose name contains one of `patterns` (case-insensitive)."""
    cols = (list(header.columns) if isinstance(header, pd.DataFrame)
            else list(header))
    for pat in patterns:
        for col in cols:
            if pat.lower() in str(col).lower():
                return col
    if required:
        raise KeyError(f"None of {patterns} found in header")
    return None


def find_columns(header, patterns):
    """ALL columns whose name contains any of `patterns` (case-insensitive)."""
    cols = (list(header.columns) if isinstance(header, pd.DataFrame)
            else list(header))
    return [c for c in cols
            if any(p.lower() in str(c).lower() for p in patterns)]


def read_header(path: str | Path):
    """Header of a .dta (via StataReader, like iter_trucost) or a CSV."""
    if Path(path).suffix.lower() == ".dta":
        with pd.io.stata.StataReader(path, convert_categoricals=False) as r:
            return list(r.variable_labels())     # variable names
    return pd.read_csv(path, nrows=0).columns


# ============================================================================
# 3. Field resolution - mirrors iter_lseg() / iter_trucost()
# ============================================================================
def resolve_lseg(lseg_path: Path):
    header = pd.read_csv(lseg_path, nrows=0)

    single = {
        "year":       find_column(header, ["FiscalYear", "fiscal_year", "year"]),
        "name":       find_column(header, ["Company Common Name", "company_name", "companyname"]),
        "sector":     find_column(header, ["NAICS International Industry Name", "NAICS Sector Name"]),
        "isin":       find_column(header, ["ISIN", "isin"]),
        "instrument": find_column(header, ["Instrument", "instrument", "RIC"], required=False),
        "target_ambition":  find_column(header, ["Emissions Target Type"], required=False),
        "verification":     find_column(header, ["CSR Sustainability External Audit"], required=False),
    }

    groups = {
        "revenue": find_columns(header, ["Revenue", "Total Revenue",
                                         "EU Taxonomy Total Revenue Amount"]),
        "inventory_turnover": find_columns(header, ["Inventory Turnover"]),
        "employees":          find_columns(header, ["Number of Employees"]),
        "gross_profit":       find_columns(header, ["Gross Profit"]),
        "operating_profit":   find_columns(header, ["Operating Profit"]),
        "esg_score":          find_columns(header, ["ESG Score", "LSEG ESG Score"]),
        "policy_emissions":   find_columns(header, ["Policy Emissions"]),
        "carbon_price":       find_columns(header, ["Internal Carbon Pricing",
                                                    "Internal Carbon Price per Tonne"]),
        "renewable_total":    find_columns(header, ["Energy Use Total",
                                                    "Total Renewable Energy",
                                                    "Renewable Energy Use"]),
        "renewable_components": find_columns(header, [
            "Renewable Energy Purchased", "Renewable Energy Produced",
            "Electricity Produced from Other Renewables"]),
        "energy_use":         find_columns(header, ["Energy Use Total",
                                                    "Total Energy Use from Properties"]),
        "target_coverage":    find_columns(header, [
            "Long Term Set 1 Percentage of GHG Emission Covered by Target"]),
    }

    policies = {name: find_column(header, [name], required=False)
                for name in POLICY_COLUMNS}
    policies = {k: v for k, v in policies.items() if v is not None}

    missing = [k for k, v in {**single, **policies}.items() if v is None]
    if missing:
        logging.warning("[lseg] unresolved optional columns: %s", missing)
    return single, groups, policies


def resolve_trucost(trucost_path: Path):
    header = read_header(trucost_path)

    fields = {
        "year":       find_column(header, ["fiscalyear", "fiscal_year", "year"]),
        "name":       find_column(header, ["companyname", "company_name", "company name"]),
        "isin":       find_column(header, ["isin"], required=False),
        "id":         find_column(header, ["companyid", "company_id", "institutionid"],
                                  required=False),
        # Metric fields are optional: vendor extracts can legitimately omit a
        # variable, and the report should still be useful for the fields present.
        "revenue_trucost": find_column(header, ["di_319522", "trucost_revenue",
                                                "total_revenue"], required=False),
        "scope1":            find_column(header, ["di_319413"], required=False),
        "scope2":            find_column(header, ["di_319414"], required=False),
        "scope3_upstream":   find_column(header, ["di_319415"], required=False),
        "scope3_downstream": find_column(header, ["di_326737"], required=False),
        "scope1_intensity":          find_column(header, ["di_319407"], required=False),
        "scope2_intensity":          find_column(header, ["di_319408"], required=False),
        "scope3_upstream_intensity": find_column(header, ["di_319409"], required=False),
        "scope3_downstream_intensity": find_column(header, ["di_326738"], required=False),
    }
    missing = [k for k, v in fields.items() if v is None]
    if missing:
        logging.warning("[trucost] unresolved optional columns: %s", missing)
    return {k: v for k, v in fields.items() if v is not None}


# ============================================================================
# 4. Loading
# ============================================================================
def load_lseg(lseg_path: Path, single, groups, policies,
              requested_years: set[int] | None = None):
    value_cols = [c for c in single.values() if c] \
        + [c for cols in groups.values() for c in cols] \
        + list(policies.values())
    wanted = list(dict.fromkeys(value_cols))
    id_cols = [single.get("isin"), single.get("instrument"), single.get("name")]
    id_cols = [c for c in id_cols if c]

    df = pd.read_csv(lseg_path, usecols=wanted, na_values=NA_TOKENS,
                     keep_default_na=True, low_memory=False,
                     dtype={c: "string" for c in id_cols})
    logging.info("[lseg] loaded %d rows x %d cols", len(df), len(df.columns))

    year_col = single["year"]
    df["_year"] = pd.to_numeric(df[year_col], errors="coerce")
    df = df.dropna(subset=["_year"])
    df["_year"] = df["_year"].astype(int)
    df = filter_years(df, requested_years)

    # numeric coercion for the fields that must be numeric
    for canon, cols in groups.items():
        if canon in NUMERIC_CANONS:
            for c in cols:
                df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in policies.values():
        df[c] = df[c].astype("string").str.strip()

    id_col = id_cols[0] if id_cols else None
    if id_col:
        dup = int(df.duplicated(subset=[id_col, "_year"]).sum())
        logging.info("[lseg] duplicate (%s, year) rows: %d", id_col, dup)
    return df, year_col, id_col


def load_trucost(trucost_path: Path, requested_years: set[int] | None = None):
    fields = resolve_trucost(trucost_path)
    wanted = list(dict.fromkeys(fields.values()))
    id_cols = [c for k, c in fields.items()
               if k in ("isin", "id", "name")]
    year_col = fields["year"]

    suffix = trucost_path.suffix.lower()
    if suffix == ".dta":
        df = pd.read_stata(trucost_path, columns=wanted,
                           convert_categoricals=False)
    else:
        df = pd.read_csv(trucost_path, usecols=wanted, na_values=NA_TOKENS,
                         keep_default_na=True, low_memory=False,
                         dtype={c: "string" for c in id_cols})
    logging.info("[trucost] loaded %d rows x %d cols", len(df), len(df.columns))

    df["_year"] = pd.to_numeric(df[year_col], errors="coerce")
    df = df.dropna(subset=["_year"])
    df["_year"] = df["_year"].astype(int)
    df = filter_years(df, requested_years)

    for k, c in fields.items():
        if k in NUMERIC_CANONS:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    id_col = id_cols[0] if id_cols else None
    if id_col:
        dup = int(df.duplicated(subset=[id_col, "_year"]).sum())
        logging.info("[trucost] duplicate (%s, year) rows: %d", id_col, dup)
    return df, year_col, id_col, fields


def filter_years(df, requested_years, start=None, end=None):
    if requested_years:
        df = df[df["_year"].isin(requested_years)]
    if start is not None:
        df = df[df["_year"] >= start]
    if end is not None:
        df = df[df["_year"] <= end]
    return df


# ============================================================================
# 5. Per-year missing analysis
# ============================================================================
def detect_kind(s: pd.Series) -> str:
    """numeric | flag (True/False) | categorical"""
    if pd.api.types.is_numeric_dtype(s):
        return "numeric"
    v = s.dropna().astype(str).str.strip().str.lower()
    if len(v) and v.isin(TRUE_SET | FALSE_SET).mean() > 0.9:
        return "flag"
    return "categorical"


def truthy_rate(s: pd.Series) -> float:
    """Share of 'True' among answered rows of a flag column."""
    v = s.dropna().astype(str).str.strip().str.lower()
    v = v[v.isin(TRUE_SET | FALSE_SET)]
    if v.empty:
        return np.nan
    return float(v.isin(TRUE_SET).mean())


def build_fields(single, groups, policies=None):
    """Flatten resolved fields, retaining policy columns as their own section."""
    fields = []
    keys = {"year", "name", "sector", "isin", "instrument", "id"}
    policy_cols = set((policies or {}).values())
    for canon, col in single.items():
        if canon not in keys and col:
            fields.append((canon, col))
    for canon, cols in groups.items():
        for col in cols:
            if col not in policy_cols:
                fields.append((f"{canon}::{col}", col))
    for name, col in (policies or {}).items():
        fields.append((f"policy::{name}", col))
    return fields


def per_year_missing(df, year_col, fields, id_col,
                     groups=None, policy_fields=None) -> pd.DataFrame:
    rows = []
    for year, g in df.groupby("_year", observed=True):
        row = {"year": int(year), "n_rows": int(len(g))}
        if id_col:
            row["n_companies"] = int(g[id_col].nunique())

        for label, col in fields:
            s = g[col]
            row[f"{label}__missing_pct"] = round(100.0 * s.isna().mean(), 2)
            row[f"{label}__missing_n"] = int(s.isna().sum())
            kind = detect_kind(s)
            if kind == "numeric":
                row[f"{label}__zeros_n"] = int((s == 0).sum())
            elif kind == "flag":
                row[f"{label}__share_true_pct"] = round(100.0 * truthy_rate(s), 2)

        for gname, cols in (groups or {}).items():
            if len(cols) > 1 and all(c in g.columns for c in cols):
                row[f"{gname}__group_all_missing_pct"] = round(
                    100.0 * g[cols].isna().all(axis=1).mean(), 2)

        if policy_fields:
            pmiss = [g[c].isna().mean() for _, c in policy_fields]
            row["policies__avg_missing_pct"] = round(100.0 * float(np.mean(pmiss)), 2)
            row["policies__n_cols_with_data"] = int(
                sum(1 for _, c in policy_fields if g[c].notna().any()))

        rows.append(row)
    return pd.DataFrame(rows).sort_values("year").reset_index(drop=True)


def wide_to_long(wide: pd.DataFrame) -> pd.DataFrame:
    pct_cols = [c for c in wide.columns if c.endswith("__missing_pct")]
    long = wide.melt(id_vars="year", value_vars=pct_cols,
                     var_name="field", value_name="missing_pct")
    long["field"] = long["field"].str.replace("__missing_pct", "", regex=False)
    return long.sort_values(["field", "year"]).reset_index(drop=True)


def field_summary(long: pd.DataFrame) -> pd.DataFrame:
    """Per field: average / first-year / last-year missing % and trend."""
    piv = long.pivot(index="field", columns="year", values="missing_pct")
    out = pd.DataFrame({
        "avg_missing_pct": piv.mean(axis=1).round(2),
        "first_year_missing_pct": piv.iloc[:, 0].round(2),
        "last_year_missing_pct": piv.iloc[:, -1].round(2),
    })
    out["change_pp"] = (out["last_year_missing_pct"]
                        - out["first_year_missing_pct"]).round(2)
    return out.sort_values("avg_missing_pct", ascending=False).reset_index()


def yoy_delta(long: pd.DataFrame) -> pd.DataFrame:
    piv = long.pivot(index="field", columns="year", values="missing_pct")
    return piv.diff(axis=1).round(2).reset_index()


# ============================================================================
# 6. Plots
# ============================================================================
def plot_heatmap(wide, labels, title, path):
    if not HAS_MPL or wide.empty or not labels:
        return
    pct_cols = [f"{l}__missing_pct" for l in labels if f"{l}__missing_pct" in wide.columns]
    if not pct_cols:
        return
    m = wide[pct_cols].copy()
    m.columns = [c.replace("__missing_pct", "") for c in pct_cols]
    m.index = wide["year"]
    fig, ax = plt.subplots(figsize=(max(8, 0.55 * len(m.columns)),
                                    max(4, 0.42 * len(m))))
    im = ax.imshow(m.values, aspect="auto", cmap="Reds", vmin=0, vmax=100)
    ax.set_xticks(range(len(m.columns)), m.columns, rotation=55, ha="right", fontsize=7)
    ax.set_yticks(range(len(m)), m.index)
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            v = m.values[i, j]
            ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=6,
                    color="white" if v > 60 else "black")
    ax.set_title(f"{title}\n% missing by year (0 = fully populated)")
    fig.colorbar(im, ax=ax, label="% missing")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    logging.info("Saved %s", path)


def plot_lines(long, title, path, max_lines=18):
    if not HAS_MPL or long.empty:
        return
    avg = long.groupby("field")["missing_pct"].mean()
    keep = avg.sort_values(ascending=False).head(max_lines).index
    sub = long[long["field"].isin(keep)]
    fig, ax = plt.subplots(figsize=(12, 7))
    for field, g in sub.groupby("field"):
        ax.plot(g["year"], g["missing_pct"], marker="o", label=field, alpha=0.85)
    ax.set_xlabel("Year"); ax.set_ylabel("% missing"); ax.set_ylim(0, 105)
    ax.set_title(title); ax.grid(alpha=0.3)
    ax.legend(bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=7)
    fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)
    logging.info("Saved %s", path)


def display_field(field: str) -> str:
    """Make internal canonical field labels readable in plots and reports."""
    return field.replace("::", " — ").replace("policy::", "Policy — ").replace("_", " ")


def plot_latest_gaps(long, title, path, max_fields=12):
    """Rank the latest-year data gaps; this is more actionable than a dense line chart."""
    if not HAS_MPL or long.empty:
        return
    latest_year = int(long["year"].max())
    latest = (long[long["year"] == latest_year]
              .sort_values("missing_pct", ascending=False).head(max_fields)
              .sort_values("missing_pct"))
    if latest.empty:
        return
    fig, ax = plt.subplots(figsize=(11, max(4.5, 0.48 * len(latest) + 1.5)))
    bars = ax.barh([display_field(x) for x in latest["field"]], latest["missing_pct"],
                   color="#d85a4a")
    ax.bar_label(bars, labels=[f"{x:.1f}%" for x in latest["missing_pct"]],
                 padding=4, fontsize=8)
    ax.set_xlim(0, 108)
    ax.set_xlabel("Missing values (%)")
    ax.set_title(f"{title}: largest gaps in {latest_year}")
    ax.grid(axis="x", alpha=0.2)
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    logging.info("Saved %s", path)


def plot_completeness_trend(source_longs, path):
    """Show median field completeness over time without over-weighting any field."""
    if not HAS_MPL or not source_longs:
        return
    fig, ax = plt.subplots(figsize=(10.5, 5.5))
    for label, long in source_longs.items():
        if long.empty:
            continue
        trend = (long.groupby("year", observed=True)["missing_pct"].median()
                 .rsub(100).sort_index())
        ax.plot(trend.index, trend.values, marker="o", linewidth=2.3,
                label=label.upper())
    ax.set_ylim(0, 100)
    ax.set_xlabel("Fiscal year")
    ax.set_ylabel("Median field completeness (%)")
    ax.set_title("Typical field completeness over time")
    ax.grid(alpha=0.25)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)
    logging.info("Saved %s", path)


def plot_overlap(overlap, path):
    if not HAS_MPL or overlap is None or overlap.empty:
        return
    fig, ax = plt.subplots(figsize=(10.5, 5.5))
    ax.plot(overlap["year"], overlap["pct_trucost_in_lseg"], marker="o",
            linewidth=2.3, label="Trucost records found in LSEG")
    ax.plot(overlap["year"], overlap["pct_lseg_in_trucost"], marker="o",
            linewidth=2.3, label="LSEG records found in Trucost")
    ax.set_ylim(0, 100)
    ax.set_xlabel("Fiscal year")
    ax.set_ylabel("ISIN-year overlap (%)")
    ax.set_title("Cross-source identifier coverage")
    ax.grid(alpha=0.25)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)
    logging.info("Saved %s", path)


# ============================================================================
# 7. HTML report
# ============================================================================
def source_snapshot(label, wide, long):
    """Small, stable set of source-level metrics for the report front page."""
    latest_year = int(wide["year"].max())
    latest = long[long["year"] == latest_year]
    latest_row = wide.loc[wide["year"] == latest_year].iloc[0]
    return {
        "source": label.upper(),
        "years": f"{int(wide['year'].min())}–{latest_year}",
        "latest_year": latest_year,
        "rows": int(latest_row["n_rows"]),
        "companies": int(latest_row.get("n_companies", 0)),
        "fields": int(latest["field"].nunique()),
        "median_completeness": float(100 - latest["missing_pct"].median()),
        "mean_completeness": float(100 - latest["missing_pct"].mean()),
    }


def priority_gaps(label, long, limit=10):
    latest_year = int(long["year"].max())
    summary = field_summary(long).set_index("field")
    latest = (long[long["year"] == latest_year]
              .set_index("field").join(summary[["change_pp"]], how="left")
              .sort_values("missing_pct", ascending=False).head(limit).reset_index())
    latest.insert(0, "Source", label.upper())
    latest["Field"] = latest["field"].map(display_field)
    latest["Availability"] = 100 - latest["missing_pct"]
    return latest.loc[:, ["Source", "Field", "missing_pct", "Availability", "change_pp"]]


def html_table(frame, percent_columns=()):
    view = frame.copy()
    for col in percent_columns:
        if col in view:
            view[col] = view[col].map(lambda x: "—" if pd.isna(x) else f"{x:.1f}%")
    return view.to_html(index=False, classes="report-table", border=0, escape=True)


def write_html_report(out, source_results, overlap, source_errors, lseg_path, trucost_path):
    """Write a standalone, print-friendly audit narrative beside the CSV outputs."""
    snapshots = [source_snapshot(label, wide, long)
                 for label, (wide, long) in source_results.items()]
    overview = pd.DataFrame(snapshots).rename(columns={
        "source": "Source", "years": "Years audited", "latest_year": "Latest year",
        "rows": "Rows in latest year", "companies": "Companies in latest year",
        "fields": "Fields assessed", "median_completeness": "Median completeness",
        "mean_completeness": "Mean completeness",
    })
    priorities = pd.concat([priority_gaps(label, long)
                            for label, (_, long) in source_results.items()],
                           ignore_index=True)
    priorities = priorities.sort_values("missing_pct", ascending=False).head(15)
    priorities = priorities.rename(columns={
        "missing_pct": "Missing", "change_pp": "Change since first year (pp)",
    })

    asset_items = []
    for name, caption in [
        ("overall_completeness_trend.png", "Median completeness by source and fiscal year."),
        ("lseg_latest_gaps.png", "Largest LSEG data gaps in the most recent year."),
        ("trucost_latest_gaps.png", "Largest Trucost data gaps in the most recent year."),
        ("lseg_missing_heatmap.png", "LSEG field-level missingness across time."),
        ("trucost_missing_heatmap.png", "Trucost field-level missingness across time."),
        ("lseg_policies_heatmap.png", "LSEG policy disclosure coverage across time."),
        ("coverage_overlap.png", "Cross-source ISIN-year overlap."),
    ]:
        if (out / name).exists():
            asset_items.append(
                f'<figure><img src="{escape(name)}" alt="{escape(caption)}">'
                f'<figcaption>{escape(caption)}</figcaption></figure>'
            )

    errors = "".join(f"<li><strong>{escape(label.upper())}:</strong> {escape(message)}</li>"
                     for label, message in source_errors.items())
    error_block = (f"<section class=\"warning\"><h2>Source warnings</h2><ul>{errors}</ul></section>"
                   if errors else "")
    overlap_block = ""
    if overlap is not None and not overlap.empty:
        overlap_view = overlap.tail(5).rename(columns={
            "trucost_companies": "Trucost companies", "lseg_companies": "LSEG companies",
            "matched_isin_year": "Matched ISIN-years", "pct_trucost_in_lseg": "Trucost in LSEG",
            "pct_lseg_in_trucost": "LSEG in Trucost",
        })
        overlap_block = "<h2>Cross-source match coverage</h2>" + html_table(
            overlap_view, ("Trucost in LSEG", "LSEG in Trucost"))

    cards = "".join(
        f'<article class="card"><p class="eyebrow">{escape(row["Source"])} · {row["Years audited"]}</p>'
        f'<p class="metric">{row["Median completeness"]:.1f}%</p>'
        f'<p>median completeness in {row["Latest year"]}</p>'
        f'<dl><div><dt>Rows</dt><dd>{row["Rows in latest year"]:,}</dd></div>'
        f'<div><dt>Companies</dt><dd>{row["Companies in latest year"]:,}</dd></div>'
        f'<div><dt>Fields</dt><dd>{row["Fields assessed"]:,}</dd></div></dl></article>'
        for row in overview.to_dict("records")
    )
    generated = datetime.now().astimezone().strftime("%d %B %Y, %H:%M %Z")
    html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>TRACE3 Missing-data Audit</title><style>
:root {{ --ink:#14212b; --muted:#5f6c76; --paper:#f5f7f8; --card:#fff; --accent:#146c7e; --warning:#9a4d20; --line:#d9e0e4; }}
* {{ box-sizing:border-box }} body {{ margin:0; background:var(--paper); color:var(--ink); font:15px/1.55 Arial, sans-serif }}
main {{ max-width:1260px; margin:auto; padding:38px 28px 64px }} header {{ padding:38px; background:linear-gradient(130deg,#102e3b,#146c7e); color:#fff; border-radius:16px }}
h1 {{ margin:0; font-size:clamp(28px,5vw,48px); line-height:1.1 }} h2 {{ margin:38px 0 12px; font-size:22px }} .sub {{ max-width:760px; color:#d9edf0; margin:12px 0 0 }}
.meta,.eyebrow {{ color:var(--muted); font-size:12px; letter-spacing:.06em; text-transform:uppercase }} header .meta {{ color:#b7d8de; margin-top:22px }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:16px; margin-top:18px }} .card {{ background:var(--card); padding:22px; border:1px solid var(--line); border-radius:12px; box-shadow:0 2px 10px #1b2f3a0a }}
.card .eyebrow {{ margin:0 }} .metric {{ font-size:36px; font-weight:700; color:var(--accent); margin:8px 0 -3px }} .card p:last-of-type {{ margin-top:0; color:var(--muted) }} dl {{ display:flex; gap:16px; margin:18px 0 0 }} dt {{ color:var(--muted); font-size:12px }} dd {{ margin:0; font-weight:700 }}
.report-table {{ border-collapse:collapse; width:100%; background:#fff; font-size:13px; overflow:hidden; border-radius:10px }} .report-table th {{ background:#e7f0f2; text-align:left; color:#24424b }} .report-table th,.report-table td {{ padding:9px 10px; border-bottom:1px solid var(--line) }} .report-table tr:last-child td {{ border-bottom:0 }}
.visuals {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(420px,1fr)); gap:18px }} figure {{ margin:0; background:#fff; padding:15px; border:1px solid var(--line); border-radius:12px }} figure img {{ display:block; width:100%; height:auto }} figcaption {{ color:var(--muted); font-size:13px; padding:8px 4px 0 }}
.note,.warning {{ margin-top:28px; padding:18px 20px; border-radius:10px; background:#e9f3f5; border-left:4px solid var(--accent) }} .warning {{ background:#fff3eb; border-color:var(--warning) }} .warning h2 {{ margin-top:0 }}
footer {{ color:var(--muted); margin-top:36px; font-size:12px }} @media print {{ body {{ background:#fff }} main {{ padding:0 }} header {{ border-radius:0 }} .card,figure {{ box-shadow:none }} }}
</style></head><body><main><header><h1>Missing-data audit</h1><p class="sub">A decision-ready review of field completeness, trends, policy disclosure coverage, and identifier overlap across the LSEG and Trucost extracts.</p><p class="meta">TRACE3 · generated {escape(generated)}</p></header>
<h2>Executive snapshot</h2><div class="cards">{cards}</div>
<section class="note"><strong>How to read this report.</strong> Completeness is 100% minus the share of blank or recognised missing values. Values reported as zero are retained and counted separately in the detailed CSVs; a zero is not treated as missing. “Change since first year” is expressed in percentage points, where a negative value indicates improved coverage.</section>
{error_block}<h2>Priority data gaps</h2><p>Fields with the highest missingness in each source’s most recent available year. Use this table to decide which variables need exclusion, imputation, or an alternative source.</p>{html_table(priorities, ("Missing", "Availability", "Change since first year (pp)"))}
<h2>Source coverage</h2>{html_table(overview, ("Median completeness", "Mean completeness"))}
{overlap_block}<h2>Visual evidence</h2><div class="visuals">{''.join(asset_items)}</div>
<h2>Method and scope</h2><p>The audit resolves columns by their documented aliases, normalises recognised text missing-value tokens, then calculates missingness for every available fiscal year. It evaluates every resolved field individually, policy fields separately, and ISIN-year overlap only where both extracts provide an ISIN column. Results reflect the supplied extracts rather than the full vendor universes.</p>
<footer>Inputs: {escape(str(lseg_path))}<br>Inputs: {escape(str(trucost_path))}<br>Detailed machine-readable outputs are stored alongside this report.</footer></main></body></html>'''
    report_path = out / "missing_data_report.html"
    report_path.write_text(html, encoding="utf-8")
    logging.info("Saved %s", report_path)
    return report_path


# ============================================================================
# 7. Cross-source ISIN+Year overlap
# ============================================================================
def coverage_overlap(t_df, t_isin, l_df, l_isin):
    if not t_isin or not l_isin:
        logging.warning("Overlap skipped: ISIN column missing in one source.")
        return None

    def norm(frame, col):
        s = frame[col].astype("string").str.strip().str.upper()
        return (frame.assign(_isin=s)
                     .dropna(subset=["_isin"])
                     .drop_duplicates(subset=["_isin", "_year"])
                     .loc[:, ["_isin", "_year"]])

    merged = norm(t_df, t_isin).merge(norm(l_df, l_isin),
                                      on=["_isin", "_year"],
                                      how="outer", indicator=True)
    rows = []
    for year, g in merged.groupby("_year", observed=True):
        n_t = int((g["_merge"] != "right_only").sum())
        n_l = int((g["_merge"] != "left_only").sum())
        n_b = int((g["_merge"] == "both").sum())
        rows.append({
            "year": int(year), "trucost_companies": n_t, "lseg_companies": n_l,
            "matched_isin_year": n_b,
            "pct_trucost_in_lseg": round(100 * n_b / n_t, 2) if n_t else np.nan,
            "pct_lseg_in_trucost": round(100 * n_b / n_l, 2) if n_l else np.nan,
        })
    return pd.DataFrame(rows).sort_values("year").reset_index(drop=True)


# ============================================================================
# 8. Orchestration
# ============================================================================
def analyse_source(label, df, year_col, id_col, fields, groups,
                   policy_fields, out, main_labels):
    wide = per_year_missing(df, year_col, fields, id_col,
                            groups=groups, policy_fields=policy_fields)
    long = wide_to_long(wide)

    wide.to_csv(out / f"{label}_missing_by_year_wide.csv", index=False)
    long.to_csv(out / f"{label}_missing_by_year_long.csv", index=False)
    field_summary(long).to_csv(out / f"{label}_field_summary.csv", index=False)
    yoy_delta(long).to_csv(out / f"{label}_missing_yoy_delta.csv", index=False)

    logging.info("\n===== %s: %% missing by year (main fields) =====\n%s",
                 label.upper(), wide.to_string(index=False))
    logging.info("\n===== %s: field summary (worst first) =====\n%s",
                 label.upper(), field_summary(long).to_string(index=False))

    latest = int(wide["year"].max())
    snap = (long[long["year"] == latest]
            .sort_values("missing_pct", ascending=False).head(15))
    logging.info("\n===== %s: worst-covered fields in %d =====\n%s",
                 label.upper(), latest, snap.to_string(index=False))

    plot_heatmap(wide, main_labels, f"{label} - missingness by year",
                 out / f"{label}_missing_heatmap.png")
    plot_lines(long, f"{label} - % missing by year",
               out / f"{label}_missing_lines.png")
    plot_latest_gaps(long, label.upper(), out / f"{label}_latest_gaps.png")
    return wide, long


def main():
    ap = argparse.ArgumentParser(description="LSEG/Trucost missing % by year")
    ap.add_argument("--start-year", type=int, default=YEAR_RANGE[0])
    ap.add_argument("--end-year", type=int, default=YEAR_RANGE[1])
    ap.add_argument("--out", default=OUTPUT_DIR)
    ap.add_argument("--lseg-path", type=Path, default=LSEG_RAW_PATH,
                    help="Path to the LSEG CSV (default: project data/raw location).")
    ap.add_argument("--trucost-path", type=Path, default=TRUCOST_RAW_PATH,
                    help="Path to the Trucost CSV or Stata extract.")
    ap.add_argument("--list-columns", action="store_true")
    ap.add_argument("--no-html-report", action="store_true",
                    help="Write CSVs and charts only; skip missing_data_report.html.")
    args = ap.parse_args()

    if args.start_year is not None and args.end_year is not None and args.start_year > args.end_year:
        ap.error("--start-year must be less than or equal to --end-year")

    out = Path(args.out).expanduser().resolve()
    lseg_path = args.lseg_path.expanduser().resolve()
    trucost_path = args.trucost_path.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-8s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(out / "missing_by_year.log",
                                                       mode="w")])

    if args.list_columns:
        for path, name in [(trucost_path, "TRUCOST"), (lseg_path, "LSEG")]:
            if path.exists():
                cols = list(read_header(path))
                logging.info("[%s] %d columns:\n  %s",
                             name, len(cols), "\n  ".join(map(str, cols)))
            else:
                logging.warning("[%s] not found: %s", name, path)
        return

    years = None
    if args.start_year is not None and args.end_year is not None:
        years = set(range(args.start_year, args.end_year + 1))

    # ---------------- LSEG ----------------
    l_wide = l_long = None
    t_wide = t_long = None
    lseg_df = trucost_df = None
    source_results = {}
    source_errors = {}
    if lseg_path.exists():
        single, groups, policies = resolve_lseg(lseg_path)
        lseg_df, l_year, l_id = load_lseg(lseg_path, single, groups, policies,
                                          requested_years=years)
        fields = build_fields(single, groups, policies)
        policy_fields = [(f"policy::{k}", v) for k, v in policies.items()]
        main_labels = ([c for c in single if c not in
                        ("year", "name", "sector", "isin", "instrument")]
                       + [f"{g}::{c}" for g, cols in groups.items() for c in cols])
        l_wide, l_long = analyse_source("lseg", lseg_df, l_year, l_id,
                                        fields, groups, policy_fields,
                                        out, main_labels)
        source_results["lseg"] = (l_wide, l_long)
        if policy_fields:
            p_long = l_long[l_long["field"].str.startswith("policy::")]
            p_long.to_csv(out / "lseg_policies_missing_long.csv", index=False)
            plot_heatmap(l_wide, [l for l, _ in policy_fields],
                         "LSEG policy columns - missingness by year",
                         out / "lseg_policies_heatmap.png")
        lseg_isin = single.get("isin")
    else:
        message = f"File not found: {lseg_path}"
        logging.warning("[lseg] %s", message)
        source_errors["lseg"] = message
        lseg_isin = None

    # ---------------- Trucost ----------------
    t_isin = None
    if trucost_path.exists():
        trucost_df, t_year, t_id, t_fields = load_trucost(trucost_path, requested_years=years)
        t_value_fields = [(k, c) for k, c in t_fields.items()
                          if k not in ("year", "name", "isin", "id")]
        t_wide, t_long = analyse_source("trucost", trucost_df, t_year, t_id,
                                        t_value_fields, None, None, out,
                                        [k for k, _ in t_value_fields])
        source_results["trucost"] = (t_wide, t_long)
        t_isin = t_fields.get("isin")
    else:
        message = f"File not found: {trucost_path}"
        logging.warning("[trucost] %s", message)
        source_errors["trucost"] = message

    # ---------------- combined & overlap ----------------
    if l_long is not None and t_long is not None:
        both = pd.concat([l_long.assign(source="lseg"),
                          t_long.assign(source="trucost")])
        plot_lines(both, "Missing data by year - LSEG vs Trucost",
                   out / "missing_by_year_lines.png", max_lines=24)

    if l_wide is not None and t_wide is not None:
        overlap = coverage_overlap(trucost_df, t_isin, lseg_df, lseg_isin)
        if overlap is not None:
            overlap.to_csv(out / "coverage_overlap_by_year.csv", index=False)
            plot_overlap(overlap, out / "coverage_overlap.png")
            logging.info("\n===== ISIN+Year coverage overlap =====\n%s",
                         overlap.to_string(index=False))

    else:
        overlap = None

    if source_results:
        plot_completeness_trend({label: long for label, (_, long) in source_results.items()},
                                out / "overall_completeness_trend.png")
        if not args.no_html_report:
            write_html_report(out, source_results, overlap, source_errors,
                              lseg_path, trucost_path)

    logging.info("Done. All outputs in: %s", out.resolve())


if __name__ == "__main__":
    main()

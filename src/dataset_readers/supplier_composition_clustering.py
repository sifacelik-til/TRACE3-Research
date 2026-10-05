"""Cluster companies by the industry composition of their FactSet suppliers.

FactSet's REVENUE_PCT is generally a relationship-revenue measure, not the
customer's audited procurement spend. It can therefore be used as a supply-chain
importance proxy, but it should not be described as actual spend unless a true
spend column is supplied separately.

Example:
    py src\supplier_composition_clustering.py --clusters 8
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans


LOGGER = logging.getLogger(__name__)
DEFAULT_FACTSET_DIR = Path("../../data") / "raw" / "FactSet"
DEFAULT_OUTPUT_DIR = Path("../../data") / "processed" / "supplier_composition"
UNCLASSIFIED = "Not Classified"


def read_factset_file(path: Path) -> pd.DataFrame:
    """Read a pipe-delimited FactSet file with common encoding fallbacks."""
    for encoding in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            frame = pd.read_csv(
                path,
                sep="|",
                quotechar='"',
                dtype=str,
                encoding=encoding,
                low_memory=False,
            )
            frame.columns = [column.strip().strip('"') for column in frame.columns]
            return frame
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not decode FactSet file: {path}")


def require_columns(frame: pd.DataFrame, columns: set[str], path: Path) -> None:
    missing = columns.difference(frame.columns)
    if missing:
        raise ValueError(f"{path} is missing required columns: {sorted(missing)}")


def load_inputs(factset_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    entity_path = factset_dir / "sym_entity_v1_full_12328" / "sym_entity.txt"
    sector_path = factset_dir / "sym_entity_v1_full_12328" / "sym_entity_sector.txt"
    relationship_path = (
        factset_dir / "ent_supply_chain_v1_full_3856" / "ent_scr_relationships.txt"
    )
    industry_path = factset_dir / "ref_hub_v2_full_3565" / "factset_industry_map.txt"

    for path in (entity_path, sector_path, relationship_path, industry_path):
        if not path.exists():
            raise FileNotFoundError(f"Missing required FactSet file: {path}")

    entities = read_factset_file(entity_path)
    sectors = read_factset_file(sector_path)
    relationships = read_factset_file(relationship_path)
    industries = read_factset_file(industry_path)

    require_columns(entities, {"FACTSET_ENTITY_ID", "ENTITY_PROPER_NAME"}, entity_path)
    require_columns(sectors, {"FACTSET_ENTITY_ID", "INDUSTRY_CODE"}, sector_path)
    require_columns(
        relationships,
        {
            "REL_TYPE",
            "SOURCE_FACTSET_ENTITY_ID",
            "TARGET_FACTSET_ENTITY_ID",
            "REVENUE_PCT",
        },
        relationship_path,
    )
    require_columns(
        industries,
        {"FACTSET_INDUSTRY_CODE", "FACTSET_INDUSTRY_DESC"},
        industry_path,
    )
    return entities, sectors, relationships, industries


def prepare_supplier_relationships(
    relationships: pd.DataFrame,
    sectors: pd.DataFrame,
    industries: pd.DataFrame,
    as_of: pd.Timestamp | None,
    exclude_unclassified: bool,
) -> pd.DataFrame:
    """Return one current row per customer-supplier pair with supplier metadata."""
    rel = relationships.copy()
    rel["REL_TYPE"] = rel["REL_TYPE"].fillna("").str.strip().str.upper()
    rel = rel[rel["REL_TYPE"].eq("SUPPLIER")].copy()
    rel = rel.rename(
        columns={
            "SOURCE_FACTSET_ENTITY_ID": "supplier_id",
            "TARGET_FACTSET_ENTITY_ID": "company_id",
            "REVENUE_PCT": "revenue_pct",
        }
    )
    rel["supplier_id"] = rel["supplier_id"].fillna("").str.strip().str.strip('"')
    rel["company_id"] = rel["company_id"].fillna("").str.strip().str.strip('"')
    rel = rel[(rel["supplier_id"] != "") & (rel["company_id"] != "")].copy()

    for column in ("START_DATE", "END_DATE"):
        if column not in rel.columns:
            rel[column] = pd.NaT
        rel[column] = pd.to_datetime(rel[column], errors="coerce")

    if as_of is not None:
        rel = rel[
            (rel["START_DATE"].isna() | rel["START_DATE"].le(as_of))
            & (rel["END_DATE"].isna() | rel["END_DATE"].ge(as_of))
        ].copy()

    rel["revenue_pct"] = pd.to_numeric(rel["revenue_pct"], errors="coerce")
    rel.loc[rel["revenue_pct"] <= 0, "revenue_pct"] = np.nan
    rel = rel.sort_values(
        ["company_id", "supplier_id", "START_DATE"],
        ascending=[True, True, False],
        na_position="last",
    ).drop_duplicates(["company_id", "supplier_id"], keep="first")

    supplier_sectors = (
        sectors[["FACTSET_ENTITY_ID", "INDUSTRY_CODE"]]
        .drop_duplicates("FACTSET_ENTITY_ID", keep="first")
        .rename(
            columns={
                "FACTSET_ENTITY_ID": "supplier_id",
                "INDUSTRY_CODE": "supplier_industry_code",
            }
        )
    )
    industry_lookup = (
        industries[["FACTSET_INDUSTRY_CODE", "FACTSET_INDUSTRY_DESC"]]
        .drop_duplicates("FACTSET_INDUSTRY_CODE", keep="first")
        .rename(
            columns={
                "FACTSET_INDUSTRY_CODE": "supplier_industry_code",
                "FACTSET_INDUSTRY_DESC": "supplier_industry",
            }
        )
    )
    rel = rel.merge(supplier_sectors, on="supplier_id", how="left")
    rel = rel.merge(industry_lookup, on="supplier_industry_code", how="left")
    rel["supplier_industry"] = rel["supplier_industry"].fillna(UNCLASSIFIED)
    rel["supplier_industry_code"] = rel["supplier_industry_code"].fillna("9999")

    if exclude_unclassified:
        rel = rel[rel["supplier_industry"].ne(UNCLASSIFIED)].copy()
    return rel


def build_composition(
    relationships: pd.DataFrame,
    entities: pd.DataFrame,
    weighting: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build long-form company-by-supplier-industry composition shares."""
    rel = relationships.copy()
    rel["has_revenue_weight"] = rel["revenue_pct"].notna()

    company_stats = rel.groupby("company_id").agg(
        supplier_count=("supplier_id", "nunique"),
        suppliers_with_revenue_pct=("has_revenue_weight", "sum"),
    )
    company_stats["revenue_weight_coverage"] = (
        company_stats["suppliers_with_revenue_pct"] / company_stats["supplier_count"]
    )

    if weighting == "equal":
        rel["weight"] = 1.0
        company_stats["weight_basis"] = "equal supplier count"
    else:
        companies_with_weights = set(
            rel.loc[rel["has_revenue_weight"], "company_id"].unique()
        )
        rel["weight"] = rel["revenue_pct"]
        no_weight_mask = ~rel["company_id"].isin(companies_with_weights)
        rel.loc[no_weight_mask, "weight"] = 1.0
        company_stats["weight_basis"] = np.where(
            company_stats.index.isin(companies_with_weights),
            "FactSet REVENUE_PCT proxy",
            "equal fallback: no REVENUE_PCT available",
        )
        rel = rel[rel["weight"].notna()].copy()

    profile = (
        rel.groupby(
            [
                "company_id",
                "supplier_industry_code",
                "supplier_industry",
            ],
            as_index=False,
        )
        .agg(
            industry_weight=("weight", "sum"),
            suppliers_in_industry=("supplier_id", "nunique"),
        )
    )
    profile["composition_share"] = profile["industry_weight"] / profile.groupby(
        "company_id"
    )["industry_weight"].transform("sum")
    profile["composition_pct"] = 100 * profile["composition_share"]

    names = (
        entities[["FACTSET_ENTITY_ID", "ENTITY_PROPER_NAME"]]
        .drop_duplicates("FACTSET_ENTITY_ID", keep="first")
        .rename(
            columns={
                "FACTSET_ENTITY_ID": "company_id",
                "ENTITY_PROPER_NAME": "company_name",
            }
        )
    )
    profile = profile.merge(names, on="company_id", how="left")
    company_stats = company_stats.reset_index().merge(names, on="company_id", how="left")
    return profile, company_stats


def top_composition_text(group: pd.DataFrame, limit: int = 3) -> str:
    top = group.nlargest(limit, "composition_share")
    return "; ".join(
        f"{row.supplier_industry}: {row.composition_pct:.1f}%"
        for row in top.itertuples()
    )


def cluster_compositions(
    profile: pd.DataFrame,
    company_stats: pd.DataFrame,
    n_clusters: int,
    min_suppliers: int,
    random_state: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Cluster eligible companies using Hellinger-transformed composition vectors."""
    eligible_ids = set(
        company_stats.loc[
            company_stats["supplier_count"].ge(min_suppliers), "company_id"
        ]
    )
    eligible = profile[profile["company_id"].isin(eligible_ids)].copy()
    wide = eligible.pivot_table(
        index="company_id",
        columns="supplier_industry",
        values="composition_share",
        aggfunc="sum",
        fill_value=0.0,
    )
    if wide.empty:
        raise ValueError(
            f"No companies have at least {min_suppliers} classified suppliers."
        )
    if len(wide) < n_clusters:
        LOGGER.warning(
            "Requested %d clusters but only %d companies are eligible; using %d clusters.",
            n_clusters,
            len(wide),
            len(wide),
        )
        n_clusters = len(wide)

    transformed = np.sqrt(wide.to_numpy())
    model = KMeans(n_clusters=n_clusters, random_state=random_state, n_init=20)
    raw_labels = model.fit_predict(transformed)

    assignments = pd.DataFrame(
        {"company_id": wide.index, "raw_cluster": raw_labels}
    )
    assignments = assignments.merge(company_stats, on="company_id", how="left")
    assignments["top_supplier_composition"] = assignments["company_id"].map(
        profile.groupby("company_id").apply(
            top_composition_text, include_groups=False
        )
    )

    centroid_rows = []
    for raw_cluster, member_ids in assignments.groupby("raw_cluster")["company_id"]:
        centroid = wide.loc[member_ids].mean(axis=0).sort_values(ascending=False)
        for industry, share in centroid.items():
            centroid_rows.append(
                {
                    "raw_cluster": raw_cluster,
                    "supplier_industry": industry,
                    "mean_composition_share": share,
                    "mean_composition_pct": 100 * share,
                }
            )
    centroids = pd.DataFrame(centroid_rows)
    top_industries = (
        centroids.sort_values(
            ["raw_cluster", "mean_composition_share"],
            ascending=[True, False],
        )
        .groupby("raw_cluster")
        .head(3)
        .groupby("raw_cluster")
        .apply(
            lambda group: " + ".join(group["supplier_industry"]),
            include_groups=False,
        )
        .rename("cluster_profile")
    )

    ordered_raw_clusters = sorted(
        top_industries.index,
        key=lambda cluster: (top_industries.loc[cluster].casefold(), cluster),
    )
    cluster_map = {
        raw_cluster: cluster_number
        for cluster_number, raw_cluster in enumerate(ordered_raw_clusters, start=1)
    }
    assignments["cluster"] = assignments["raw_cluster"].map(cluster_map)
    assignments = assignments.merge(
        top_industries, left_on="raw_cluster", right_index=True, how="left"
    ).drop(columns="raw_cluster")
    assignments = assignments.sort_values(["cluster", "company_name", "company_id"])

    centroids["cluster"] = centroids["raw_cluster"].map(cluster_map)
    centroids = centroids.merge(
        top_industries, left_on="raw_cluster", right_index=True, how="left"
    ).drop(columns="raw_cluster")
    centroids = centroids.sort_values(
        ["cluster", "mean_composition_share"], ascending=[True, False]
    )

    wide_output = wide.reset_index()
    wide_output.columns.name = None
    return assignments, centroids, wide_output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cluster companies by the weighted industry composition of suppliers."
    )
    parser.add_argument("--factset-dir", type=Path, default=DEFAULT_FACTSET_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--clusters", type=int, default=8)
    parser.add_argument("--min-suppliers", type=int, default=3)
    parser.add_argument(
        "--weighting",
        choices=("revenue_pct", "equal"),
        default="revenue_pct",
        help="Use FactSet REVENUE_PCT where available, or count every supplier equally.",
    )
    parser.add_argument(
        "--as-of",
        type=pd.Timestamp,
        default=None,
        help="Optional relationship snapshot date, for example 2026-06-30.",
    )
    parser.add_argument("--exclude-unclassified", action="store_true")
    parser.add_argument("--random-state", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.clusters < 1:
        raise ValueError("--clusters must be at least 1")
    if args.min_suppliers < 1:
        raise ValueError("--min-suppliers must be at least 1")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    entities, sectors, relationships, industries = load_inputs(args.factset_dir)
    supplier_rel = prepare_supplier_relationships(
        relationships,
        sectors,
        industries,
        args.as_of,
        args.exclude_unclassified,
    )
    if supplier_rel.empty:
        raise ValueError("No supplier relationships remain after filtering.")

    profile, company_stats = build_composition(
        supplier_rel, entities, args.weighting
    )
    assignments, centroids, wide = cluster_compositions(
        profile,
        company_stats,
        args.clusters,
        args.min_suppliers,
        args.random_state,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    profile.sort_values(
        ["company_id", "composition_share"], ascending=[True, False]
    ).to_csv(args.output_dir / "company_supplier_composition_long.csv", index=False)
    wide.to_csv(args.output_dir / "company_supplier_composition_wide.csv", index=False)
    assignments.to_csv(args.output_dir / "company_supplier_clusters.csv", index=False)
    centroids.to_csv(args.output_dir / "supplier_cluster_profiles.csv", index=False)

    LOGGER.info(
        "Clustered %d companies into %d supplier-composition groups.",
        len(assignments),
        assignments["cluster"].nunique(),
    )
    LOGGER.info("Outputs written to %s", args.output_dir)
    if args.weighting == "revenue_pct":
        LOGGER.warning(
            "REVENUE_PCT is a relationship-revenue proxy, not confirmed procurement spend."
        )


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

from data_engine.extract_cdp_org_answers_2014_2024 import (
    DEFAULT_CDP_ROOT,
    DEFAULT_OUT_DIR,
    extract_from_2024_parquet,
    extract_from_legacy_xlsx,
    parse_year_file,
    slugify,
)


LOGGER = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

FACTSET_RAW_ROOT = Path(__file__).resolve().parent.parent / "data" / "raw" / "FactSet"


def _read_pipe(path: Path, usecols: List[str]) -> pd.DataFrame:
    try:
        return pd.read_csv(path, sep="|", dtype=str, usecols=usecols, low_memory=False, encoding="utf-8")
    except UnicodeDecodeError:
        return pd.read_csv(path, sep="|", dtype=str, usecols=usecols, low_memory=False, encoding="latin-1")


def resolve_org_name_from_isin(isin: str, factset_root: Path = FACTSET_RAW_ROOT) -> str:
    isin_clean = str(isin).strip().upper()
    if not isin_clean:
        raise ValueError("ISIN is empty")

    sym_isin = _read_pipe(
        factset_root / "sym_isin_v1_full_11256" / "sym_isin.txt",
        ["FSYM_ID", "ISIN"],
    )
    sym_xc = _read_pipe(
        factset_root / "sym_xc_isin_v1_full_12672" / "sym_xc_isin.txt",
        ["FSYM_ID", "ISIN"],
    )
    sec_entity = _read_pipe(
        factset_root / "ent_supply_chain_hub_v1_full_3858" / "ent_scr_sec_entity.txt",
        ["FSYM_ID", "FACTSET_ENTITY_ID"],
    )
    entity = _read_pipe(
        factset_root / "sym_entity_v1_full_12328" / "sym_entity.txt",
        ["FACTSET_ENTITY_ID", "ENTITY_PROPER_NAME"],
    )

    isin_map = pd.concat([sym_isin, sym_xc], ignore_index=True).drop_duplicates()
    isin_map["ISIN"] = isin_map["ISIN"].fillna("").astype(str).str.strip().str.upper()
    isin_map["FSYM_ID"] = isin_map["FSYM_ID"].fillna("").astype(str).str.strip()
    sec_entity["FSYM_ID"] = sec_entity["FSYM_ID"].fillna("").astype(str).str.strip()
    sec_entity["FACTSET_ENTITY_ID"] = sec_entity["FACTSET_ENTITY_ID"].fillna("").astype(str).str.strip()
    entity["FACTSET_ENTITY_ID"] = entity["FACTSET_ENTITY_ID"].fillna("").astype(str).str.strip()
    entity["ENTITY_PROPER_NAME"] = entity["ENTITY_PROPER_NAME"].fillna("").astype(str).str.strip()

    merged = isin_map.merge(sec_entity, on="FSYM_ID", how="left").merge(entity, on="FACTSET_ENTITY_ID", how="left")
    hit = merged[merged["ISIN"] == isin_clean]
    if hit.empty:
        raise ValueError(f"No organization found for ISIN: {isin_clean}")

    names = hit["ENTITY_PROPER_NAME"].dropna().astype(str).str.strip()
    names = names[names != ""]
    if names.empty:
        raise ValueError(f"No entity name found for ISIN: {isin_clean}")
    return names.iloc[0]


def build_theme_analysis(df_long: pd.DataFrame) -> pd.DataFrame:
    if df_long.empty:
        return pd.DataFrame(columns=["primary_theme", "answer_count", "unique_questions", "avg_answer_length", "sample_answers"])

    tmp = df_long.copy()
    tmp["answer_str"] = tmp["answer"].astype(str)
    tmp["answer_len"] = tmp["answer_str"].str.len()
    tmp["primary_theme"] = tmp["primary_theme"].fillna("other")

    grouped = (
        tmp.groupby("primary_theme", dropna=False)
        .agg(
            answer_count=("answer_str", "count"),
            unique_questions=("question_key", "nunique"),
            avg_answer_length=("answer_len", "mean"),
        )
        .reset_index()
    )

    samples = (
        tmp.groupby("primary_theme", dropna=False)["answer_str"]
        .apply(lambda s: " || ".join(list(dict.fromkeys([v for v in s if v and v.lower() != "nan"]))[:3]))
        .reset_index(name="sample_answers")
    )

    out = grouped.merge(samples, on="primary_theme", how="left")
    out["avg_answer_length"] = out["avg_answer_length"].round(1)
    return out.sort_values(["answer_count", "primary_theme"], ascending=[False, True])


def extract_for_year(org_name: str, year: int, cdp_root: Path) -> Tuple[pd.DataFrame, List[str], Path]:
    year_dir = cdp_root / str(year)
    file_path = parse_year_file(year_dir)
    if file_path is None:
        raise FileNotFoundError(f"No supported CDP file found for year {year} in {year_dir}")

    if file_path.suffix.lower() == ".parquet":
        records, matched_orgs = extract_from_2024_parquet(year, file_path, org_name)
    else:
        records, matched_orgs = extract_from_legacy_xlsx(year, file_path, org_name)

    if not records:
        return pd.DataFrame(), matched_orgs, file_path

    df = pd.DataFrame(records).sort_values(["primary_theme", "question_key", "question_code"], na_position="last")
    return df, matched_orgs, file_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract one-year CDP answers by org name or ISIN and analyze by theme.")
    parser.add_argument("--org-name", help="Organization name")
    parser.add_argument("--isin", help="ISIN to resolve organization name")
    parser.add_argument("--year", type=int, required=True, help="CDP year to extract")
    parser.add_argument("--cdp-root", default=str(DEFAULT_CDP_ROOT), help="Root folder for CDP yearly data")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory")
    parser.add_argument("--factset-root", default=str(FACTSET_RAW_ROOT), help="FactSet raw folder for ISIN lookup")
    args = parser.parse_args()

    if not args.org_name and not args.isin:
        parser.error("Provide either --org-name or --isin")

    cdp_root = Path(args.cdp_root)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if not cdp_root.exists():
        raise SystemExit(f"CDP root path not found: {cdp_root}")

    org_name: Optional[str] = args.org_name
    if not org_name:
        org_name = resolve_org_name_from_isin(args.isin, Path(args.factset_root))
        LOGGER.info("Resolved ISIN %s to org name: %s", args.isin, org_name)

    df_long, matched_orgs, source_file = extract_for_year(org_name, args.year, cdp_root)
    if df_long.empty:
        LOGGER.warning("No answers found for '%s' in year %s (file: %s)", org_name, args.year, source_file)
        return

    theme_analysis = build_theme_analysis(df_long)
    slug = slugify(org_name)

    answers_out = out_dir / f"cdp_org_answers_{slug}_{args.year}_thematic_answers.csv"
    analysis_out = out_dir / f"cdp_org_answers_{slug}_{args.year}_theme_analysis.csv"
    orgs_out = out_dir / f"cdp_org_answers_{slug}_{args.year}_matched_orgs.csv"

    df_long.to_csv(answers_out, index=False)
    theme_analysis.to_csv(analysis_out, index=False)
    pd.DataFrame({"year": [args.year], "matched_organizations": [" || ".join(matched_orgs)]}).to_csv(orgs_out, index=False)

    LOGGER.info("Source file: %s", source_file)
    LOGGER.info("Wrote answers: %s (rows=%d)", answers_out, len(df_long))
    LOGGER.info("Wrote theme analysis: %s (rows=%d)", analysis_out, len(theme_analysis))
    LOGGER.info("Wrote matched organizations: %s", orgs_out)


if __name__ == "__main__":
    main()

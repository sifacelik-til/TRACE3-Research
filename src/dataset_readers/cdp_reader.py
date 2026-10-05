#!/usr/bin/env python3
"""Read organization-level CDP answers from ``data/raw/CDP``.

The raw CDP directory contains answer datasets, not completed response PDFs:

* 2010--2023: public Excel workbooks;
* 2024--2025: Climate Change ``responses`` Parquet extracts.

This module is the stable entry point for extracting an organization's answers.
Its format-specific parsing is shared with
``extract_cdp_org_answers_2014_2024`` so both paths read the same fields.
"""
from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

try:  # The organization-answer extractor is in a separate package.
    from .extract_cdp_org_answers_2014_2024 import (
        DEFAULT_CDP_ROOT,
        extract_from_2024_parquet,
        extract_from_legacy_xlsx,
        parse_year_file,
        resolve_org_name_from_factset_id,
    )
except ImportError:
    from src.cdp_extraction.extract_cdp_org_answers_2014_2024 import (
        DEFAULT_CDP_ROOT,
        extract_from_2024_parquet,
        extract_from_legacy_xlsx,
        parse_year_file,
        resolve_org_name_from_factset_id,
    )

try:
    from .cdp_theme_taxonomy import THEME_PATTERNS
except ImportError:
    from src.dataset_readers.cdp_theme_taxonomy import THEME_PATTERNS


LOGGER = logging.getLogger(__name__)

# These are the questionnaire's top-level Climate Change modules.  They are a
# stable parent category even where question wording or response options vary
# between years.
QUESTION_CATEGORY_RULES = (
    (r"^C0", "Organization profile"),
    (r"^C1", "Governance"),
    (r"^C2", "Risks and opportunities"),
    (r"^C3", "Business strategy"),
    (r"^C4", "Targets and performance"),
    (r"^C5", "Emissions methodology"),
    (r"^C6", "Emissions data"),
    (r"^C7", "Emissions breakdown"),
    (r"^C8", "Energy"),
    (r"^C9", "Additional metrics"),
    (r"^C10", "Verification"),
    (r"^C11", "Carbon pricing"),
    (r"^C12", "Engagement"),
    (r"^C13", "Land management"),
    (r"^C14", "Portfolio impact"),
    (r"^C15", "Biodiversity"),
    (r"^C16", "Signoff"),
)
QUESTION_RE = re.compile(
    r"(?im)^\s*((?:CC|C)(?:-[A-Z]{1,8})?\s*\d+(?:\.\d+)?[a-z]?)"
    r"\s*(?:[:\-\u2013\u2014]\s*)?(.*)$"
)


def normalize_for_match(value: object) -> str:
    text = str(value or "").lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def normalize_question_code(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "").upper())


def extract_response_options(text: str) -> List[str]:
    """Extract declared choices from a questionnaire question block.

    CDP's wording has varied ("Select from", "Response options", bullets),
    so this is deliberately conservative: it returns no choices instead of
    inventing a category from prose.
    """
    match = re.search(
        r"(?:select\s+from|response\s+options?|options?)\s*:?\s*(.+?)"
        r"(?=\[?(?:text|numerical)\s+field|add\s+row|$)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return []
    options = re.split(r"[\u2022\u25cf\n;]+", match.group(1))
    cleaned = []
    for option in options:
        option = re.sub(r"^\s*[-\u2013\u2014]\s*", "", option).strip()
        option = re.sub(r"\s+", " ", option)
        if 2 < len(option) < 250:
            cleaned.append(option)
    return list(dict.fromkeys(cleaned))


def iter_questionnaire_files(questionnaire_dir: Path, year: int) -> Iterable[Path]:
    """Yield full corporate questionnaire PDFs for a year, excluding SME PDFs."""
    candidates = sorted(questionnaire_dir.glob(f"{year}*.pdf"))
    return (path for path in candidates if "sme" not in path.name.lower())


def load_questionnaire_options(questionnaire_dir: Path, year: int) -> Dict[str, List[str]]:
    """Read official questionnaire options keyed by CDP question code.

    The PDF library is imported only here so Excel/Parquet answer reading still
    works in environments that do not need questionnaire enrichment.
    """
    files = list(iter_questionnaire_files(questionnaire_dir, year))
    if not files:
        return {}
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "Questionnaire categorization requires pypdf; install requirements.txt."
        ) from exc

    options_by_code: Dict[str, List[str]] = {}
    for path in files:
        text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
        matches = list(QUESTION_RE.finditer(text))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            options = extract_response_options(text[match.start():end])
            if options:
                options_by_code.setdefault(
                    normalize_question_code(match.group(1)), options
                )
    return options_by_code


def parent_question_category(question_code: object) -> str:
    code = normalize_question_code(question_code)
    code = re.sub(r"^CC(?=\d)", "C", code)
    code = re.sub(r"^C-[A-Z]{1,8}(?=\d)", "C", code)
    for pattern, label in QUESTION_CATEGORY_RULES:
        if re.match(pattern, code, flags=re.IGNORECASE):
            return label
    return "Other / unmatched"


def matched_options(answer: object, options: List[str]) -> List[str]:
    answer_norm = normalize_for_match(answer)
    if not answer_norm:
        return []
    return [
        option for option in options
        if normalize_for_match(option) == answer_norm
    ]


def detail_categories(*texts: object) -> List[str]:
    """Apply the project taxonomy to answers and declared response options."""
    haystack = " ".join(normalize_for_match(text) for text in texts)
    categories = []
    for label, patterns in THEME_PATTERNS:
        if any(re.search(pattern, haystack, flags=re.IGNORECASE) for pattern in patterns):
            categories.append(label)
    return list(dict.fromkeys(categories))


def categorize_answers(
    answers: pd.DataFrame,
    questionnaire_dir: Path,
    use_questionnaire_guides: bool = True,
) -> pd.DataFrame:
    """Attach parent, detailed, and official-option categories to every answer.

    ``question_category`` is always derived from the CDP question code.
    ``detailed_categories`` refines that category from the raw answer and,
    where available, the questionnaire's declared response options. Exact
    option matches are emitted separately and are never inferred.
    """
    if answers.empty:
        return answers.copy()

    categorized = answers.copy()
    categorized["question_category"] = categorized["question_code"].map(
        parent_question_category
    )
    categorized["category_source"] = "question_code"
    categorized["questionnaire_response_options"] = ""
    categorized["matched_questionnaire_options"] = ""

    options_by_year: Dict[int, Dict[str, List[str]]] = {}
    if use_questionnaire_guides:
        for year in sorted(categorized["year"].dropna().astype(int).unique()):
            try:
                options_by_year[year] = load_questionnaire_options(
                    questionnaire_dir, year
                )
            except RuntimeError as exc:
                LOGGER.warning("%s Falling back to question-code categories.", exc)
                options_by_year[year] = {}

    detailed = []
    option_values = []
    matched_values = []
    for row in categorized.itertuples(index=False):
        options = options_by_year.get(int(row.year), {}).get(
            normalize_question_code(row.question_code), []
        )
        exact_options = matched_options(row.answer, options)
        inherited = [
            tag.strip() for tag in str(getattr(row, "theme_tags", "")).split("|")
            if tag.strip()
        ]
        categories = list(dict.fromkeys(
            inherited + detail_categories(row.answer, " ".join(options))
        ))
        detailed.append(" | ".join(categories))
        option_values.append(" | ".join(options))
        matched_values.append(" | ".join(exact_options))

    categorized["detailed_categories"] = detailed
    categorized["questionnaire_response_options"] = option_values
    categorized["matched_questionnaire_options"] = matched_values
    categorized.loc[
        categorized["questionnaire_response_options"].ne(""), "category_source"
    ] = "question_code + questionnaire"
    return categorized


def read_year_answers(
    year: int, org_name: str, cdp_root: Path = DEFAULT_CDP_ROOT
) -> Tuple[List[Dict[str, object]], List[str], Optional[Path]]:
    """Read one organization's non-empty answers for one reporting year.

    In Parquet data, ``content_full`` is the answer field. In legacy
    workbooks, answers are non-metadata fields in matched question sheets.
    ``N/A`` and ``Not applicable`` remain valid selected CDP answers.
    """
    source_file = parse_year_file(cdp_root / str(year))
    if source_file is None:
        return [], [], None

    if source_file.suffix.lower() == ".parquet":
        records, matched_orgs = extract_from_2024_parquet(
            year, source_file, org_name
        )
    else:
        records, matched_orgs = extract_from_legacy_xlsx(
            year, source_file, org_name
        )
    return records, matched_orgs, source_file


def read_answers(
    org_name: str,
    start_year: int = 2010,
    end_year: int = 2025,
    cdp_root: Path = DEFAULT_CDP_ROOT,
    questionnaire_dir: Optional[Path] = None,
    use_questionnaire_guides: bool = True,
) -> Tuple[pd.DataFrame, Dict[int, List[str]], Dict[int, Path]]:
    """Read raw CDP answers across an inclusive year range."""
    if start_year > end_year:
        raise ValueError("start_year must be less than or equal to end_year")

    all_records: List[Dict[str, object]] = []
    matched_by_year: Dict[int, List[str]] = {}
    source_by_year: Dict[int, Path] = {}
    for year in range(start_year, end_year + 1):
        records, matched_orgs, source_file = read_year_answers(
            year, org_name, cdp_root
        )
        if source_file is None:
            LOGGER.warning("No supported CDP answer file for %s", year)
            continue
        source_by_year[year] = source_file
        matched_by_year[year] = matched_orgs
        all_records.extend(records)
        LOGGER.info(
            "%s: source=%s, matched organizations=%d, answers=%d",
            year, source_file.name, len(matched_orgs), len(records),
        )

    questionnaire_dir = questionnaire_dir or cdp_root / "CDP Questionnaires"
    answers = categorize_answers(
        pd.DataFrame(all_records), questionnaire_dir, use_questionnaire_guides
    )
    return answers, matched_by_year, source_by_year


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read organization-level CDP answers from data/raw/CDP."
    )
    parser.add_argument("--org-name", help="CDP organization name to match")
    parser.add_argument("--factset-id", help="Resolve this FactSet ID to an organization name")
    parser.add_argument("--cdp-root", type=Path, default=DEFAULT_CDP_ROOT)
    parser.add_argument("--start-year", type=int, default=2010)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--out", type=Path, help="Optional CSV output path")
    parser.add_argument(
        "--questionnaire-dir",
        type=Path,
        help="Directory containing annual CDP questionnaire PDFs",
    )
    parser.add_argument(
        "--no-questionnaire-guides",
        action="store_true",
        help="Use question-code categories only; do not parse questionnaire PDFs",
    )
    args = parser.parse_args()

    if not args.org_name and not args.factset_id:
        parser.error("provide --org-name or --factset-id")
    if args.org_name and args.factset_id:
        parser.error("provide only one of --org-name and --factset-id")
    if not args.cdp_root.exists():
        parser.error(f"CDP root not found: {args.cdp_root}")

    org_name = args.org_name or resolve_org_name_from_factset_id(args.factset_id)
    answers, _, _ = read_answers(
        org_name,
        args.start_year,
        args.end_year,
        args.cdp_root,
        args.questionnaire_dir,
        not args.no_questionnaire_guides,
    )
    if answers.empty:
        LOGGER.warning("No CDP answers found for %r", org_name)
        return

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        answers.to_csv(args.out, index=False, encoding="utf-8-sig")
        LOGGER.info("Wrote %d answers to %s", len(answers), args.out)
    else:
        print(answers.to_csv(index=False))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    main()

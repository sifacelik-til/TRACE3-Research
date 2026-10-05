"""Replace compact CDP fields with lossless, question-specific answer columns."""

import csv
import gzip
import hashlib
import itertools
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


CDP_METADATA = {"cdp_account_number", "cdp_org_name", "cdp_match_method",
                "cdp_match_score"}
DROP_COLUMNS = {"cdp_c6_3_start_date", "cdp_c6_3_end_date", "cdp_c6_3_comment_c5775702"}
KEEP_COLUMNS = """
cdp_c4_1_you_emissions_target_was_active_report_year
cdp_c4_1a_pct_achieved_emissions
cdp_c4_1a_pct_target_achieved
cdp_q7_53_1_greenhouse_gases_covered_target
cdp_q7_53_1_s3_categories
cdp_c4_1a_target_reference_number
cdp_q7_53_1_scopes
cdp_c4_1b_target_reference_number
cdp_c4_1a_target_year_6ad93f0d
cdp_c4_1a_base_year
cdp_c4_1a_year_target_was_set
cdp_c4_1a_target_coverage
cdp_c4_1b_base_year_efc7582e
cdp_c4_1b_target_year_96a7a722
cdp_q7_53_1_base_year_total_s3_emissions_covered_target_tco2e
cdp_q7_53_1_total_base_year_emissions_covered_target_all_selected_scopes_tco2e
cdp_q7_53_1_total_emissions_report_year_covered_target_all_selected_scopes_tco2e
cdp_q7_53_1_sbt_target
cdp_q7_53_1_targeted_reduction_base_year_pct
cdp_q7_53_1_end_date_target
""".split()


def short_name(code, header):
    label = header.split(" - ")[-1]
    label = re.sub(r"^(?:col\d+_|(?:CC?|Q)\d[\w.]*[ _]*(?:C\d+[ _]*)?)", "", label,
                   flags=re.I).lower()
    for pattern, replacement in (
        (r"scope\s+(\d)", r"s\1"), (r"category\s+(\d+)", r"cat\1"),
        (r"metric (?:tonnes|tons) co2e", "tco2e"),
        (r"reporting year", "report_year"), (r"base year", "base_year"),
        (r"verification[/ ]*(?:or )?assurance", "verification"),
        (r"science.based", "sbt"), (r"organization[’']?s?", "org"),
        (r"percentage|%", " pct "),
    ):
        label = re.sub(pattern, replacement, label)
    words = re.findall(r"[a-z0-9]+", label)
    stop = set("the a an of for in on at by to and or your this please provide details is are do does have has which that with from as were what how any".split())
    slug = "_".join(w for w in words if w not in stop) or "answer"
    prefix = "cdp_" + re.sub(r"\W+", "_", code.lower()) + "_"
    if len(prefix + slug) > 80:
        slug = slug[:80 - len(prefix) - 9].rstrip("_") + "_" + hashlib.sha1(header.encode()).hexdigest()[:8]
    return prefix + slug


def expand_panel(panel_path: Path, long_path: Path):
    """Atomically refresh a year-sorted panel; preserve every original answer cell.

    Single answers are raw strings. Repeated answers are JSON string arrays.
    Columns with more than 65% missing values are removed after expansion.
    """
    csv.field_size_limit(100_000_000)
    with gzip.open(panel_path, "rt", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        base_columns = [c for c in reader.fieldnames
                        if not c.startswith("cdp_") or c in CDP_METADATA]
        rows = [{c: row[c] for c in base_columns} for row in reader]
    years = [int(row["year"]) for row in rows]
    if years != sorted(years):
        raise ValueError("Panel must be sorted by year; no file was changed")
    keys = {(int(r["year"]), r["cdp_account_number"]) for r in rows}
    counts = Counter()
    question_counts = Counter()
    previous_year = -1
    with gzip.open(long_path, "rt", encoding="utf-8", newline="") as stream:
        for r in csv.DictReader(stream):
            year = int(r["year"])
            if year < previous_year or (year, r["cdp_account_number"]) not in keys:
                raise ValueError("Unsorted or unmatched answer records; no file was changed")
            previous_year = year
            counts[(r["family"], r["question_code"], r["column_header"])] += 1
            question_counts[(year, r["family"], r["question_code"])] += 1
    names = {}
    used = set(base_columns)
    for key in sorted(counts):
        name = short_name(key[1], key[2])
        if name in used:
            name = name[:71] + "_" + hashlib.sha1(repr(key).encode()).hexdigest()[:8]
        if name in used:
            raise ValueError(f"Column collision: {key}")
        used.add(name)
        names[key] = name
    pending = panel_path.with_name(panel_path.name + ".partial")
    written = 0
    panel_years = {year: list(group) for year, group in
                   itertools.groupby(rows, lambda r: int(r["year"]))}
    with gzip.open(pending, "wt", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=base_columns + list(names.values()))
        writer.writeheader()
        with gzip.open(long_path, "rt", encoding="utf-8", newline="") as source:
            groups = itertools.groupby(csv.DictReader(source), lambda r: int(r["year"]))
            current = next(groups, None)
            for year, company_rows in panel_years.items():
                cells = defaultdict(lambda: defaultdict(list))
                if current is not None and current[0] == year:
                    for r in current[1]:
                        name = names[(r["family"], r["question_code"], r["column_header"])]
                        cells[r["cdp_account_number"]][name].append(r["answer"])
                    current = next(groups, None)
                for row in company_rows:
                    expanded = dict(row)
                    for name, values in cells.get(row["cdp_account_number"], {}).items():
                        expanded[name] = (values[0] if len(values) == 1 else
                                          json.dumps(values, ensure_ascii=False, separators=(",", ":")))
                    writer.writerow(expanded)
                    written += 1
                print(f"{year}: expanded {len(company_rows):,} company-years", flush=True)
    if written != len(rows):
        raise AssertionError("Company-year row count changed")
    mapping_path = panel_path.parent / "cdp_column_name_mapping.csv"
    with mapping_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["column_name", "family", "question_code", "column_header", "answer_cells"])
        for key, name in names.items():
            writer.writerow([name, *key, counts[key]])
    with (panel_path.parent / "cdp_question_mapping_by_year.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["year", "harmonized_family", "source_question_code", "answer_cells"])
        for key, count in sorted(question_counts.items()):
            writer.writerow([*key, count])
    pending.replace(panel_path)
    print(f"Saved {written:,} rows, {len(names):,} CDP answer columns, "
          f"{sum(counts.values()):,} source cells; mapping: {mapping_path}", flush=True)
    clean_panel(panel_path)


def answer_only(value):
    """Strip provenance from the previous repeated-answer representation."""
    if value.startswith("[{"):
        try:
            items = json.loads(value)
        except ValueError:
            return value
        if isinstance(items, list) and items and all(
                isinstance(item, dict) and "answer" in item for item in items):
            return json.dumps([item["answer"] for item in items],
                              ensure_ascii=False, separators=(",", ":"))
    return value


def missing_value(value):
    # Empty cells and conventional CSV missing-value markers; no-response
    # statements such as "Question not applicable" remain substantive answers.
    markers = {"", "nan", "-nan", "na", "n/a", "null", "none", "<na>",
               "#na", "#n/a", "#n/a n/a", "-1.#ind", "1.#ind", "-1.#qnan", "1.#qnan"}
    if value.strip().lower() in markers:
        return True
    if value.startswith("["):
        try:
            items = json.loads(value)
        except ValueError:
            return False
        if isinstance(items, list):
            return all(item is None or str(item).strip().lower() in markers for item in items)
    return False


def clean_panel(panel_path: Path):
    """Keep answer values only and columns missing in at most 65% of rows.

    The threshold applies to all columns over the entire company-year panel.
    Verify row count and exact transformed values before replacing the file.
    """
    csv.field_size_limit(100_000_000)
    missing = Counter()
    nrows = 0
    with gzip.open(panel_path, "rt", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames
        for row in reader:
            for col, value in row.items():
                if missing_value(answer_only(value) if col.startswith("cdp_") else value):
                    missing[col] += 1
            nrows += 1
    if not nrows:
        raise ValueError("Cannot filter an empty panel")
    kept = [col for col in columns if col not in DROP_COLUMNS and
            (col in KEEP_COLUMNS or col in {"primary_sector", "primary_industry"}
             or missing[col] * 100 <= nrows * 65)]
    pending = panel_path.with_name(panel_path.name + ".partial")
    expected = hashlib.sha256()
    with gzip.open(panel_path, "rt", encoding="utf-8", newline="") as source, \
            gzip.open(pending, "wt", encoding="utf-8", newline="") as target:
        writer = csv.writer(target)
        writer.writerow(kept)
        for row in csv.DictReader(source):
            values = [answer_only(row[c]) if c.startswith("cdp_") else row[c] for c in kept]
            writer.writerow(values)
            expected.update(json.dumps(values, ensure_ascii=False).encode("utf-8"))
    actual = hashlib.sha256()
    checked = 0
    with gzip.open(pending, "rt", encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream)
        assert next(reader) == kept
        for values in reader:
            assert len(values) == len(kept)
            actual.update(json.dumps(values, ensure_ascii=False).encode("utf-8"))
            checked += 1
    assert checked == nrows and actual.digest() == expected.digest()
    audit_path = panel_path.parent / "cdp_panel_column_missingness.csv"
    with audit_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["column_name", "missing_rows", "total_rows", "missing_pct", "retained"])
        for col in columns:
            writer.writerow([col, missing[col], nrows, 100 * missing[col] / nrows, col in kept])
    mapping_path = panel_path.parent / "cdp_column_name_mapping.csv"
    if mapping_path.exists():
        with mapping_path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            fields = list(reader.fieldnames)
            mapping = list(reader)
        if "retained" not in fields:
            fields.append("retained")
        with mapping_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for row in mapping:
                row["retained"] = row["column_name"] in kept
                writer.writerow(row)
    pending.replace(panel_path)
    print(f"Validated {nrows:,} rows; kept {len(kept)} columns; "
          f"removed {len(columns) - len(kept)} columns using missingness and explicit selection rules.", flush=True)

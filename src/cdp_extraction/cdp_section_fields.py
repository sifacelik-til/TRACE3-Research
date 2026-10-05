"""Exact answer-field registry and connected-company splits for the section benchmark."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "processed" / "cdp_section_datasets"
OUTPUT = ROOT / "data" / "outputs" / "cdp_text_clustering" / "cdp_sections_benchmark_2020_2025"
FILES = {
    "targets_performance": "cdp_targets_performance_2016_2025.csv",
    "risks_opportunities": "cdp_risks_opportunities_2016_2025.csv",
    "engagement": "cdp_engagement_2016_2025.csv",
}
TARGET_FIELDS = {
    "initiative": {"initiative_details": "action"},
    **{kind: {"target_plan_progress": "action", "target_key_initiatives": "action",
              "target_description": "action"} for kind in (
        "absolute_target", "intensity_target", "energy_target", "other_target", "net_zero_target")},
    "no_initiative": {"no_initiative_reason": "barrier"},
}
ENGAGEMENT_FIELDS = {
    "engagement_details": "engagement", "engagement_effect": "engagement",
    "coverage_reason": "engagement", "requirement_details": "engagement",
    "noncompliance_procedure": "engagement", "noncompliance_response": "engagement",
    "supplier_data_use": "engagement", "supplier_data_details": "engagement",
    "engagement_action": "engagement", "no_engagement_expl": "barrier",
}
BENCHMARK_FIELDS = {
    "reduction": ("initiative_details", "target_plan_progress"),
    "risk": ("description", "response_strategy"),
    "opportunity": ("description", "response_strategy"),
    "engagement": ("engagement_details", "engagement_effect"),
}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def file_digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def write_json(path: Path, value: dict) -> None:
    pending = path.with_suffix(path.suffix + ".pending")
    pending.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                       encoding="utf-8")
    pending.replace(path)


def read_fields(path: Path) -> list[dict]:
    opener = gzip.open if path.suffix == ".gz" else Path.open
    with opener(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def connected_accounts(path: Path) -> dict[str, str]:
    parent = {}

    def find(key):
        parent.setdefault(key, key)
        while key != parent[key]:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if not 2020 <= int(row["year"]) <= 2025:
                continue
            account = "cdp:" + row["cdp_account_number"]
            find(account)
            for name in ("factset_entity_id", "trucost_company_id", "lseg_isin"):
                value = row[name].strip()
                if not value or value.casefold() in {"nan", "none", "null"}:
                    continue
                first, second = find(account), find(name + ":" + value)
                if first != second:
                    parent[max(first, second)] = min(first, second)
    return {key.removeprefix("cdp:"): find(key) for key in parent if key.startswith("cdp:")}


def split_for(group: str) -> str:
    bucket = int(digest("20261001|" + group)[:12], 16) % 100
    return "train" if bucket < 60 else "selection" if bucket < 80 else "verification"


def field_definitions(section: str, kind: str) -> tuple[str, dict[str, str]]:
    if section == "targets_performance":
        return "reduction", TARGET_FIELDS.get(kind, {})
    if section == "risks_opportunities":
        if kind not in {"risk", "opportunity"}:
            return "", {}
        return kind, {
            "description": kind, "response_strategy": "action",
            "response_cost_desc": "action",
        }
    if section == "engagement":
        return "engagement", ENGAGEMENT_FIELDS
    raise ValueError(f"Unsupported section: {section}")


def normalized_text(text: str) -> str:
    return " ".join(text.casefold().split())


def prepare(output: Path = OUTPUT, source: Path = SOURCE) -> list[dict]:
    output.mkdir(parents=True, exist_ok=True)
    fingerprint = {
        "version": 1, "years": [2020, 2025], "split_seed": 20261001,
        "sources": {name: file_digest(source / filename) for name, filename in FILES.items()},
        "links": file_digest(source / "company_year_links.csv"),
        "field_definitions": {
            "targets": TARGET_FIELDS, "engagement": ENGAGEMENT_FIELDS,
            "risk_opportunity": ["description", "response_strategy", "response_cost_desc"],
        },
    }
    manifest = output / "data_manifest.json"
    registry = output / "fields.jsonl.gz"
    if manifest.exists():
        state = json.loads(manifest.read_text(encoding="utf-8"))
        if state["fingerprint"] != fingerprint:
            raise ValueError("Section input files or field definitions changed; choose a new output")
        if not registry.exists():
            raise ValueError("Registry missing despite completed data manifest")
        if file_digest(registry) != state["registry_sha256"]:
            raise ValueError("Completed field registry has changed")
        return read_fields(registry)
    accounts = connected_accounts(source / "company_year_links.csv")
    fields, seen = [], set()
    source_counts, coverage, reasons, relevance = Counter(), Counter(), Counter(), Counter()
    for section, filename in FILES.items():
        with (source / filename).open(encoding="utf-8-sig", newline="") as stream:
            for record in csv.DictReader(stream):
                year = int(record["year"])
                if not 2020 <= year <= 2025:
                    continue
                source_counts[(section, year)] += 1
                goal, definitions = field_definitions(section, record["record_type"])
                if not definitions:
                    reasons[(section, "record_type_outside_scope")] += 1
                    continue
                account = record["cdp_account_number"]
                if account not in accounts:
                    raise ValueError(f"Account not in matched linkage panel: {account}")
                industry = record["primary_industry"].strip()
                if industry.casefold() == "fossil fuels":
                    industry = "Fossil fuels"
                sector_status = ("missing" if not industry else "unrecognized"
                                 if industry == "Corporate Tags" else "reported")
                for name, role in definitions.items():
                    if name not in record:
                        raise ValueError(f"Mapped field missing in {filename}: {name}")
                    text = record[name]
                    key = (section, goal, name, year)
                    if not text.strip():
                        coverage[(*key, "blank")] += 1
                        continue
                    if normalized_text(text) in {"n/a", "na", "not applicable", "not available", "-"}:
                        coverage[(*key, "placeholder")] += 1
                        continue
                    field_id = f"{section}|{record['record_id']}|{name}"
                    if field_id in seen:
                        raise ValueError(f"Duplicate source field: {field_id}")
                    seen.add(field_id)
                    coverage[(*key, "available")] += 1
                    climate = record.get("climate_relevance", "") or "climate_questionnaire"
                    relevance[(goal, climate)] += 1
                    fields.append({
                        "field_id": field_id, "record_id": record["record_id"],
                        "dataset": section, "goal": goal, "record_type": record["record_type"],
                        "source_field": name, "role": role, "text": text, "year": year,
                        "text_sha256": digest(text), "normalized_sha256": digest(normalized_text(text)),
                        "company_id": account, "company_name": record["company_name"],
                        "connected_group": accounts[account], "split": split_for(accounts[account]),
                        "sector_label": industry or "unknown", "sector_status": sector_status,
                        "primary_sector_reported": record["primary_sector"],
                        "climate_relevance": climate, "question_code": record["question_code"],
                        "source_row": record["source_row"], "source_path": str(source / filename),
                        "reported_selection": record.get("initiative_type", "") or record.get("driver", "")
                        or record.get("engagement_category", "") or record.get("engagement_type", ""),
                    })
    train_text = {row["normalized_sha256"] for row in fields if row["split"] == "train"}
    selection_text = {row["normalized_sha256"] for row in fields if row["split"] == "selection"}
    for row in fields:
        row["evaluation_status"] = (
            "training" if row["split"] == "train" else
            "excluded_duplicate_training" if row["normalized_sha256"] in train_text else
            "excluded_duplicate_selection" if row["split"] == "verification"
            and row["normalized_sha256"] in selection_text else "eligible"
        )
    pending = registry.with_suffix(".pending.gz")
    with gzip.open(pending, "wt", encoding="utf-8") as stream:
        for row in fields:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    pending.replace(registry)
    with (output / "field_coverage.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["dataset", "goal", "source_field", "year", "status", "fields"])
        writer.writerows([*key, count] for key, count in sorted(coverage.items()))
    write_json(manifest, {
        "fingerprint": fingerprint, "registry_sha256": file_digest(registry),
        "source_rows_2020_2025": sum(source_counts.values()), "available_fields": len(fields),
        "unique_texts": len({row["text_sha256"] for row in fields}),
        "year_counts": dict(Counter(row["year"] for row in fields)),
        "goal_counts": dict(Counter(row["goal"] for row in fields)),
        "source_counts": [{"dataset": key[0], "year": key[1], "rows": count}
                          for key, count in sorted(source_counts.items())],
        "split_counts": dict(Counter(row["split"] for row in fields)),
        "sector_counts": dict(Counter(row["sector_status"] for row in fields)),
        "climate_relevance": [{"goal": key[0], "status": key[1], "fields": count}
                              for key, count in sorted(relevance.items())],
        "excluded_record_types": {key[0]: count for key, count in reasons.items()},
        "scope": "Narrative strategy, risk/opportunity item and engagement fields; verification, carbon pricing, assessment processes and numeric-only fields are outside scope.",
    })
    return fields


def year_balanced(rows: list[dict], count: int) -> list[dict]:
    pools = defaultdict(list)
    for row in sorted(rows, key=lambda row: digest("sample|" + row["field_id"])):
        pools[row["year"]].append(row)
    result, seen = [], set()
    while len(result) < count:
        progressed = False
        for year in sorted(pools):
            while pools[year]:
                row = pools[year].pop()
                if row["normalized_sha256"] not in seen:
                    seen.add(row["normalized_sha256"])
                    result.append(row)
                    progressed = True
                    break
            if len(result) == count:
                break
        if not progressed:
            break
    return result


def benchmark_sample(fields: list[dict], output: Path, per_cohort: int = 48) -> list[dict]:
    if per_cohort < 36 or per_cohort % 6:
        raise ValueError("Per-cohort sample must be a multiple of six and at least 36")
    budgets = {"train": per_cohort * 2 // 3,
               "selection": per_cohort // 6, "verification": per_cohort // 6}
    grouped = defaultdict(list)
    for row in fields:
        if (row["source_field"] in BENCHMARK_FIELDS[row["goal"]]
                and row["sector_status"] == "reported"
                and row["evaluation_status"] in {"training", "eligible"}):
            grouped[(row["goal"], row["source_field"], row["sector_label"])].append(row)
    selected, ledger = [], []
    for goal, names in BENCHMARK_FIELDS.items():
        for name in names:
            candidates = []
            for key, rows in grouped.items():
                if key[:2] != (goal, name):
                    continue
                parts = {split: year_balanced([row for row in rows if row["split"] == split], budget)
                         for split, budget in budgets.items()}
                supported = all(len(parts[split]) == budget for split, budget in budgets.items())
                available_years = {row["year"] for row in rows}
                supported = supported and all(
                    {row["year"] for row in part} == available_years for part in parts.values())
                ledger.append({"goal": goal, "source_field": name, "sector_label": key[2],
                               "available": len(rows), "sample_supported": supported})
                if supported:
                    candidates.append((len(rows), key, parts))
            candidates.sort(key=lambda item: (-item[0], item[1]))
            if len(candidates) < 2:
                raise ValueError(f"Fewer than two adequately supported sectors for {goal}/{name}")
            for _, key, parts in candidates[:2]:
                cohort = "|".join(key)
                selected.extend({**row, "cohort": cohort}
                                for split in budgets for row in parts[split])
    fingerprint = {"per_cohort": per_cohort,
                   "fields": [[row["field_id"], row["text_sha256"], row["split"]] for row in selected]}
    path = output / "sample_manifest.json"
    if path.exists() and json.loads(path.read_text())["fingerprint"] != fingerprint:
        raise ValueError("Benchmark sample differs; choose a new output directory")
    write_json(path, {"fingerprint": fingerprint, "fields": len(selected),
                      "cohorts": len({row["cohort"] for row in selected}),
                      "budgets": budgets, "cohort_eligibility": ledger})
    with (output / "sample_fields.jsonl").open("w", encoding="utf-8") as stream:
        for row in selected:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    return selected

"""Apply evidence-linked development-sample suggestions without accepting AI labels."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import logging
import shutil
from collections import Counter, defaultdict
from pathlib import Path

from src.cdp_text_clustering.cdp_field_chunking import validate_codebook
from src.cdp_extraction.prepare_cdp_annotation_sample import excel_safe

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
METHOD = "copilot_assisted_initiative_review_v1"
LOGGER = logging.getLogger(__name__)
CONTEXT_COLUMNS = [
    "company_id", "company_name", "year", "primary_sector_reported",
    "primary_industry_reported", "sector_label", "sector_label_source",
    "reported_initiative_name", "initiative_name", "parent_code",
    "initiative_cluster_key", "sector_initiative_cluster_key", "suggestion_method",
]


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def source_context(fields: list[dict], root: Path) -> dict[str, dict]:
    grouped = defaultdict(list)
    for field in fields:
        grouped[field["source_path"]].append(field)
    contexts = {}
    for source_path, group in grouped.items():
        path = (root / source_path).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError(f"Source outside repository: {source_path}")
        wanted = {field["record_id"] for field in group}
        matched = {}
        opener = gzip.open if path.suffix == ".gz" else Path.open
        with opener(path, "rt", encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                record_id = row.get("record_id") or (
                    f"2024:{row['question_number']}:{row['cdp_disclosing_org_number']}"
                    f":{row['row_order']}"
                )
                if record_id not in wanted:
                    continue
                if record_id in matched:
                    raise ValueError(f"Duplicate source record: {source_path}/{record_id}")
                matched[record_id] = row
        if wanted != set(matched):
            raise ValueError(f"Source records missing: {sorted(wanted - set(matched))}")
        for field in group:
            row = matched[field["record_id"]]
            company = row.get("cdp_account_number", row.get("cdp_disclosing_org_number"))
            if company != field["company_id"] or row.get("year", "2024") != field["year"]:
                raise ValueError(f"Source company/year mismatch: {field['field_id']}")
            if row[field["source_field"]] != field["text"]:
                raise ValueError(f"Source text changed: {field['field_id']}")
            industry = row.get("primary_industry", row.get("primary_industry_name", "")).strip()
            # CDP's industry is the comparable broad level; sector is finer and absent in 2024.
            label = "Fossil fuels" if industry.casefold() == "fossil fuels" else industry
            metadata = field["source_metadata"]
            reported_name = metadata.get("structured_selection_col1", "") or ": ".join(
                value for value in (metadata.get("initiative_category_reported", ""),
                                    metadata.get("initiative_type_reported", "")) if value
            )
            contexts[field["field_id"]] = {
                "company_id": company,
                "company_name": row.get("organization", row.get("disclosing_organization", "")),
                "year": field["year"],
                "primary_sector_reported": row.get("primary_sector", ""),
                "primary_industry_reported": industry,
                "sector_label": label or "unknown",
                "sector_label_source": (
                    "cdp_primary_industry" if industry else "missing_in_source"
                ),
                "reported_initiative_name": reported_name,
            }
    return contexts


def label_context(context: dict, code: dict, reviewed: bool) -> dict:
    actionable = reviewed and code["code"] not in {
        "insufficient_information", "general_environmental_effort",
    }
    key = code["code"] if actionable else ""
    return {
        **context,
        "initiative_name": code.get("label", code["code"].replace("_", " ")) if key else "",
        "parent_code": code.get("parent_code", "") if reviewed else "",
        "initiative_cluster_key": key,
        "sector_initiative_cluster_key": (
            f"cdp_primary_industry:{context['sector_label'].casefold()}|{key}"
            if key and context["sector_label_source"] == "cdp_primary_industry" else ""
        ),
    }


def reviewed_candidates(fields: list[dict], chunks: list[dict], review: dict,
                        codebook: list[dict], contexts: dict[str, dict]) -> list[dict]:
    validate_codebook(codebook)
    codes = {code["code"]: code for code in codebook}
    selected = [field for field in fields if field["dataset"] in review["scope"]
                and field["field_status"] == "available"]
    ids = [field["record_id"] for field in selected]
    if len(set(ids)) != len(ids) or set(ids) != set(review["evidence"]):
        raise ValueError("Review manifest must match every available initiative exactly")
    if set(review.get("notes", {})) - set(ids):
        raise ValueError("Review notes refer to unknown initiatives")
    grouped_chunks = defaultdict(list)
    for chunk in chunks:
        grouped_chunks[chunk["field_id"]].append(chunk)
    proposals = []
    for field in selected:
        entries = review["evidence"][field["record_id"]]
        if not entries or len({entry[0] for entry in entries}) != len(entries):
            raise ValueError(f"Missing or duplicate codes: {field['record_id']}")
        if len(entries) > 1 and any(code == "insufficient_information" for code, _ in entries):
            raise ValueError("Insufficient information must not coexist with mechanism codes")
        for code_id, excerpt in entries:
            code = codes.get(code_id)
            if code is None or field["role"] not in code["roles"]:
                raise ValueError(f"Invalid code: {field['record_id']}/{code_id}")
            text = field["text"]
            if not excerpt or text.count(excerpt) != 1:
                raise ValueError(f"Evidence must match once: {field['record_id']}/{code_id}")
            start = text.index(excerpt)
            end = start + len(excerpt)
            overlaps = [chunk for chunk in grouped_chunks[field["field_id"]]
                        if chunk["start"] < end and chunk["end"] > start]
            cursor = start
            for chunk in sorted(overlaps, key=lambda item: item["start"]):
                if chunk["start"] > cursor:
                    raise ValueError("Evidence crosses a gap in chunk coverage")
                cursor = max(cursor, chunk["end"])
            if cursor < end:
                raise ValueError("Evidence is not covered by source chunks")
            note = review.get("notes", {}).get(field["record_id"], "")
            if code_id == "insufficient_information":
                note = ("Comment does not establish an action mechanism. The reported selection "
                        "is retained as metadata, not substituted for comment evidence. " + note).strip()
            proposals.append({
                **{key: field[key] for key in ("dataset", "record_id", "field_id", "source_field")},
                **label_context(contexts[field["field_id"]], code, True),
                "chunk_id": overlaps[0]["chunk_id"] if len(overlaps) == 1 else None,
                "chunk_ids": [chunk["chunk_id"] for chunk in overlaps],
                "code": code_id, "evidence_start": start, "evidence_end": end,
                "evidence_text": excerpt, "similarity": None,
                "review_status": "unreviewed_ai_candidate", "suggestion_method": METHOD,
                "interpretation": (
                    "AI-assisted evidence review, not a human-accepted annotation. "
                    "Canonical action names group mechanisms, not initiative entities. "
                    "Codes do not establish implementation status or realised savings."
                ),
                "notes": note,
            })
    return proposals


def populate_template(existing: list[dict], proposals: list[dict],
                      contexts: dict[str, dict]) -> list[dict]:
    grouped = defaultdict(list)
    for row in proposals:
        grouped[row["field_id"]].append(row)
    current = defaultdict(list)
    for row in existing:
        current[row["field_id"]].append(row)
    if set(grouped) - set(current):
        raise ValueError("Reviewed fields missing from coding template")
    result = []
    for field_id, rows in current.items():
        if field_id not in contexts:
            raise ValueError(f"Unknown template field: {field_id}")
        protected = any(
            row.get("reviewer_id") or row.get("review_date")
            or row.get("review_status") not in ("", "pending")
            or any(row.get(key) for key in (
                "code", "evidence_start", "evidence_end", "evidence_text", "notes"
            ))
            for row in rows
        )
        if field_id not in grouped or protected:
            # Human edits, including pending work and rejected annotations, are never replaced.
            result.extend({**contexts[field_id], **row} for row in rows)
            continue
        for proposal in grouped[field_id]:
            result.append({
                **{key: proposal[key] for key in (
                    "dataset", "record_id", "field_id", "source_field", "code",
                    "evidence_start", "evidence_end", "evidence_text", *CONTEXT_COLUMNS,
                )},
                "reviewer_id": "", "review_date": "", "review_status": "pending",
                "notes": ("AI suggestion; verify the exact evidence before accepting. "
                          + proposal["notes"]).strip(),
            })
    return result


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: (row.get(key, "") if key == "evidence_text" else excel_safe(row.get(key, "")))
                for key in columns
            })


def run(output: Path, review_path: Path) -> dict:
    fields = read_jsonl(output / "fields.jsonl")
    if len({field["field_id"] for field in fields}) != len(fields):
        raise ValueError("Duplicate source field IDs")
    chunks = read_jsonl(output / "chunks.jsonl")
    review = json.loads(review_path.read_text(encoding="utf-8"))
    codebook_path = HERE / "cdp_field_codebook.json"
    codebook = json.loads(codebook_path.read_text(encoding="utf-8"))
    original = output / "coding_candidates.original.jsonl"
    retrieval = read_jsonl(original if original.exists() else output / "coding_candidates.jsonl")
    with (output / "coding_template.csv").open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = list(reader.fieldnames or [])
        existing = list(reader)
    available = {field["field_id"] for field in fields if field["field_status"] == "available"}
    if {row["field_id"] for row in existing} != available:
        raise ValueError("Template coverage differs from available source fields")
    contexts = source_context(fields, ROOT)
    revised = reviewed_candidates(fields, chunks, review, codebook, contexts)
    revised_ids = {row["field_id"] for row in revised}
    proposals = []
    code_by_id = {code["code"]: code for code in codebook}
    for row in retrieval:
        if row["field_id"] not in revised_ids:
            proposals.append({
                **row, **label_context(contexts[row["field_id"]], code_by_id[row["code"]], False),
                "suggestion_method": "original_top_two_retrieval_not_reviewed",
            })
    proposals = revised + proposals
    template = populate_template(existing, revised, contexts)
    if {row["field_id"] for row in proposals} != available:
        raise ValueError("Candidate coverage differs from available source fields")
    for code in codebook:
        if code.get("parent_code") and code["parent_code"] not in code_by_id:
            raise ValueError(f"Unknown parent code: {code['code']}")
    for filename in ("coding_candidates.jsonl", "coding_template.csv", "codebook.json"):
        path = output / filename
        backup = path.with_name(f"{path.stem}.original{path.suffix}")
        if not backup.exists():
            shutil.copyfile(path, backup)
    with (output / "coding_candidates.jsonl").open("w", encoding="utf-8") as stream:
        for proposal in proposals:
            stream.write(json.dumps(proposal, ensure_ascii=False, allow_nan=False) + "\n")
    write_csv(output / "coding_template.csv", template,
              list(dict.fromkeys([*columns, *CONTEXT_COLUMNS])))
    write_json(output / "codebook.json", {
        "status": "draft_for_human_review", "codes": codebook,
        "retrieval_codebook": "codebook.original.json",
        "note": "Expanded review vocabulary; original embedding similarities were not recomputed.",
    })
    write_csv(output / "initiative_cluster_labels.csv", revised, [
        "dataset", "record_id", "field_id", "source_field", "code", *CONTEXT_COLUMNS,
        "evidence_start", "evidence_end", "evidence_text", "review_status", "notes",
    ])
    counts = Counter(row["code"] for row in revised)
    summary = {
        "method": METHOD, "review_status": "ai_suggestions_require_human_review",
        "review_manifest": str(review_path.resolve().relative_to(ROOT)),
        "review_manifest_sha256": hashlib.sha256(review_path.read_bytes()).hexdigest(),
        "codebook_sha256": hashlib.sha256(codebook_path.read_bytes()).hexdigest(),
        "fields_sha256": hashlib.sha256((output / "fields.jsonl").read_bytes()).hexdigest(),
        "initiative_fields_reviewed": len(revised_ids),
        "initiative_code_suggestions": len(revised),
        "insufficient_comment_fields": counts["insufficient_information"],
        "other_fields_not_relabelled": len(available - revised_ids),
        "original_candidates": len(retrieval), "current_candidates": len(proposals),
        "template_rows": len(template), "code_counts": dict(counts),
        "reviewed_split_counts": dict(Counter(
            field["split"] for field in fields if field["field_id"] in revised_ids
        )),
        "initiative_sector_counts": dict(Counter(
            contexts[field_id]["sector_label"] for field_id in sorted(revised_ids)
        )),
        "limitations": [
            "Only the two initiative datasets were evidence-reviewed; other candidates are unchanged.",
            "All new suggestions remain pending. Existing human template work is preserved.",
            "Sector labels use reported CDP primary industry, never keywords or inferred company identity.",
            "Detailed primary sector is preserved separately; missing classifications stay unknown.",
            "Canonical names group action mechanisms, not named-programme or company entities.",
            "Planned and completed actions are not separated by these grouping keys.",
            "Both development train and holdout comments informed this vocabulary; neither is an untouched coding-accuracy test set.",
            "No clustering, embeddings, benchmark metrics or original experiment metadata were recomputed.",
            "Original top-two scores refer to the archived codebook; reviewed suggestions have null scores.",
        ],
    }
    write_json(output / "initiative_review_summary.json", summary)
    LOGGER.info("Reviewed %s initiative fields; %s suggestions; %s insufficient comments",
                len(revised_ids), len(revised), counts["insufficient_information"])
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=(
        ROOT / "data" / "outputs" / "cdp_text_clustering" / "cdp_field_chunks_minilm_development"
    ))
    parser.add_argument("--review", type=Path, default=HERE / "cdp_initiative_review.json")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run(args.output, args.review)

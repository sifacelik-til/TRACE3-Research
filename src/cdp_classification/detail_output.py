"""Extract, validate, and export item-level CDP classifications.

The column layouts in ``cdp_classification_all_details.xlsx`` are the output
contract.  One source answer may generate any number of item rows.  The module
uses only the Python standard library so it can run in the data pipeline
without an Excel dependency.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath


SHEET_CONFIG = {
    "reduction": {
        "sheet": "Reduction actions",
        "review_sheet": "Reduction review",
        "file": "reduction_actions.csv.gz",
        "review_prefix": "RED",
        "item_marker": "A",
        "headers": [
            "Review ID", "Item ID", "Item number", "Industry", "Company", "Year",
            "Source field", "Listed measure", "Action class", "Action family",
            "Item role", "Implementation stage", "Targeted emission scope",
            "Counterparty", "Evidence excerpt", "Coding notes", "Review status",
            "Source answer cell", "Counts as action",
        ],
        "eligibility": "Counts as action",
    },
    "engagement": {
        "sheet": "Engagement details",
        "review_sheet": "Engagement review",
        "file": "engagement_details.csv.gz",
        "review_prefix": "ENG",
        "item_marker": "D",
        "headers": [
            "Review ID", "Item ID", "Item number", "Industry", "Company", "Year",
            "Source field", "Item role", "Item class",
            "Engagement mechanism or policy", "Counterparty", "Objective",
            "Intensity or stage", "Answer in scope?", "Evidence excerpt",
            "Coding notes", "Review status", "Source answer cell",
            "In-scope engagement item?",
        ],
        "eligibility": "In-scope engagement item?",
    },
    "risk": {
        "sheet": "Risk details",
        "review_sheet": "Risk review",
        "file": "risk_details.csv.gz",
        "review_prefix": "RSK",
        "item_marker": "D",
        "headers": [
            "Review ID", "Item ID", "Item number", "Industry", "Company", "Year",
            "Source field", "Item role", "Item class", "Risk driver", "Risk type",
            "Operational exposure", "Time horizon", "Stated response",
            "Evidence excerpt", "Coding notes", "Review status", "Source answer cell",
            "In-scope risk item?",
        ],
        "eligibility": "In-scope risk item?",
    },
    "opportunity": {
        "sheet": "Opportunity details",
        "review_sheet": "Opportunity review",
        "file": "opportunity_details.csv.gz",
        "review_prefix": "OPP",
        "item_marker": "D",
        "headers": [
            "Review ID", "Item ID", "Item number", "Industry", "Company", "Year",
            "Source field", "Item role", "Item class", "Opportunity driver",
            "Opportunity type", "Expected benefit", "Time horizon", "Stated response",
            "Evidence excerpt", "Coding notes", "Review status", "Source answer cell",
            "In-scope opportunity item?",
        ],
        "eligibility": "In-scope opportunity item?",
    },
}

ENUMERATION_COLUMNS = {
    "Item role", "Action family", "Implementation stage", "Targeted emission scope",
    "Counterparty", "Intensity or stage", "Answer in scope?", "Risk type",
    "Opportunity type", "Time horizon", "Review status", "Counts as action",
    "In-scope engagement item?", "In-scope risk item?", "In-scope opportunity item?",
}

_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def _column_number(reference: str) -> int:
    match = re.match(r"([A-Z]+)", reference)
    if not match:
        raise ValueError(f"Invalid cell reference: {reference}")
    result = 0
    for character in match.group(1):
        result = result * 26 + ord(character) - 64
    return result - 1


def _xlsx_sheets(path: Path) -> dict[str, list[list[object]]]:
    """Read cell values from an XLSX file without altering the workbook."""
    with zipfile.ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {item.attrib["Id"]: item.attrib["Target"] for item in relationships}
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared_strings = [
                "".join(node.text or "" for node in item.iter(f"{{{_NS['x']}}}t"))
                for item in strings
            ]

        result = {}
        for sheet in workbook.find("x:sheets", _NS):
            name = sheet.attrib["name"]
            target = PurePosixPath("xl") / targets[sheet.attrib[_RID]].lstrip("/")
            xml = ET.fromstring(archive.read(str(target)))
            rows = []
            sheet_data = xml.find("x:sheetData", _NS)
            if sheet_data is None:
                result[name] = rows
                continue
            for xml_row in sheet_data:
                cells: dict[int, object] = {}
                for cell in xml_row:
                    column = _column_number(cell.attrib["r"])
                    cell_type = cell.attrib.get("t")
                    value_node = cell.find("x:v", _NS)
                    inline = cell.find("x:is", _NS)
                    value: object = ""
                    if value_node is not None:
                        raw = value_node.text or ""
                        if cell_type == "s":
                            value = shared_strings[int(raw)]
                        elif cell_type == "b":
                            value = raw == "1"
                        elif cell_type in {"n", None}:
                            try:
                                number = float(raw)
                                value = int(number) if number.is_integer() else number
                            except ValueError:
                                value = raw
                        else:
                            value = raw
                    elif inline is not None:
                        value = "".join(
                            node.text or "" for node in inline.iter(f"{{{_NS['x']}}}t")
                        )
                    cells[column] = value
                width = max(cells, default=-1) + 1
                rows.append([cells.get(column, "") for column in range(width)])
            result[name] = rows
        return result


def validate_item(section: str, row: dict[str, object]) -> None:
    config = SHEET_CONFIG[section]
    missing = [header for header in config["headers"] if header not in row]
    extra = [header for header in row if header not in config["headers"]]
    if missing or extra:
        raise ValueError(f"{section}: schema mismatch; missing={missing}, extra={extra}")

    review_id = str(row["Review ID"])
    item_id = str(row["Item ID"])
    item_number = int(row["Item number"])
    if not re.fullmatch(rf"{config['review_prefix']}-\d{{3,}}", review_id):
        raise ValueError(f"{section}: invalid Review ID {review_id!r}")
    expected = f"{review_id}-{config['item_marker']}{item_number:02d}"
    if item_id != expected:
        raise ValueError(f"{section}: Item ID {item_id!r} should be {expected!r}")
    if not str(row["Industry"]).strip() or not str(row["Source field"]).strip():
        raise ValueError(f"{section}: missing Industry or Source field for {item_id}")
    if str(row["Review status"]) not in {"Pending", "Complete", "Needs discussion", "Exclude"}:
        raise ValueError(f"{section}: invalid Review status for {item_id}")
    if str(row[config["eligibility"]]) not in {"Yes", "No", "Unclear"}:
        raise ValueError(f"{section}: invalid eligibility for {item_id}")
    if not str(row["Evidence excerpt"]).strip():
        raise ValueError(f"{section}: missing evidence for {item_id}")


def extract_validation(workbook: Path, output: Path, contract: Path | None = None) -> dict:
    sheets = _xlsx_sheets(workbook)
    records = []
    answers = []
    counts = {}
    answer_counts = {}
    answers_with_items = {}
    enumerations: dict[str, dict[str, list[str]]] = {}
    seen_item_ids = set()

    for section, config in SHEET_CONFIG.items():
        review_rows = sheets.get(config["review_sheet"])
        if review_rows is None or len(review_rows) < 3:
            raise ValueError(f"Missing review sheet: {config['review_sheet']}")
        review_headers = [str(value) for value in review_rows[2]]
        required_review = {
            "Review ID", "Industry", "Source field", "Year", "Company", "Source text", "Field ID"
        }
        if not required_review.issubset(review_headers):
            raise ValueError(f"{config['review_sheet']} lacks required source columns")
        answer_by_id = {}
        for values in review_rows[3:]:
            padded = list(values) + [""] * (len(review_headers) - len(values))
            review = dict(zip(review_headers, padded[:len(review_headers)]))
            if not str(review["Review ID"]).strip():
                continue
            answer = {
                "section": section,
                "review_id": review["Review ID"],
                "industry": review["Industry"],
                "source_field": review["Source field"],
                "year": review["Year"],
                "company": review["Company"],
                "source_text": review["Source text"],
                "field_id": review["Field ID"],
            }
            answer_by_id[str(review["Review ID"])] = answer
            answers.append(answer)
        answer_counts[section] = len(answer_by_id)

        rows = sheets.get(config["sheet"])
        if rows is None or len(rows) < 3:
            raise ValueError(f"Missing detail sheet: {config['sheet']}")
        headers = [str(value) for value in rows[2]]
        if headers != config["headers"]:
            raise ValueError(
                f"{config['sheet']} columns differ from the output contract:\n"
                f"expected={config['headers']}\nactual={headers}"
            )
        section_records = []
        values_by_column = defaultdict(set)
        for values in rows[3:]:
            padded = list(values) + [""] * (len(headers) - len(values))
            row = dict(zip(headers, padded[:len(headers)]))
            if not str(row["Review ID"]).strip():
                continue
            validate_item(section, row)
            if str(row["Review ID"]) not in answer_by_id:
                raise ValueError(f"{config['sheet']}: missing source answer {row['Review ID']}")
            answer = answer_by_id[str(row["Review ID"])]
            if str(row["Evidence excerpt"]) not in str(answer["source_text"]):
                raise ValueError(f"{config['sheet']}: non-verbatim evidence for {row['Item ID']}")
            if row["Item ID"] in seen_item_ids:
                raise ValueError(f"Duplicate Item ID: {row['Item ID']}")
            seen_item_ids.add(row["Item ID"])
            for column in ENUMERATION_COLUMNS & row.keys():
                if str(row[column]).strip():
                    values_by_column[column].add(str(row[column]))
            section_records.append({"section": section, **row})
        records.extend(section_records)
        counts[section] = len(section_records)
        answers_with_items[section] = len({str(row["Review ID"]) for row in section_records})
        enumerations[section] = {
            column: sorted(values) for column, values in sorted(values_by_column.items())
        }

    output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output, "wt", encoding="utf-8") as stream:
        for row in records:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    answers_path = output.with_name("cdp_validation_answers.jsonl.gz")
    with gzip.open(answers_path, "wt", encoding="utf-8") as stream:
        for row in answers:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")

    workbook_hash = hashlib.sha256(workbook.read_bytes()).hexdigest()
    contract_payload = {
        "version": 1,
        "unit": "one distinct item extracted from one complete CDP answer",
        "industry_specific": True,
        "source_workbook": str(workbook),
        "source_workbook_sha256": workbook_hash,
        "validation_answers": str(answers_path),
        "rules": [
            "Keep one row per distinct item; do not limit an answer to primary and secondary labels.",
            "Link every item to its source answer with Review ID and Source answer cell.",
            "Copy a verbatim item-specific Evidence excerpt.",
            "Use Item role and the final eligibility column to distinguish core items from responses, monitoring and context.",
            "Consolidate repeated mentions of the same item; retain distinct named items separately.",
            "Do not treat engagement or policy disclosure as evidence of an emissions reduction.",
        ],
        "sections": {
            section: {
                "sheet": config["sheet"],
                "output_file": config["file"],
                "headers": config["headers"],
                "eligibility_column": config["eligibility"],
                "validated_rows": counts[section],
                "validated_answers": answer_counts[section],
                "answers_with_detail_rows": answers_with_items[section],
                "observed_values": enumerations[section],
            }
            for section, config in SHEET_CONFIG.items()
        },
        "total_validated_rows": len(records),
    }
    contract_path = contract or output.with_name("cdp_detail_output_contract.json")
    contract_path.write_text(
        json.dumps(contract_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "rows": len(records), "answers": len(answers), "counts": counts,
        "answers_with_items": answers_with_items,
        "labels": str(output), "answer_file": str(answers_path),
        "contract": str(contract_path),
    }


def export_csv(input_path: Path, output_dir: Path) -> dict[str, int]:
    grouped = defaultdict(list)
    opener = gzip.open if input_path.suffix == ".gz" else open
    with opener(input_path, "rt", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            record = json.loads(line)
            section = record.pop("section")
            if section not in SHEET_CONFIG:
                raise ValueError(f"Unknown section: {section}")
            validate_item(section, record)
            grouped[section].append(record)

    output_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for section, config in SHEET_CONFIG.items():
        rows = grouped[section]
        rows.sort(key=lambda row: (str(row["Review ID"]), int(row["Item number"])))
        target = output_dir / config["file"]
        with gzip.open(target, "wt", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=config["headers"], extrasaction="raise")
            writer.writeheader()
            writer.writerows(rows)
        counts[section] = len(rows)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    extract = subparsers.add_parser("extract-validation")
    extract.add_argument("--workbook", type=Path, required=True)
    extract.add_argument("--output", type=Path, required=True)
    extract.add_argument("--contract", type=Path)
    export = subparsers.add_parser("export-csv")
    export.add_argument("--input", type=Path, required=True)
    export.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "extract-validation":
        result = extract_validation(args.workbook, args.output, args.contract)
    else:
        result = export_csv(args.input, args.output_dir)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

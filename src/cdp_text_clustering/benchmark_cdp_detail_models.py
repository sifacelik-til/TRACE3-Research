"""Benchmark structured CDP extraction models against the validated workbook.

The benchmark calls any OpenAI-compatible chat-completions endpoint, including
Ollama's local endpoint.  Predictions are one-to-many item records and are
exported with the exact column layouts defined in ``cdp_detail_output.py``.
Company-level folds prevent answers from the same company appearing in both
the few-shot examples and the evaluation fold.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from src.cdp_text_clustering.cdp_detail_output import SHEET_CONFIG, export_csv, validate_item


DEFAULT_DATA = Path("data/processed/cdp_section_datasets")
DEFAULT_CONTRACT = DEFAULT_DATA / "cdp_detail_output_contract.json"
TAXONOMY_FIELDS = {
    "reduction": ("Action family", "Item role", "Implementation stage", "Targeted emission scope"),
    "engagement": ("Item role", "Counterparty", "Intensity or stage"),
    "risk": ("Risk type", "Item role", "Time horizon"),
    "opportunity": ("Opportunity type", "Item role", "Time horizon"),
}
OUTPUT_FIELDS = {
    "reduction": [
        "Listed measure", "Action class", "Action family", "Item role",
        "Implementation stage", "Targeted emission scope", "Counterparty",
        "Evidence excerpt", "Coding notes", "Review status", "Counts as action",
    ],
    "engagement": [
        "Item role", "Item class", "Engagement mechanism or policy", "Counterparty",
        "Objective", "Intensity or stage", "Answer in scope?", "Evidence excerpt",
        "Coding notes", "Review status", "In-scope engagement item?",
    ],
    "risk": [
        "Item role", "Item class", "Risk driver", "Risk type", "Operational exposure",
        "Time horizon", "Stated response", "Evidence excerpt", "Coding notes",
        "Review status", "In-scope risk item?",
    ],
    "opportunity": [
        "Item role", "Item class", "Opportunity driver", "Opportunity type",
        "Expected benefit", "Time horizon", "Stated response", "Evidence excerpt",
        "Coding notes", "Review status", "In-scope opportunity item?",
    ],
}

EVALUATED_FIELDS = {
    "reduction": [
        "Action class", "Action family", "Item role", "Implementation stage",
        "Targeted emission scope", "Counterparty", "Counts as action",
    ],
    "engagement": [
        "Item role", "Item class", "Engagement mechanism or policy", "Counterparty",
        "Objective", "Intensity or stage", "In-scope engagement item?",
    ],
    "risk": [
        "Item role", "Item class", "Risk driver", "Risk type", "Operational exposure",
        "Time horizon", "In-scope risk item?",
    ],
    "opportunity": [
        "Item role", "Item class", "Opportunity driver", "Opportunity type",
        "Expected benefit", "Time horizon", "In-scope opportunity item?",
    ],
}

SYSTEM_PROMPT = """You extract structured climate-management items from one complete CDP answer.
Return JSON only: {"items": [ ... ]}. Use the exact keys requested by the user.

Rules:
1. Extract every distinct item. There is no primary/secondary limit.
2. Consolidate repeated references to the same item, but keep distinct named measures, mechanisms, risks, opportunities, policies, responses, monitoring activities, and context as separate rows.
3. Evidence excerpt must be a short verbatim substring of SOURCE TEXT. Never paraphrase evidence.
4. Keep classification industry-specific and use the supplied industry and source field.
5. Do not infer implementation, time horizon, counterpart, or benefit from company identity.
6. For risk and opportunity, label supporting actions as Item role Response or Policy; they are not additional risks or opportunities.
7. Engagement or policy disclosure does not prove an emissions reduction.
8. Use Not stated or Unclear when the answer does not support a value.
9. Review status is Complete unless a material classification boundary remains unresolved; then use Needs discussion.
10. The final eligibility field is Yes only for a core item of the requested section, No for response, monitoring, policy-only, or context rows, and Unclear for an unresolved boundary.
11. For Reduction only, return an empty items list when the answer contains no identifiable reduction measure. For Engagement, Risk, and Opportunity retain an explicit context row when no core item is supported.
12. Fields listed under CONTROLLED TAXONOMY must use exactly one of the supplied values. These are predefined topics from the validated workbook; do not invent or merge topic names.
"""


def read_jsonl(path: Path) -> list[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def normalized_tokens(value: object) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", str(value).lower()))


def jaccard(left: object, right: object) -> float:
    a, b = normalized_tokens(left), normalized_tokens(right)
    return len(a & b) / len(a | b) if a or b else 1.0


def fold_for_company(company: str, folds: int) -> int:
    return int(hashlib.sha256(company.casefold().encode("utf-8")).hexdigest()[:12], 16) % folds


def compact_gold(section: str, rows: list[dict]) -> list[dict]:
    return [{field: row[field] for field in OUTPUT_FIELDS[section]} for row in rows]


def select_examples(answer: dict, candidates: list[dict], labels: dict[str, list[dict]], count: int) -> list[dict]:
    same_cohort = [
        row for row in candidates
        if row["section"] == answer["section"]
        and row["industry"] == answer["industry"]
        and row["source_field"] == answer["source_field"]
        and row["company"] != answer["company"]
    ]
    if len(same_cohort) < count:
        same_cohort.extend(
            row for row in candidates
            if row["section"] == answer["section"]
            and row["industry"] == answer["industry"]
            and row["company"] != answer["company"]
            and row not in same_cohort
        )
    ranked = sorted(
        same_cohort,
        key=lambda row: (jaccard(answer["source_text"], row["source_text"]), row["review_id"]),
        reverse=True,
    )
    return [
        {
            "industry": row["industry"],
            "source_field": row["source_field"],
            "source_text": row["source_text"][:2500],
            "items": compact_gold(row["section"], labels[row["review_id"]]),
        }
        for row in ranked[:count]
    ]


def load_taxonomy(contract_path: Path) -> dict[str, dict[str, list[str]]]:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    taxonomy = {}
    for section, fields in TAXONOMY_FIELDS.items():
        observed = contract["sections"][section]["observed_values"]
        taxonomy[section] = {field: observed[field] for field in fields}
    return taxonomy


def prompt_for(answer: dict, examples: list[dict], taxonomy: dict) -> str:
    section = answer["section"]
    schema = {field: "string" for field in OUTPUT_FIELDS[section]}
    return (
        f"SECTION: {section}\nINDUSTRY: {answer['industry']}\n"
        f"SOURCE FIELD: {answer['source_field']}\n"
        f"Each item must have exactly these keys:\n{json.dumps(schema, ensure_ascii=False)}\n\n"
        f"CONTROLLED TAXONOMY (use values exactly):\n"
        f"{json.dumps(taxonomy[section], ensure_ascii=False)}\n\n"
        f"INDUSTRY-SPECIFIC EXAMPLES:\n{json.dumps(examples, ensure_ascii=False)}\n\n"
        f"SOURCE TEXT:\n{answer['source_text']}"
    )


def chat_completion(base_url: str, api_key: str, model: str, prompt: str,
                    timeout: int, response_format: bool) -> tuple[str, dict]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
    }
    if response_format:
        payload["response_format"] = {"type": "json_object"}
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))
    return result["choices"][0]["message"]["content"], result.get("usage", {})


def parse_json(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("No JSON object found")
    result = json.loads(text[start:end + 1])
    if not isinstance(result.get("items"), list):
        raise ValueError("Prediction must contain an items list")
    return result


def complete_rows(answer: dict, items: list[dict], taxonomy: dict) -> list[dict]:
    section = answer["section"]
    config = SHEET_CONFIG[section]
    if not items and section != "reduction":
        raise ValueError(f"{section} requires at least one core, response, or context item")
    rows = []
    for number, item in enumerate(items, 1):
        if set(item) != set(OUTPUT_FIELDS[section]):
            missing = sorted(set(OUTPUT_FIELDS[section]) - set(item))
            extra = sorted(set(item) - set(OUTPUT_FIELDS[section]))
            raise ValueError(f"Prediction keys differ from schema; missing={missing}, extra={extra}")
        row = {
            "Review ID": answer["review_id"],
            "Item ID": f"{answer['review_id']}-{config['item_marker']}{number:02d}",
            "Item number": number,
            "Industry": answer["industry"],
            "Company": answer["company"],
            "Year": answer["year"],
            "Source field": answer["source_field"],
            **item,
            "Source answer cell": f"Field ID: {answer['field_id']}",
        }
        row = {header: row[header] for header in config["headers"]}
        validate_item(section, row)
        for field, allowed in taxonomy[section].items():
            if str(row[field]) not in allowed:
                raise ValueError(
                    f"{field} must use a controlled taxonomy value; got {row[field]!r}"
                )
        if str(row["Evidence excerpt"]) not in str(answer["source_text"]):
            raise ValueError("Evidence excerpt is not verbatim in the source answer")
        rows.append(row)
    return rows


def pair_score(section: str, predicted: dict, gold: dict) -> float:
    class_field = "Action class" if section == "reduction" else "Item class"
    return 0.65 * jaccard(predicted[class_field], gold[class_field]) + 0.35 * jaccard(
        predicted["Evidence excerpt"], gold["Evidence excerpt"]
    )


def match_items(section: str, predicted: list[dict], gold: list[dict]) -> list[tuple[dict, dict, float]]:
    candidates = sorted(
        (
            (pair_score(section, pred, target), p_index, g_index)
            for p_index, pred in enumerate(predicted)
            for g_index, target in enumerate(gold)
        ),
        reverse=True,
    )
    used_pred, used_gold, result = set(), set(), []
    for score, p_index, g_index in candidates:
        if p_index in used_pred or g_index in used_gold:
            continue
        used_pred.add(p_index)
        used_gold.add(g_index)
        result.append((predicted[p_index], gold[g_index], score))
    return result


def evaluate(answer_results: list[dict], gold_by_review: dict[str, list[dict]]) -> list[dict]:
    buckets = defaultdict(list)
    for result in answer_results:
        buckets[(result["section"], result["industry"])].append(result)
        buckets[(result["section"], "ALL")].append(result)
        buckets[("ALL", "ALL")].append(result)
    metrics = []
    for (section_key, industry), results in sorted(buckets.items()):
        valid = [row for row in results if row["status"] == "ok"]
        gold_total = pred_total = matched_total = evidence_total = 0
        field_correct = Counter()
        field_total = Counter()
        item_count_error = 0
        for result in valid:
            section = result["section"]
            gold = gold_by_review.get(result["review_id"], [])
            predicted = result["rows"]
            gold_total += len(gold)
            pred_total += len(predicted)
            item_count_error += abs(len(predicted) - len(gold))
            pairs = match_items(section, predicted, gold)
            accepted = [(left, right) for left, right, score in pairs if score >= 0.25]
            matched_total += len(accepted)
            evidence_total += sum(
                str(row["Evidence excerpt"]) in str(result["source_text"]) for row in predicted
            )
            for left, right in accepted:
                for field in EVALUATED_FIELDS[section]:
                    field_total[field] += 1
                    field_correct[field] += (
                        str(left[field]).strip().casefold() == str(right[field]).strip().casefold()
                    )
        precision = matched_total / pred_total if pred_total else 0
        recall = matched_total / gold_total if gold_total else 0
        fields = sorted(field_total)
        metrics.append({
            "section": section_key,
            "industry": industry,
            "answers": len(results),
            "valid_answers": len(valid),
            "schema_valid_rate": len(valid) / len(results) if results else 0,
            "item_precision": precision,
            "item_recall": recall,
            "item_f1": 2 * precision * recall / (precision + recall) if precision + recall else 0,
            "item_count_mae": item_count_error / len(valid) if valid else "",
            "verbatim_evidence_rate": evidence_total / pred_total if pred_total else 0,
            "macro_field_accuracy": (
                sum(field_correct[field] / field_total[field] for field in fields) / len(fields)
                if fields else 0
            ),
        })
    return metrics


def safe_model_name(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", model)


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--base-url", default="http://localhost:11434/v1")
    parser.add_argument("--api-key-env", default="CDP_LLM_API_KEY")
    parser.add_argument("--answers", type=Path, default=DEFAULT_DATA / "cdp_validation_answers.jsonl.gz")
    parser.add_argument("--labels", type=Path, default=DEFAULT_DATA / "cdp_validation_detail_labels.jsonl.gz")
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, default=Path("data/outputs/cdp_text_clustering/cdp_detail_model_benchmark"))
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--examples", type=int, default=2)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--no-response-format", action="store_true")
    args = parser.parse_args()

    answers = read_jsonl(args.answers)
    taxonomy = load_taxonomy(args.contract)
    labels_list = read_jsonl(args.labels)
    labels = defaultdict(list)
    for row in labels_list:
        section = row.pop("section")
        validate_item(section, row)
        labels[str(row["Review ID"])].append(row)
    answer_ids = {str(row["review_id"]) for row in answers}
    if not set(labels).issubset(answer_ids):
        raise ValueError("Labels contain Review IDs absent from the answer file")
    missing_nonreduction = [
        row["review_id"] for row in answers
        if row["section"] != "reduction" and row["review_id"] not in labels
    ]
    if missing_nonreduction:
        raise ValueError(f"Non-reduction answers lack detail rows: {missing_nonreduction}")
    for answer in answers:
        answer["fold"] = fold_for_company(str(answer["company"]), args.folds)
    answers.sort(key=lambda row: (row["section"], row["industry"], row["source_field"], row["review_id"]))
    if args.limit:
        answers = answers[:args.limit]

    api_key = os.environ.get(args.api_key_env, "ollama")
    args.output.mkdir(parents=True, exist_ok=True)
    all_model_metrics = []
    for model in args.models:
        model_dir = args.output / safe_model_name(model)
        model_dir.mkdir(parents=True, exist_ok=True)
        experiment = {
            "model": model,
            "base_url": args.base_url,
            "answers_sha256": file_digest(args.answers),
            "labels_sha256": file_digest(args.labels),
            "contract_sha256": file_digest(args.contract),
            "objective": "item extraction and predefined taxonomy classification",
            "folds": args.folds,
            "examples": args.examples,
            "limit": args.limit,
            "response_format": not args.no_response_format,
        }
        experiment_path = model_dir / "experiment.json"
        if experiment_path.exists() and json.loads(experiment_path.read_text(encoding="utf-8")) != experiment:
            raise ValueError(
                f"Benchmark settings changed for {model}; choose a new --output directory"
            )
        experiment_path.write_text(json.dumps(experiment, indent=2), encoding="utf-8")
        checkpoint = model_dir / "answer_predictions.jsonl"
        existing = {}
        if checkpoint.exists():
            for row in read_jsonl(checkpoint):
                existing[row["review_id"]] = row
        results = []
        for number, answer in enumerate(answers, 1):
            if answer["review_id"] in existing:
                results.append(existing[answer["review_id"]])
                continue
            candidates = [row for row in answers if row["fold"] != answer["fold"]]
            examples = select_examples(answer, candidates, labels, args.examples)
            prompt = prompt_for(answer, examples, taxonomy)
            begun = time.perf_counter()
            result = {
                "model": model, "review_id": answer["review_id"],
                "section": answer["section"], "industry": answer["industry"],
                "source_text": answer["source_text"], "status": "error", "rows": [],
            }
            for attempt in range(args.retries + 1):
                try:
                    content, usage = chat_completion(
                        args.base_url, api_key, model, prompt, args.timeout,
                        not args.no_response_format,
                    )
                    parsed = parse_json(content)
                    result.update({
                        "status": "ok", "rows": complete_rows(answer, parsed["items"], taxonomy),
                        "raw_content": content, "usage": usage,
                    })
                    break
                except (ValueError, KeyError, json.JSONDecodeError, urllib.error.URLError) as error:
                    result["error"] = f"{type(error).__name__}: {error}"
                    if attempt < args.retries:
                        time.sleep(2 ** attempt)
            result["seconds"] = time.perf_counter() - begun
            with checkpoint.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n")
            results.append(result)
            print(f"{model}: {number}/{len(answers)} {answer['review_id']} {result['status']}", flush=True)

        metrics = evaluate(results, labels)
        for row in metrics:
            row["model"] = model
        all_model_metrics.extend(metrics)
        prediction_path = model_dir / "detail_predictions.jsonl.gz"
        with gzip.open(prediction_path, "wt", encoding="utf-8") as stream:
            for result in results:
                if result["status"] != "ok":
                    continue
                for row in result["rows"]:
                    stream.write(json.dumps({"section": result["section"], **row}, ensure_ascii=False) + "\n")
        export_csv(prediction_path, model_dir / "detail_csv")
        with (model_dir / "metrics.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(metrics[0]))
            writer.writeheader()
            writer.writerows(metrics)

    with (args.output / "model_comparison.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        fieldnames = ["model", "section", "industry", "answers", "valid_answers", "schema_valid_rate",
                      "item_precision", "item_recall", "item_f1", "item_count_mae",
                      "verbatim_evidence_rate", "macro_field_accuracy"]
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_model_metrics)


if __name__ == "__main__":
    main()

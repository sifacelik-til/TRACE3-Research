"""Checkpointed full-field encoding, sector models, and pending evidence coding."""

from __future__ import annotations

from src.cdp_text_clustering.encode_cdp_section_fields import EncoderCache

import csv
import gzip
import hashlib
import json
import logging
from collections import Counter, defaultdict
from pathlib import Path

import joblib
import numpy as np
from threadpoolctl import threadpool_limits

from src.cdp_extraction.cdp_section_fields import OUTPUT, digest, file_digest, read_fields, write_json, year_balanced
from src.cdp_text_clustering.cluster_cdp_fields_by_sector import fit_cohort, hybrid_features, descriptive_terms
from src.cdp_extraction.prepare_cdp_annotation_sample import excel_safe

LOGGER = logging.getLogger(__name__)
BLOCK_SIZE = 256


def evidence_candidates(field: dict, payload: dict, codebook: list[dict]) -> list[dict]:
    applicable = [i for i, code in enumerate(codebook) if field["role"] in code["roles"]]
    if not applicable:
        raise ValueError(f"No applicable codes for {field['role']}")
    insufficient = next(i for i in applicable if codebook[i]["code"] == "insufficient_information")
    if len(payload["spans"]) != len(payload["code_scores"]):
        raise ValueError("Evidence score rows do not match chunk spans")
    candidates = []
    position = 0
    for number, (span, scores) in enumerate(zip(payload["spans"], payload["code_scores"])):
        if len(scores) != len(codebook) or not np.isfinite(scores).all():
            raise ValueError("Invalid evidence score vector")
        start, end = span["start"], span["end"]
        if start != position or not start < end <= len(field["text"]):
            raise ValueError("Cached evidence spans are incomplete or overlapping")
        position = end
        ranked = sorted(applicable, key=lambda i: scores[i], reverse=True)
        chosen = [i for i in ranked if i != insufficient and scores[i] > scores[insufficient] + 0.02][:2]
        if not chosen:
            chosen = [insufficient]
        for i in chosen:
            code = codebook[i]
            candidates.append({
                **{name: field[name] for name in (
                    "field_id", "record_id", "dataset", "goal", "source_field", "role",
                    "year", "company_id", "sector_label",
                )},
                "code": code["code"], "code_definition": code["definition"],
                "chunk_number": number, "evidence_start": start, "evidence_end": end,
                "evidence_text": field["text"][start:end], "similarity": scores[i],
                "review_status": "unreviewed_ai_candidate", "reviewer_id": "",
                "interpretation": "Whole-chunk candidate; verify and narrow evidence. Similarity and the abstention margin are not calibrated accuracy.",
            })
    if position != len(field["text"]):
        raise ValueError("Evidence spans do not cover the complete field")
    return candidates


def encode_full(fields: list[dict], output: Path, key: str, callback) -> tuple[Path, dict[str, list[str]], int]:
    full = output / "full"
    blocks = full / "blocks"
    blocks.mkdir(parents=True, exist_ok=True)
    cache = EncoderCache(key, output)
    field_codes, total_candidates = {}, 0
    try:
        write_json(full / "codebook.json", {"status": "draft_for_human_review", "codes": cache.codebook})
        for start in range(0, len(fields), BLOCK_SIZE):
            rows = fields[start:start + BLOCK_SIZE]
            folder = blocks / f"{start:08d}"
            folder.mkdir(exist_ok=True)
            identity = digest(json.dumps([[row["field_id"], row["text_sha256"], row["role"]]
                                          for row in rows]))
            completed = folder / "complete.json"
            if completed.exists():
                state = json.loads(completed.read_text())
                if state["identity"] != identity or state["encoder"] != key:
                    raise ValueError("Full encoding checkpoint belongs to other fields or model")
                for name, expected in state["file_sha256"].items():
                    if file_digest(folder / name) != expected:
                        raise ValueError(f"Corrupt completed block: {folder}/{name}")
            else:
                cache.ensure(rows)
                vectors, audits, codes, count = [], [], {}, 0
                with gzip.open(folder / "coding_candidates.jsonl.gz", "wt", encoding="utf-8") as stream:
                    for row in rows:
                        cached = cache.get(row["text_sha256"])
                        if cached is None:
                            raise ValueError("Missing cached field after inference")
                        vector, _, payload = cached
                        vectors.append(vector)
                        proposals = evidence_candidates(row, payload, cache.codebook)
                        codes[row["field_id"]] = sorted({proposal["code"] for proposal in proposals})
                        for proposal in proposals:
                            stream.write(json.dumps(proposal, ensure_ascii=False, allow_nan=False) + "\n")
                        count += len(proposals)
                        audits.append({
                            "field_id": row["field_id"], "characters": len(row["text"]),
                            "covered_characters": sum(span["end"] - span["start"] for span in payload["spans"]),
                            "chunks": len(payload["spans"]),
                            "max_input_tokens": max(span["input_tokens"] for span in payload["spans"]),
                        })
                np.save(folder / "embeddings.npy", np.stack(vectors))
                write_json(folder / "field_codes.json", codes)
                with (folder / "coverage.csv").open("w", encoding="utf-8-sig", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=list(audits[0]))
                    writer.writeheader()
                    writer.writerows(audits)
                state = {
                    "identity": identity, "encoder": key, "fields": len(rows), "candidates": count,
                    "file_sha256": {name: file_digest(folder / name) for name in (
                        "embeddings.npy", "coding_candidates.jsonl.gz", "field_codes.json", "coverage.csv")},
                }
                write_json(completed, state)
            field_codes.update(json.loads((folder / "field_codes.json").read_text()))
            total_candidates += state["candidates"]
            write_json(full / "progress.json", {
                "stage": "full_encoding", "encoded_fields": min(start + BLOCK_SIZE, len(fields)),
                "total_fields": len(fields), "coding_candidates": total_candidates, "encoder": key,
            })
            if start % (BLOCK_SIZE * 8) == 0:
                callback()
            LOGGER.info("Full corpus %s: %s/%s fields", key, min(start + BLOCK_SIZE, len(fields)), len(fields))
        matrix_path = full / "field_embeddings.npy"
        matrix = np.lib.format.open_memmap(matrix_path, mode="w+", dtype="float32",
                                          shape=(len(fields), cache.dimension))
        for start in range(0, len(fields), BLOCK_SIZE):
            block = np.load(blocks / f"{start:08d}" / "embeddings.npy", allow_pickle=False)
            matrix[start:start + len(block)] = block
        matrix.flush()
        del matrix
        write_json(full / "progress.json", {
            "stage": "sector_clustering", "encoded_fields": len(fields), "total_fields": len(fields),
            "coding_candidates": total_candidates, "encoder": key,
        })
        callback()
        return matrix_path, field_codes, total_candidates
    finally:
        cache.close()


def fit_and_assign(fields: list[dict], matrix_path: Path, codes: dict, output: Path, callback) -> dict:
    full = output / "full"
    models = full / "models"
    models.mkdir(exist_ok=True)
    matrix = np.load(matrix_path, mmap_mode="r", allow_pickle=False)
    if len(matrix) != len(fields):
        raise ValueError("Deployment matrix is not aligned with the field registry")
    indices = {row["field_id"]: i for i, row in enumerate(fields)}
    embeddings = {row["field_id"]: matrix[i] for i, row in enumerate(fields)}
    cohorts = defaultdict(list)
    for row in fields:
        cohorts[(row["goal"], row["source_field"], row["sector_label"])].append(row)
    columns = [
        "field_id", "record_id", "dataset", "goal", "source_field", "year", "company_id",
        "company_name", "sector_label", "primary_sector_reported", "climate_relevance",
        "split", "assignment_status", "cluster_id", "cluster_label",
        "candidate_code_ids", "coding_status",
    ]
    status_counts, summaries, fit_audits, representatives = Counter(), [], [], []
    target = full / "cluster_assignments.csv.gz"
    pending = full / "cluster_assignments.pending.csv.gz"
    with gzip.open(pending, "wt", encoding="utf-8-sig", newline="") as stream, threadpool_limits(limits=2):
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for number, (cohort, rows) in enumerate(sorted(cohorts.items()), 1):
            goal, source_field, sector = cohort
            if any(row["sector_status"] != "reported" for row in rows):
                result = {"status": "unclustered_missing_or_unrecognized_sector", "k": 0}
            else:
                fit_rows = year_balanced([row for row in rows if row["split"] == "train"], 256)
                result = fit_cohort(fit_rows, embeddings, max_clusters=16, min_cluster_size=3, tolerance=0.02)
            names = {}
            cohort_id = digest("|".join(cohort))[:16]
            label_counts = Counter()
            if result["status"] == "clustered":
                model, vectorizer = result["model"], result["vectorizer"]
                for cluster in range(result["k"]):
                    terms = descriptive_terms(vectorizer, result["fit_rows"], model.labels_, cluster)
                    names[cluster] = sector + " | " + goal + " | " + ("; ".join(terms) or f"semantic subcluster {cluster}")
                    members = [row for row, label in zip(result["fit_rows"], model.labels_) if label == cluster]
                    for row in members[:3]:
                        representatives.append({
                            "cluster_id": f"{cohort_id}:{cluster:02d}", "field_id": row["field_id"],
                            "text": row["text"], "split": "train",
                            "note": "Training illustration, not an independently validated cluster label.",
                        })
                joblib.dump({
                    "cohort": cohort, "model": model, "vectorizer": vectorizer,
                    "fit_field_ids": [row["field_id"] for row in result["fit_rows"]], "names": names,
                }, models / f"{cohort_id}.joblib")
            for start in range(0, len(rows), BLOCK_SIZE):
                batch = rows[start:start + BLOCK_SIZE]
                labels = None
                if result["status"] == "clustered":
                    features, _ = hybrid_features(
                        matrix[[indices[row["field_id"]] for row in batch]],
                        [row["text"] for row in batch], result["vectorizer"])
                    labels = result["model"].predict(features)
                for i, row in enumerate(batch):
                    label = int(labels[i]) if labels is not None else None
                    state = result["status"]
                    status_counts[state] += 1
                    if label is not None:
                        label_counts[label] += 1
                    record = {
                        **{key: row[key] for key in columns if key in row},
                        "assignment_status": state, "cluster_id": f"{cohort_id}:{label:02d}" if label is not None else "",
                        "cluster_label": names[label] if label is not None else "",
                        "candidate_code_ids": json.dumps(codes[row["field_id"]]),
                        "coding_status": "pending_ai_suggestions",
                    }
                    writer.writerow({key: excel_safe(value) for key, value in record.items()})
            fit_audits.append({
                "goal": goal, "source_field": source_field, "sector_label": sector,
                "fields": len(rows), "fit_status": result["status"], "k": result.get("k", 0),
                "unique_fit_fields": len(result.get("fit_rows", [])), "maximum_fit_fields": 256,
                "train_silhouette": result.get("score"), "seed_ari": result.get("seed_ari"),
            })
            for label, count in sorted(label_counts.items()):
                summaries.append({
                    "goal": goal, "source_field": source_field, "sector_label": sector,
                    "cluster_id": f"{cohort_id}:{label:02d}", "cluster_label": names[label], "fields": count,
                })
            write_json(full / "progress.json", {
                "stage": "sector_clustering", "encoded_fields": len(fields), "total_fields": len(fields),
                "completed_cohorts": number, "total_cohorts": len(cohorts),
            })
            if number % 8 == 0:
                callback()
            LOGGER.info("Deployment sector models: %s/%s cohorts", number, len(cohorts))
    pending.replace(target)
    import pandas as pd
    pd.DataFrame(summaries).to_csv(full / "cluster_summary.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(fit_audits).to_csv(full / "cohort_metrics.csv", index=False)
    with gzip.open(full / "training_examples.jsonl.gz", "wt", encoding="utf-8") as stream:
        for row in representatives:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    if sum(status_counts.values()) != len(fields):
        raise ValueError("Full assignment coverage differs from source registry")
    return {
        "fields": len(fields), "clustered_fields": status_counts["clustered"],
        "assignment_status_counts": dict(status_counts), "clusters": len(summaries),
        "cohorts": len(cohorts),
    }


def deploy(output: Path = OUTPUT, progress_callback=lambda: None) -> dict:
    selection = json.loads((output / "selection.json").read_text())
    checks = json.loads((output / "verification_checks.json").read_text())
    if checks["selection_sha256"] != file_digest(output / "selection.json"):
        raise ValueError("Selected model has not passed the saved structural verification")
    data = json.loads((output / "data_manifest.json").read_text())
    if data["registry_sha256"] != file_digest(output / "fields.jsonl.gz"):
        raise ValueError("Full deployment registry differs from the audited input")
    fields = read_fields(output / "fields.jsonl.gz")
    full = output / "full"
    full.mkdir(exist_ok=True)
    fingerprint = {
        "registry_sha256": file_digest(output / "fields.jsonl.gz"),
        "selection_sha256": file_digest(output / "selection.json"),
        "encoder": selection["selected_encoder"], "block_size": BLOCK_SIZE, "fit_cap": 256,
    }
    config = full / "experiment.json"
    if config.exists() and json.loads(config.read_text()) != fingerprint:
        raise ValueError("Deployment settings changed; choose a new output directory")
    write_json(config, fingerprint)
    completed = full / "completion.json"
    if completed.exists():
        return json.loads(completed.read_text())
    matrix_path, codes, count = encode_full(fields, output, selection["selected_encoder"], progress_callback)
    summary = fit_and_assign(fields, matrix_path, codes, output, progress_callback)
    summary.update({
        "encoder": selection["selected_encoder"], "choice_status": selection["choice_status"],
        "coding_candidates": count, "accepted_human_codes_generated": False,
        "embedding_inference": "Selected encoder for every exact text; no surrogate classifier.",
        "evidence_files": "blocks/*/coding_candidates.jsonl.gz; exact offsets into fields.jsonl.gz",
    })
    write_json(completed, summary)
    write_json(full / "progress.json", {"stage": "complete", "encoded_fields": len(fields),
                                       "total_fields": len(fields)})
    return summary

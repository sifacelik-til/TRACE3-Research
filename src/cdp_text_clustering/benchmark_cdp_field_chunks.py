"""Field-separated complete-text benchmark and evidence-linked multi-label review.

Run with --per-dataset 100 for a bounded end-to-end development run.
The default uses the existing 600-response-per-dataset competition sample.
Models must already be downloaded by benchmark_cdp_encoders.py.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import torch
import joblib
import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from threadpoolctl import threadpool_limits

from src.cdp_text_clustering.benchmark_cdp_encoders import (
    DATASETS, DEFAULT_OUTPUT as COMPETITION, MODEL_CACHE, MODELS, PREFIXES,
    ROOT, SEEDS, sha_text, write_json,
)
from src.cdp_text_clustering.cdp_field_chunking import (
    aggregate_chunks, chunk_text, coding_candidates, token_count,
    validate_annotations, validate_codebook, verify_spans,
)
from src.cdp_extraction.prepare_cdp_annotation_sample import excel_safe

LOGGER = logging.getLogger(__name__)
CODEBOOK = Path(__file__).with_name("cdp_field_codebook.json")
OUTPUT = ROOT / "data" / "outputs" / "cdp_text_clustering" / "cdp_field_chunks_20261001"
LONG_SOURCE = (ROOT / "data" / "processed" / "cdp_2016_2024_climate_actions"
               / "climate_action_risk_opportunity_records_with_currency.csv.gz")
TEXT_SOURCE = ROOT / "data" / "outputs" / "cdp_text_clustering" / "cdp_2024_emissions_initiative_clusters"
LONG_FIELDS = {
    "initiative": [("initiative_comment_reported", "action")],
    "risk": [("reported_outcome_text", "risk"),
             ("response_strategy_reported", "action"),
             ("financial_impact_description", "financial")],
    "opportunity": [("reported_outcome_text", "opportunity"),
                    ("response_strategy_reported", "action"),
                    ("financial_impact_description", "financial")],
}
QUESTION_FIELDS = {
    "q7_55_2": ("col9", "action"), "q7_55_3": ("col2", "funding"),
    "q7_55_4": ("col1", "barrier"),
}


def normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def write_jsonl(path: Path, rows: list[dict]) -> None:
    pending = path.with_suffix(path.suffix + ".pending")
    with pending.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    pending.replace(path)


def load_fields(per_dataset: int, datasets: list[str]) -> pd.DataFrame:
    manifest = pd.read_csv(COMPETITION / "sample_manifest.csv", dtype=str, keep_default_na=False)
    chosen = []
    for dataset in datasets:
        for split, budget in (("train", int(per_dataset * 0.8)),
                              ("holdout", per_dataset - int(per_dataset * 0.8))):
            pool = manifest.loc[manifest.dataset.eq(dataset) & manifest.split.eq(split)]
            if pool.empty:
                raise ValueError(f"No source split for {dataset}/{split}")
            chosen.append(pool.sample(min(len(pool), budget), random_state=20261001))
    sample = pd.concat(chosen, ignore_index=True)
    source_rows: dict[tuple[str, str], dict] = {}
    selected_long = sample.loc[sample.dataset.str.startswith("longitudinal_")]
    wanted = set(selected_long.record_id)
    if wanted:
        for block in pd.read_csv(LONG_SOURCE, dtype=str, keep_default_na=False, chunksize=25000):
            for record in block.loc[block.record_id.isin(wanted)].to_dict("records"):
                key = ("longitudinal_" + record["record_type"], record["record_id"])
                if key in source_rows:
                    raise ValueError(f"Duplicate source record: {key}")
                source_rows[key] = record
    for dataset in set(sample.dataset) & set(QUESTION_FIELDS):
        source = pd.read_csv(TEXT_SOURCE / f"{dataset}_assignments.csv.gz",
                             dtype=str, keep_default_na=False)
        source["record_id"] = ("2024:" + source.question_number + ":"
                               + source.cdp_disclosing_org_number + ":" + source.row_order)
        ids = set(sample.loc[sample.dataset.eq(dataset)].record_id)
        for record in source.loc[source.record_id.isin(ids)].to_dict("records"):
            key = (dataset, record["record_id"])
            if key in source_rows:
                raise ValueError(f"Duplicate source record: {key}")
            source_rows[key] = record
    fields = []
    for row in sample.to_dict("records"):
        dataset, record_id = row["dataset"], row["record_id"]
        record = source_rows.get((dataset, record_id))
        if record is None:
            raise ValueError(f"Source record missing: {dataset}/{record_id}")
        definitions = (LONG_FIELDS[dataset.removeprefix("longitudinal_")]
                       if dataset.startswith("longitudinal_") else [QUESTION_FIELDS[dataset]])
        source_path = LONG_SOURCE if dataset.startswith("longitudinal_") else (
            TEXT_SOURCE / f"{dataset}_assignments.csv.gz"
        )
        company = record.get("cdp_account_number", record.get("cdp_disclosing_org_number"))
        if company != row["company_id"]:
            raise ValueError(f"Source company mismatch: {record_id}")
        metadata = {key: record[key] for key in (
            "year", "question_id", "question_number", "question_row", "row_order",
            "source_file", "source_sheet", "source_excel_row", "initiative_category_reported",
            "initiative_type_reported", "source_or_driver_reported", "source_or_driver_group",
            "financial_impact_kind", "cost_reported", "cost_text_reported",
            "reporting_currency_iso", "emissions_boundary_reported",
        ) if key in record}
        if dataset in {"q7_55_2", "q7_55_3"}:
            metadata["structured_selection_col1"] = record["col1"]
        for source_field, role in definitions:
            if source_field not in record:
                raise ValueError(f"Missing mapped source field: {source_field}")
            text = record[source_field]
            fields.append({
                **row, "field_id": f"{dataset}|{record_id}|{source_field}",
                "source_field": source_field, "role": role, "text": text,
                "source_path": str(source_path.relative_to(ROOT)),
                "source_metadata": metadata,
                "field_status": "available" if text.strip() else "blank_source_field",
            })
    result = pd.DataFrame(fields)
    if not result.field_id.is_unique:
        raise ValueError("Field identities are not unique")
    for dataset, rows in result.groupby("dataset"):
        train, test = rows.loc[rows.split.eq("train")], rows.loc[rows.split.eq("holdout")]
        if set(train.company_id) & set(test.company_id):
            raise ValueError(f"Company split leakage: {dataset}")
        if set(train.connected_group) & set(test.connected_group):
            raise ValueError(f"Connected-group split leakage: {dataset}")
    return result


def cached_encode(model, inputs: list[str], folder: Path, batch_size: int,
                  require_untruncated: bool, max_tokens: int) -> np.ndarray:
    if not inputs:
        raise ValueError("Cannot encode an empty input collection")
    folder.mkdir(parents=True, exist_ok=True)
    fingerprint = {
        "inputs_sha256": sha_text(inputs), "max_tokens": max_tokens,
        "require_untruncated": require_untruncated, "rows": len(inputs),
    }
    manifest = folder / "manifest.json"
    if manifest.exists() and json.loads(manifest.read_text()) != fingerprint:
        raise ValueError(f"Stale embedding cache: {folder}")
    if require_untruncated:
        for text in inputs:
            if token_count(model.tokenizer, text) > max_tokens:
                raise ValueError("A supposedly complete chunk would be truncated")
    write_json(manifest, fingerprint)
    blocks = []
    dimension = model.get_sentence_embedding_dimension()
    for start in range(0, len(inputs), 64):
        block_path = folder / f"{start:07d}.npy"
        stop = min(start + 64, len(inputs))
        if block_path.exists():
            block = np.load(block_path)
        else:
            block = model.encode(inputs[start:stop], prompt="", batch_size=batch_size,
                                 normalize_embeddings=True, convert_to_numpy=True,
                                 show_progress_bar=False)
            temporary = block_path.with_suffix(".pending")
            with temporary.open("wb") as stream:
                np.save(stream, block)
            temporary.replace(block_path)
            LOGGER.info("%s: %s/%s inputs encoded", folder.name, stop, len(inputs))
        if block.shape != (stop - start, dimension) or not np.isfinite(block).all():
            raise ValueError(f"Invalid embedding block: {block_path}")
        if not np.allclose(np.linalg.norm(block, axis=1), 1, atol=1e-4):
            raise ValueError(f"Unnormalized embedding block: {block_path}")
        blocks.append(block)
    return np.concatenate(blocks)


def compare(fields: pd.DataFrame, pooled: np.ndarray, truncated: np.ndarray,
            output: Path) -> None:
    metrics, comparisons, stability, statuses, assignments = [], [], [], [], []
    for (dataset, source_field), group in fields.groupby(["dataset", "source_field"], sort=False):
        train = group.index[group.split.eq("train")].to_numpy()
        test = group.index[group.split.eq("holdout")].to_numpy()
        train_text = {normalize(text) for text in fields.iloc[train].text}
        eligible_test = [i for i in test if normalize(fields.iloc[i].text) not in train_text]
        for index in test:
            statuses.append({
                "field_id": fields.iloc[index].field_id,
                "benchmark_status": ("eligible_holdout" if index in eligible_test
                                     else "excluded_exact_field_duplicate_of_training"),
            })
        test = np.asarray(eligible_test, dtype=int)
        k = 6 if dataset == "q7_55_4" else 12
        n_unique = len(train_text)
        if n_unique < k or len(test) < 3:
            LOGGER.warning("Skipping %s/%s: %s unique training fields, %s eligible holdouts",
                           dataset, source_field, n_unique, len(test))
            comparisons.append({
                "dataset": dataset, "source_field": source_field, "status": "insufficient_sample",
                "train": len(train), "holdout": len(test), "unique_train": n_unique,
            })
            continue
        predictions = {}
        for mode, vectors in (("complete_chunk_mean", pooled), ("truncated_prefix", truncated)):
            predictions[mode] = []
            for seed in SEEDS:
                model = KMeans(n_clusters=k, n_init=10, random_state=seed)
                model.fit(vectors[train])
                labels = model.predict(vectors[test])
                predictions[mode].append(labels)
                valid = 2 <= len(set(labels)) < len(labels)
                if not valid:
                    LOGGER.warning("Undefined silhouette: %s/%s/%s seed=%s",
                                   dataset, source_field, mode, seed)
                metrics.append({
                    "dataset": dataset, "source_field": source_field, "mode": mode, "seed": seed,
                    "train": len(train), "holdout": len(test), "holdout_topics": len(set(labels)),
                    "silhouette_complete_space": float(silhouette_score(
                        pooled[test], labels, metric="cosine")) if valid else None,
                    "silhouette_prefix_space": float(silhouette_score(
                        truncated[test], labels, metric="cosine")) if valid else None,
                    "metric_status": "defined" if valid else "undefined_cluster_count",
                })
                if seed == 42:
                    joblib.dump(model, output / f"{dataset}_{source_field}_{mode}.joblib")
                    labels_all = model.predict(vectors[group.index])
                    for index, label in zip(group.index, labels_all):
                        assignments.append({
                            "field_id": fields.iloc[index].field_id,
                            "dataset": dataset, "record_id": fields.iloc[index].record_id,
                            "source_field": source_field, "mode": mode, "cluster": int(label),
                            "split": fields.iloc[index].split,
                        })
            from itertools import combinations
            aris = [adjusted_rand_score(first, second)
                    for first, second in combinations(predictions[mode], 2)]
            stability.append({"dataset": dataset, "source_field": source_field, "mode": mode,
                              "seed_ari_mean": float(np.mean(aris))})
        comparisons.append({
            "dataset": dataset, "source_field": source_field, "status": "compared",
            "train": len(train), "holdout": len(test), "unique_train": n_unique,
            "complete_vs_prefix_ari": float(np.mean([
                adjusted_rand_score(first, second) for first, second in zip(
                    predictions["complete_chunk_mean"], predictions["truncated_prefix"]
                )
            ])),
        })
    pd.DataFrame(metrics).to_csv(output / "benchmark_metrics.csv", index=False)
    pd.DataFrame(stability).to_csv(output / "seed_stability.csv", index=False)
    pd.DataFrame(comparisons).to_csv(output / "paired_comparison.csv", index=False)
    pd.DataFrame(statuses).to_csv(output / "holdout_eligibility.csv", index=False)
    pd.DataFrame(assignments).to_csv(output / "cluster_assignments.csv", index=False)


def run(args) -> None:
    codebook = json.loads(CODEBOOK.read_text(encoding="utf-8"))
    validate_codebook(codebook)
    fields = load_fields(args.per_dataset, args.datasets)
    revision_info = json.loads((COMPETITION / f"{args.model}_revision.json").read_text())
    if revision_info["repository"] != MODELS[args.model]:
        raise ValueError("Model repository/revision mismatch")
    revision = revision_info["revision"]
    model_path = MODEL_CACHE / args.model / revision
    prefix = PREFIXES[args.model]
    fingerprint = {
        "pipeline_version": 1, "model": MODELS[args.model], "revision": revision,
        "prefix": prefix, "max_tokens": args.max_tokens,
        "source_sha256": sha_text(fields.to_json(orient="records", force_ascii=False).splitlines()),
        "codebook_sha256": sha_text([json.dumps(codebook, sort_keys=True)]),
        "per_dataset": args.per_dataset, "datasets": args.datasets,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    config = args.output / "experiment.json"
    if config.exists() and json.loads(config.read_text())["fingerprint"] != fingerprint:
        raise ValueError("Output contains a different experiment; choose a new output path")
    import importlib.metadata
    write_json(config, {
        "fingerprint": fingerprint,
        "packages": {name: importlib.metadata.version(name) for name in
                     ("torch", "transformers", "sentence-transformers", "scikit-learn", "numpy", "pandas")},
        "aggregation": "Normalized content-token-weighted mean of nonoverlapping chunks per response/source field.",
        "offsets": "Zero-based Python Unicode character indices; end exclusive, relative to exact extracted field.",
        "limitations": [
            "Field separation preserves extracted fields, not necessarily individual raw cells.",
            "Legacy strategy fields can contain cost explanations; financial descriptions can combine source cells.",
            "Sentence boundaries are heuristic; token/character fallback guarantees coverage, not linguistic segmentation.",
            "The truncated comparator uses the same separated field, not the old concatenated narrative.",
            "Field-identical training/holdout text is excluded from holdout diagnostics and recorded.",
            "Mean pooling can blur multiple themes. Candidate labels are not validated measurements.",
            "No human accuracy, causal, temporal, or full-corpus representativeness claim.",
        ],
    })
    write_jsonl(args.output / "fields.jsonl", fields.to_dict("records"))
    write_json(args.output / "codebook.json", {"status": "draft_for_human_review", "codes": codebook})
    available = fields.loc[fields.field_status.eq("available")].reset_index(drop=True)
    if available.empty:
        raise ValueError("No nonblank source fields available")
    model = SentenceTransformer(str(model_path), device="cpu", local_files_only=True,
                                trust_remote_code=False, model_kwargs={"torch_dtype": torch.float32})
    model.max_seq_length = args.max_tokens
    if args.model == "qwen3":
        model.tokenizer.padding_side = "left"
    chunks, coverage = [], []
    for row in available.to_dict("records"):
        spans = chunk_text(row["text"], model.tokenizer, args.max_tokens, prefix)
        for number, span in enumerate(spans):
            chunks.append({**span, "field_id": row["field_id"],
                           "chunk_id": f"{row['field_id']}|{number:04d}"})
        verify_spans(row["text"], spans, args.max_tokens)
        original_tokens = token_count(model.tokenizer, row["text"], prefix)
        coverage.append({
            "field_id": row["field_id"], "dataset": row["dataset"],
            "source_field": row["source_field"], "source_characters": len(row["text"]),
            "covered_characters": sum(span["end"] - span["start"] for span in spans),
            "chunks": len(spans), "original_input_tokens": original_tokens,
            "prefix_would_truncate": original_tokens > args.max_tokens,
            "max_chunk_input_tokens": max(span["input_tokens"] for span in spans),
        })
    chunk_frame = pd.DataFrame(chunks)
    write_jsonl(args.output / "chunks.jsonl", chunks)
    pd.DataFrame(coverage).to_csv(args.output / "coverage_audit.csv", index=False)
    fields[["field_id", "dataset", "record_id", "source_field", "field_status"]].to_csv(
        args.output / "field_availability.csv", index=False)
    LOGGER.info("%s responses, %s available fields, %s lossless chunks",
                len(fields[["dataset", "record_id"]].drop_duplicates()), len(available), len(chunks))
    vectors = cached_encode(model, [prefix + row["text"] for row in chunks],
                            args.output / "chunk_embeddings", args.batch_size, True, args.max_tokens)
    pooled = []
    for field_id in available.field_id:
        positions = np.flatnonzero(chunk_frame.field_id.eq(field_id))
        pooled.append(aggregate_chunks(vectors[positions],
                                      chunk_frame.iloc[positions].weight.to_numpy()))
    pooled = np.stack(pooled)
    np.save(args.output / "response_field_embeddings.npy", pooled)
    available[["field_id", "dataset", "record_id", "source_field"]].to_csv(
        args.output / "response_field_embedding_manifest.csv", index=False)
    truncated = cached_encode(model, (prefix + available.text).tolist(),
                             args.output / "prefix_embeddings", args.batch_size, False, args.max_tokens)
    with threadpool_limits(limits=2):
        compare(available, pooled, truncated, args.output)
    descriptions = [prefix + code["definition"] for code in codebook]
    code_vectors = cached_encode(model, descriptions, args.output / "code_embeddings",
                                 args.batch_size, True, args.max_tokens)
    proposals = coding_candidates(available, chunk_frame, vectors, codebook, code_vectors)
    write_jsonl(args.output / "coding_candidates.jsonl", proposals)
    template = args.output / "coding_template.csv"
    if not template.exists():
        form = available[["dataset", "record_id", "field_id", "source_field"]].copy()
        for name in ("code", "evidence_start", "evidence_end", "evidence_text",
                     "reviewer_id", "review_date", "notes"):
            form[name] = ""
        form["review_status"] = "pending"
        form.to_csv(template, index=False, encoding="utf-8-sig")
    # Formula-safe display export; fields.jsonl remains the exact offset reference.
    display = available[["dataset", "record_id", "field_id", "source_field", "text"]].copy()
    display["text"] = display.text.map(excel_safe)
    display.to_csv(args.output / "review_fields.csv", index=False, encoding="utf-8-sig")
    write_json(args.output / "completion.json", {
        "available_fields": len(available), "blank_fields": len(fields) - len(available),
        "chunks": len(chunks), "candidate_codes": len(proposals),
        "all_source_characters_covered": True, "accepted_human_codes_generated": False,
    })
    LOGGER.info("Completed field-aware benchmark and review exports: %s", args.output)


def validate_review(output: Path, annotations: Path) -> None:
    fields = pd.read_json(output / "fields.jsonl", lines=True)
    codebook = json.loads((output / "codebook.json").read_text())["codes"]
    if annotations.suffix.lower() == ".csv":
        with annotations.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
    else:
        rows = [json.loads(line) for line in annotations.read_text(encoding="utf-8").splitlines()
                if line.strip()]
    accepted, counts = validate_annotations(rows, fields, codebook)
    write_jsonl(output / "validated_evidence_codes.jsonl", accepted)
    # Preserve coders independently: no implicit adjudication of disagreements.
    grouped: dict[tuple[str, str, str], dict] = {}
    for row in accepted:
        key = (row["dataset"], row["record_id"], row["reviewer_id"])
        grouped.setdefault(key, {"dataset": key[0], "record_id": key[1],
                                 "reviewer_id": key[2], "codes": set(), "evidence": []})
        grouped[key]["codes"].add(row["code"])
        grouped[key]["evidence"].append({
            name: row[name] for name in
            ("field_id", "code", "evidence_start", "evidence_end", "evidence_text")
        })
    result = [{**row, "codes": sorted(row["codes"])} for row in grouped.values()]
    write_jsonl(output / "response_multilabel_codes.jsonl", result)
    write_json(output / "coding_validation.json", counts)
    LOGGER.info("Coding validation: %s", counts)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["benchmark", "validate"], default="benchmark")
    parser.add_argument("--model", choices=list(MODELS), default="minilm")
    parser.add_argument("--datasets", nargs="+", choices=list(DATASETS), default=list(DATASETS))
    parser.add_argument("--per-dataset", type=int, default=600)
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--annotations", type=Path)
    args = parser.parse_args()
    if args.stage == "validate":
        if args.annotations is None:
            parser.error("--annotations is required for validation")
        validate_review(args.output, args.annotations)
    else:
        if args.per_dataset < 40 or not 96 <= args.max_tokens <= 512 or args.batch_size < 1:
            parser.error("Require per-dataset >=40, 96<=max-tokens<=512, batch-size>=1")
        torch.set_num_threads(3)
        run(args)

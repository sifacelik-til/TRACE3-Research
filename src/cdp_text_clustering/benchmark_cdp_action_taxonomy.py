"""Cross-sector action-span embedding benchmark for the validated CDP sample.

Design implemented here:

* one clustering cohort per disclosure goal, pooled across industries;
* one row per validated item/evidence span, allowing multiple labels per answer;
* company-disjoint 60/20/20 train, selection, and verification splits;
* cleaned clustering text with verbatim evidence retained separately;
* semantic weights 0.25, 0.50, 0.75, and 1.00, selected without verification;
* spherical k-means with cosine geometry;
* at least five evaluation observations in every predicted cluster;
* separate coverage and conditional silhouette measures;
* human-label diagnostics and a second-coder validation sample;
* company-year multi-label action output for a later transition test.

The script does not treat silhouette as evidence that a category is a feasible
MDP action.  Human validation and the separate transition test remain required.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import inspect
import json
import logging
import math
import os
import platform
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "processed" / "cdp_section_datasets"
VALIDATION_WORKBOOK = DATA / "cdp_classification_all_details.xlsx"
DEFAULT_OUTPUT = ROOT / "data" / "outputs" / "cdp_text_clustering" / "cdp_action_taxonomy_benchmark_20261002"
LEGACY_MODELS = ROOT / "data" / "models" / "cdp_encoder_competition"
MODEL_CACHE = ROOT / "data" / "models" / "cdp_action_taxonomy"
LOGGER = logging.getLogger(__name__)

MODEL_SPECS = {
    "minilm": {
        "model_id": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "legacy_key": "minilm", "prompt": "", "trust_remote_code": False,
    },
    "e5_base": {
        "model_id": "intfloat/multilingual-e5-base",
        "legacy_key": "e5", "prompt": "query: ", "trust_remote_code": False,
    },
    "bge_m3": {
        "model_id": "BAAI/bge-m3",
        "legacy_key": "bge_m3", "prompt": "", "trust_remote_code": False,
    },
    "qwen3_06b": {
        "model_id": "Qwen/Qwen3-Embedding-0.6B",
        "legacy_key": "qwen3",
        "prompt": "Instruct: Group corporate climate disclosures by operational action.\nQuery: ",
        "trust_remote_code": False,
    },
    "gte_multilingual": {
        "model_id": "Alibaba-NLP/gte-multilingual-base",
        "prompt": "", "trust_remote_code": True,
    },
    "jina_v3": {
        "model_id": "jinaai/jina-embeddings-v3",
        "prompt": "", "task": "separation", "trust_remote_code": True,
    },
    "e5_large_instruct": {
        "model_id": "intfloat/multilingual-e5-large-instruct",
        "prompt": (
            "Instruct: Identify the operational climate action, engagement mechanism, "
            "risk, or opportunity described in this corporate disclosure.\nQuery: "
        ),
        "trust_remote_code": False,
    },
    # Optional scale comparison; intentionally excluded from DEFAULT_MODELS.
    "qwen3_4b": {
        "model_id": "Qwen/Qwen3-Embedding-4B",
        "prompt": "Instruct: Group corporate climate disclosures by operational action.\nQuery: ",
        "trust_remote_code": False,
    },
}
DEFAULT_MODELS = [
    "minilm", "e5_base", "bge_m3", "qwen3_06b",
    "gte_multilingual", "jina_v3", "e5_large_instruct",
]
GOALS = ("reduction", "engagement", "risk", "opportunity")
SEMANTIC_WEIGHTS = (0.25, 0.50, 0.75, 1.00)
SPLIT_SEED = "cdp-action-taxonomy-20261002"
SPLIT_LIMITS = ((60, "train"), (80, "selection"), (100, "verification"))

# Loaded only for encode/evaluate/verify so data preparation can run with the
# standard library and validate the workbook-derived sample independently.
joblib = np = pd = TfidfVectorizer = None
adjusted_rand_score = normalized_mutual_info_score = silhouette_score = normalize = None
precision_recall_fscore_support = None
threadpool_limits = None


def load_analysis_dependencies() -> None:
    global joblib, np, pd, TfidfVectorizer
    global adjusted_rand_score, normalized_mutual_info_score, silhouette_score, normalize
    global precision_recall_fscore_support
    global threadpool_limits
    if np is not None:
        return
    import joblib as _joblib
    import numpy as _np
    import pandas as _pd
    from sklearn.feature_extraction.text import TfidfVectorizer as _TfidfVectorizer
    from sklearn.metrics import (
        adjusted_rand_score as _adjusted_rand_score,
        normalized_mutual_info_score as _normalized_mutual_info_score,
        precision_recall_fscore_support as _precision_recall_fscore_support,
        silhouette_score as _silhouette_score,
    )
    from sklearn.preprocessing import normalize as _normalize
    from threadpoolctl import threadpool_limits as _threadpool_limits
    joblib, np, pd, TfidfVectorizer = _joblib, _np, _pd, _TfidfVectorizer
    adjusted_rand_score = _adjusted_rand_score
    normalized_mutual_info_score = _normalized_mutual_info_score
    precision_recall_fscore_support = _precision_recall_fscore_support
    silhouette_score, normalize = _silhouette_score, _normalize
    threadpool_limits = _threadpool_limits


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def file_digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".pending")
    pending.write_text(
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
        encoding="utf-8",
    )
    pending.replace(path)


def read_jsonl(path: Path) -> list[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def split_for(company: str) -> str:
    bucket = int(digest(SPLIT_SEED + "|" + company.casefold())[:12], 16) % 100
    return next(name for limit, name in SPLIT_LIMITS if bucket < limit)


QUESTIONNAIRE_PATTERNS = (
    r"\bCDP\b", r"\bduring the reporting (?:year|period)\b",
    r"\bin the reporting (?:year|period)\b", r"\bplease (?:describe|explain|provide)\b",
    r"\bthis (?:question|response|disclosure)\b", r"https?://\S+", r"\b(?:19|20)\d{2}\b",
)


def clean_clustering_text(text: str, company: str) -> str:
    result = text
    if company.strip():
        result = re.sub(re.escape(company.strip()), " ", result, flags=re.IGNORECASE)
    for pattern in QUESTIONNAIRE_PATTERNS:
        result = re.sub(pattern, " ", result, flags=re.IGNORECASE)
    result = re.sub(r"\s+", " ", result).strip(" -–—:;,.")
    return result or text.strip()


def evidence_context(source: str, evidence: str, radius: int = 220) -> str:
    position = source.find(evidence)
    if position < 0:
        raise ValueError("Evidence excerpt is not verbatim in the source answer")
    start = max(0, position - radius)
    end = min(len(source), position + len(evidence) + radius)
    return source[start:end]


def label_fields(section: str, item: dict) -> tuple[str, str, str]:
    if section == "reduction":
        return str(item["Action class"]), str(item["Action family"]), str(item["Implementation stage"])
    if section == "engagement":
        return str(item["Item class"]), str(item["Engagement mechanism or policy"]), str(item["Intensity or stage"])
    if section == "risk":
        return str(item["Item class"]), str(item["Risk type"]), str(item["Time horizon"])
    if section == "opportunity":
        return str(item["Item class"]), str(item["Opportunity type"]), str(item["Time horizon"])
    raise ValueError(section)


def prepare(output: Path, answers_path: Path, labels_path: Path,
            workbook_path: Path = VALIDATION_WORKBOOK) -> list[dict]:
    output.mkdir(parents=True, exist_ok=True)
    target = output / "span_records.jsonl.gz"
    fingerprint = {
        "version": 1,
        "answers_sha256": file_digest(answers_path),
        "labels_sha256": file_digest(labels_path),
        "validation_workbook": str(workbook_path.resolve()),
        "validation_workbook_sha256": file_digest(workbook_path),
        "split_seed": SPLIT_SEED,
        "unit": "validated item-level evidence span with local source context",
        "taxonomy": "one common taxonomy per disclosure goal, pooled across industries",
    }
    manifest = output / "data_manifest.json"
    if manifest.exists():
        state = json.loads(manifest.read_text(encoding="utf-8"))
        manifest_changed = False
        old_fingerprint = state["fingerprint"]
        legacy_fingerprint = {
            key: value for key, value in fingerprint.items()
            if key not in {"validation_workbook", "validation_workbook_sha256"}
        }
        if old_fingerprint not in (fingerprint, legacy_fingerprint) or state["records_sha256"] != file_digest(target):
            raise ValueError("Prepared data changed; select a new output directory")
        if old_fingerprint == legacy_fingerprint:
            state["fingerprint"] = fingerprint
            manifest_changed = True
        if "source_answers" not in state:
            source_answers = read_jsonl(answers_path)
            state["source_answers"] = len(source_answers)
            state["answers_with_validated_items"] = state.pop("answers")
            manifest_changed = True
        if manifest_changed:
            write_json(manifest, state)
        return read_jsonl(target)

    answer_rows = read_jsonl(answers_path)
    answers = {row["review_id"]: row for row in answer_rows}
    labels = read_jsonl(labels_path)
    records = []
    for item in labels:
        section = item.pop("section")
        answer = answers[str(item["Review ID"])]
        evidence = str(item["Evidence excerpt"])
        context = evidence_context(str(answer["source_text"]), evidence)
        fine, coarse, stage = label_fields(section, item)
        records.append({
            "item_id": item["Item ID"], "review_id": item["Review ID"],
            "goal": section, "industry": item["Industry"], "company": item["Company"],
            "year": int(item["Year"]), "source_field": item["Source field"],
            "field_id": answer["field_id"], "split": split_for(str(item["Company"])),
            "original_evidence": evidence, "source_context": context,
            "clustering_text": clean_clustering_text(context, str(item["Company"])),
            "fine_human_label": fine, "coarse_human_label": coarse,
            "implementation_or_horizon": stage, "item_role": item.get("Item role", ""),
            "eligibility": item.get(
                {"reduction": "Counts as action", "engagement": "In-scope engagement item?",
                 "risk": "In-scope risk item?", "opportunity": "In-scope opportunity item?"}[section], ""),
        })

    counts = Counter((row["goal"], row["split"]) for row in records)
    for goal in GOALS:
        for split in ("selection", "verification"):
            if counts[(goal, split)] < 30:
                raise ValueError(f"{goal}/{split} has {counts[(goal, split)]} spans; require at least 30")
    companies = defaultdict(set)
    for row in records:
        companies[row["split"]].add(row["company"].casefold())
    if companies["train"] & companies["selection"] or companies["train"] & companies["verification"] or companies["selection"] & companies["verification"]:
        raise ValueError("Company leakage across splits")

    with gzip.open(target.with_suffix(".pending.gz"), "wt", encoding="utf-8") as stream:
        for row in records:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    target.with_suffix(".pending.gz").replace(target)
    write_json(manifest, {
        "fingerprint": fingerprint, "records_sha256": file_digest(target),
        "records": len(records), "source_answers": len(answer_rows),
        "answers_with_validated_items": len({row["review_id"] for row in records}),
        "companies": len({row["company"].casefold() for row in records}),
        "goal_split_counts": [
            {"goal": goal, "split": split, "items": counts[(goal, split)]}
            for goal in GOALS for split in ("train", "selection", "verification")
        ],
    })
    return records


def legacy_model_path(spec: dict) -> Path | None:
    key = spec.get("legacy_key")
    if not key:
        return None
    folder = LEGACY_MODELS / key
    candidates = [path for path in folder.iterdir() if path.is_dir() and (path / "config.json").exists()] if folder.exists() else []
    return candidates[0] if len(candidates) == 1 else None


def resolve_model(key: str, spec: dict, offline: bool) -> tuple[Path, str]:
    legacy = legacy_model_path(spec)
    if legacy is not None:
        return legacy, legacy.name
    cached_root = MODEL_CACHE / "huggingface" / ("models--" + spec["model_id"].replace("/", "--")) / "snapshots"
    cached = [path for path in cached_root.iterdir() if path.is_dir() and (path / "config.json").exists()] if cached_root.exists() else []
    if len(cached) == 1:
        return cached[0], cached[0].name
    from huggingface_hub import snapshot_download
    local_model = MODEL_CACHE / "snapshots" / key
    path = Path(snapshot_download(
        repo_id=spec["model_id"], local_dir=local_model,
        local_dir_use_symlinks=False, local_files_only=offline,
    ))
    return path, path.name


def encode_model(key: str, records: list[dict], output: Path, *, batch_size: int,
                 device: str, offline: bool) -> None:
    import torch
    from sentence_transformers import SentenceTransformer

    spec = MODEL_SPECS[key]
    folder = output / "encoders" / key
    folder.mkdir(parents=True, exist_ok=True)
    matrix_path = folder / "embeddings.npy"
    manifest = folder / "manifest.json"
    sample_hash = file_digest(output / "span_records.jsonl.gz")
    if manifest.exists():
        state = json.loads(manifest.read_text(encoding="utf-8"))
        matrix = np.load(matrix_path, allow_pickle=False)
        if state["sample_sha256"] != sample_hash or len(matrix) != len(records) or not np.isfinite(matrix).all():
            raise ValueError(f"Stale or invalid encoder output: {key}")
        LOGGER.info("%s already encoded", key)
        return

    model_path, revision = resolve_model(key, spec, offline)
    started = time.perf_counter()
    model = SentenceTransformer(
        str(model_path), device=device, local_files_only=offline,
        trust_remote_code=spec.get("trust_remote_code", False),
        model_kwargs={"torch_dtype": torch.float32} if device == "cpu" else {},
    )
    texts = [spec.get("prompt", "") + row["clustering_text"] for row in records]
    encode_kwargs = {
        "batch_size": batch_size, "normalize_embeddings": True,
        "convert_to_numpy": True, "show_progress_bar": True,
    }
    task_applied = "none"
    if spec.get("task"):
        signature = inspect.signature(model.encode).parameters
        module_kwargs = getattr(model, "module_kwargs", None) or {}
        forwards_task = (
            any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.values())
            and any("task" in keywords for keywords in module_kwargs.values())
        )
        if "task" in signature or forwards_task:
            encode_kwargs["task"] = spec["task"]
            task_applied = spec["task"]
        elif "prompt_name" in signature and spec["task"] in getattr(model, "prompts", {}):
            encode_kwargs["prompt_name"] = spec["task"]
            task_applied = "prompt_name:" + spec["task"]
        else:
            raise RuntimeError(
                f"{key} requires the '{spec['task']}' embedding task, but the installed "
                "sentence-transformers version cannot pass it. Upgrade sentence-transformers."
            )
    vectors = model.encode(texts, **encode_kwargs).astype("float32")
    if not np.isfinite(vectors).all() or not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-4):
        raise ValueError(f"{key} returned invalid or unnormalised vectors")
    np.save(matrix_path, vectors)
    write_json(manifest, {
        "key": key, "model_id": spec["model_id"], "resolved_revision": revision,
        "sample_sha256": sample_hash, "records": len(records), "dimension": vectors.shape[1],
        "prompt": spec.get("prompt", ""), "task": task_applied,
        "seconds": time.perf_counter() - started, "device": device,
        "python": platform.python_version(),
    })


class SphericalKMeans:
    def __init__(self, n_clusters: int, *, seeds=(42, 43, 44, 45, 46), max_iter=200, tol=1e-6):
        self.n_clusters, self.seeds = n_clusters, tuple(seeds)
        self.max_iter, self.tol = max_iter, tol
        self.cluster_centers_ = self.labels_ = None
        self.objective_ = None

    @staticmethod
    def _initialise(matrix: np.ndarray, k: int, seed: int) -> np.ndarray:
        rng = np.random.default_rng(seed)
        centers = [int(rng.integers(len(matrix)))]
        closest = 1 - matrix @ matrix[centers[0]]
        for _ in range(1, k):
            probabilities = np.maximum(closest, 0) ** 2
            if probabilities.sum() == 0:
                candidates = [i for i in range(len(matrix)) if i not in centers]
                centers.append(candidates[0])
            else:
                centers.append(int(rng.choice(len(matrix), p=probabilities / probabilities.sum())))
            closest = np.minimum(closest, 1 - matrix @ matrix[centers[-1]])
        return matrix[centers].copy()

    def fit(self, matrix: np.ndarray):
        matrix = normalize(np.asarray(matrix, dtype="float32"), norm="l2")
        best = None
        for seed in self.seeds:
            centers = self._initialise(matrix, self.n_clusters, seed)
            labels = None
            for _ in range(self.max_iter):
                similarities = matrix @ centers.T
                new_labels = similarities.argmax(axis=1)
                if labels is not None and np.array_equal(labels, new_labels):
                    break
                labels = new_labels
                new_centers = []
                for cluster in range(self.n_clusters):
                    members = matrix[labels == cluster]
                    if not len(members):
                        replacement = int(np.argmin(similarities.max(axis=1)))
                        center = matrix[replacement]
                    else:
                        center = members.mean(axis=0)
                    norm = np.linalg.norm(center)
                    new_centers.append(center / norm if norm else center)
                new_centers = np.asarray(new_centers, dtype="float32")
                shift = np.max(1 - np.sum(centers * new_centers, axis=1))
                centers = new_centers
                if shift < self.tol:
                    break
            labels = (matrix @ centers.T).argmax(axis=1)
            objective = float(np.sum(1 - (matrix @ centers.T).max(axis=1)))
            if best is None or objective < best[0]:
                best = objective, centers.copy(), labels.copy()
        self.objective_, self.cluster_centers_, self.labels_ = best
        return self

    def predict(self, matrix: np.ndarray) -> np.ndarray:
        return (normalize(np.asarray(matrix, dtype="float32"), norm="l2") @ self.cluster_centers_.T).argmax(axis=1)


def hybrid_features(semantic: np.ndarray, lexical: np.ndarray, weight: float) -> np.ndarray:
    semantic = normalize(semantic, norm="l2")
    if weight == 1:
        return np.asarray(semantic, dtype="float32")
    lexical = normalize(lexical, norm="l2")
    result = np.hstack((math.sqrt(weight) * semantic, math.sqrt(1 - weight) * lexical))
    return np.asarray(normalize(result, norm="l2"), dtype="float32")


def majority_cluster_labels(labels: np.ndarray, rows: list[dict]) -> dict[int, str]:
    """Map clusters to workbook labels using training observations only."""
    mapping = {}
    for cluster in sorted(set(int(value) for value in labels)):
        values = [
            row["coarse_human_label"] for row, label in zip(rows, labels)
            if int(label) == cluster
        ]
        mapping[cluster] = Counter(values).most_common(1)[0][0]
    return mapping


def partition_metrics(features: np.ndarray, labels: np.ndarray, rows: list[dict], k: int,
                      minimum_per_cluster: int, cluster_label_map: dict[int, str]) -> dict:
    counts = np.bincount(labels, minlength=k)
    supported = bool(len(labels) >= 3 and np.all(counts >= minimum_per_cluster))
    defined = supported and 2 <= len(set(labels)) < len(labels)
    result = {
        "status": "defined" if defined else "unsupported_cluster_counts",
        "minimum_cluster_count": int(counts.min()) if len(counts) else 0,
        "silhouette": float(silhouette_score(features, labels, metric="cosine")) if defined else None,
    }
    if not defined:
        return result
    fine = [row["fine_human_label"] for row in rows]
    coarse = [row["coarse_human_label"] for row in rows]
    stage = [row["implementation_or_horizon"] for row in rows]

    def purity(values):
        return sum(Counter(value for value, label in zip(values, labels) if label == cluster).most_common(1)[0][1]
                   for cluster in range(k)) / len(values)

    result.update({
        "fine_label_purity": purity(fine),
        "fine_label_ari": float(adjusted_rand_score(fine, labels)),
        "fine_label_nmi": float(normalized_mutual_info_score(fine, labels)),
        "coarse_label_purity": purity(coarse),
        "coarse_label_ari": float(adjusted_rand_score(coarse, labels)),
        "coarse_label_nmi": float(normalized_mutual_info_score(coarse, labels)),
        "implementation_or_horizon_purity": purity(stage),
    })
    predicted_coarse = [cluster_label_map[int(label)] for label in labels]
    precision, recall, f1, _ = precision_recall_fscore_support(
        coarse, predicted_coarse, average="macro", zero_division=0,
    )
    result.update({
        "coarse_label_precision": float(precision),
        "coarse_label_recall": float(recall),
        "coarse_label_f1": float(f1),
    })
    return result


def evaluate(models: list[str], records: list[dict], output: Path, *, max_clusters: int,
             minimum_cluster_size: int, minimum_eval_per_cluster: int,
             minimum_coverage: float) -> dict:
    design = {
        "sample_sha256": file_digest(output / "span_records.jsonl.gz"),
        "cohorts": list(GOALS), "pool_sectors": True,
        "semantic_weights": list(SEMANTIC_WEIGHTS), "max_clusters": max_clusters,
        "minimum_training_cluster_size": minimum_cluster_size,
        "minimum_evaluation_items_per_predicted_cluster": minimum_eval_per_cluster,
        "minimum_encoder_coverage": minimum_coverage,
        "primary_quality": "mean cosine silhouette conditional on a supported partition",
        "coverage": "share of disclosure goals with supported partitions",
        "algorithm": "spherical k-means",
        "lexical_features": "training-fitted character 3-5 gram TF-IDF after questionnaire cleaning",
        "selection": "minimum coverage first, then conditional silhouette; verification remains locked",
    }
    design_path = output / "benchmark_design.json"
    if design_path.exists():
        existing_design = json.loads(design_path.read_text(encoding="utf-8"))
        # Older smoke runs stored the requested model subset as if it were a
        # design parameter. Models may be added incrementally without changing
        # the sample, splits, tuning grid, or selection rule.
        existing_design.pop("models", None)
        if existing_design != design:
            raise ValueError("Benchmark design changed; select a new output directory")
    write_json(design_path, design)
    write_json(output / "requested_models.json", {"models": models})

    searches, metrics, assignments = [], [], []
    saved_models = output / "models"
    saved_models.mkdir(exist_ok=True)
    by_goal = {goal: [i for i, row in enumerate(records) if row["goal"] == goal] for goal in GOALS}
    with threadpool_limits(limits=2):
        for model_key in models:
            semantic_all = np.load(output / "encoders" / model_key / "embeddings.npy", allow_pickle=False)
            if len(semantic_all) != len(records):
                raise ValueError(f"Embedding alignment failure: {model_key}")
            for goal in GOALS:
                indices = by_goal[goal]
                rows = [records[i] for i in indices]
                semantic = semantic_all[indices]
                split_index = {
                    split: np.array([i for i, row in enumerate(rows) if row["split"] == split], dtype=int)
                    for split in ("train", "selection", "verification")
                }
                vectorizer = TfidfVectorizer(
                    analyzer="char_wb", ngram_range=(3, 5), min_df=2,
                    max_features=2000, sublinear_tf=True, norm="l2",
                )
                vectorizer.fit([rows[i]["clustering_text"] for i in split_index["train"]])
                lexical = vectorizer.transform([row["clustering_text"] for row in rows]).toarray().astype("float32")
                max_k = min(
                    max_clusters,
                    len(split_index["train"]) // minimum_cluster_size,
                    len(split_index["selection"]) // minimum_eval_per_cluster,
                )
                if max_k < 2:
                    raise ValueError(f"Insufficient sample for {goal}: maximum supported k={max_k}")
                candidates = []
                for weight in SEMANTIC_WEIGHTS:
                    features = hybrid_features(semantic, lexical, weight)
                    for k in range(2, max_k + 1):
                        clusterer = SphericalKMeans(k).fit(features[split_index["train"]])
                        train_counts = np.bincount(clusterer.labels_, minlength=k)
                        if np.any(train_counts < minimum_cluster_size):
                            searches.append({
                                "encoder": model_key, "goal": goal,
                                "semantic_weight": weight, "k": k,
                                "train_items": len(split_index["train"]),
                                "selection_items": len(split_index["selection"]),
                                "status": "unsupported_training_cluster_counts",
                                "minimum_training_cluster_count": int(train_counts.min()),
                                "minimum_cluster_count": None, "silhouette": None,
                            })
                            continue
                        train_rows = [rows[i] for i in split_index["train"]]
                        cluster_label_map = majority_cluster_labels(clusterer.labels_, train_rows)
                        selection_labels = clusterer.predict(features[split_index["selection"]])
                        outcome = partition_metrics(
                            features[split_index["selection"]], selection_labels,
                            [rows[i] for i in split_index["selection"]], k,
                            minimum_eval_per_cluster, cluster_label_map,
                        )
                        trial = {
                            "encoder": model_key, "goal": goal, "semantic_weight": weight,
                            "k": k, "train_items": len(split_index["train"]),
                            "selection_items": len(split_index["selection"]),
                            "minimum_training_cluster_count": int(train_counts.min()), **outcome,
                        }
                        searches.append(trial)
                        if outcome["status"] == "defined":
                            candidates.append((
                                outcome["silhouette"], -k, weight, clusterer, features,
                                cluster_label_map,
                            ))
                if not candidates:
                    metrics.append({
                        "encoder": model_key, "goal": goal, "split": "selection",
                        "status": "no_supported_partition", "items": len(split_index["selection"]),
                    })
                    continue
                _, negative_k, weight, clusterer, features, cluster_label_map = max(
                    candidates, key=lambda item: item[:3]
                )
                k = -negative_k
                bundle_path = saved_models / f"{model_key}_{goal}.joblib"
                joblib.dump({
                    "encoder": model_key, "goal": goal, "semantic_weight": weight, "k": k,
                    "cluster_centers": clusterer.cluster_centers_,
                    "vectorizer": vectorizer,
                    "cluster_label_map": cluster_label_map,
                    "train_item_ids": [rows[i]["item_id"] for i in split_index["train"]],
                }, bundle_path)
                labels_by_split = {}
                for split in ("selection", "verification"):
                    positions = split_index[split]
                    predicted = clusterer.predict(features[positions])
                    labels_by_split[split] = predicted
                    outcome = partition_metrics(
                        features[positions], predicted, [rows[i] for i in positions],
                        k, minimum_eval_per_cluster, cluster_label_map,
                    )
                    metrics.append({
                        "encoder": model_key, "goal": goal, "split": split,
                        "semantic_weight": weight, "k": k, "items": len(positions), **outcome,
                    })
                all_labels = clusterer.predict(features)
                assignments.extend({
                    **row, "encoder": model_key, "cluster_id": f"{goal}:C{int(label):02d}",
                    "industry_cluster_id": (
                        f"{row['industry']}|{goal}:C{int(label):02d}"
                    ),
                    "cluster_number": int(label), "selected_semantic_weight": weight,
                    "selected_k": k, "cluster_label": cluster_label_map[int(label)],
                } for row, label in zip(rows, all_labels))
                LOGGER.info("%s/%s selected weight=%.2f k=%s", model_key, goal, weight, k)

    search_frame = pd.DataFrame(searches)
    metric_frame = pd.DataFrame(metrics)
    assignment_frame = pd.DataFrame(assignments)
    search_frame.to_csv(output / "hyperparameter_search.csv", index=False)
    metric_frame.to_csv(output / "cohort_metrics.csv", index=False)
    assignment_frame.to_csv(output / "all_encoder_assignments.csv.gz", index=False, compression="gzip")

    defined = metric_frame[metric_frame.status.eq("defined")].copy()
    ranking_rows = []
    for encoder in models:
        for split in ("selection", "verification"):
            subset = metric_frame[(metric_frame.encoder == encoder) & (metric_frame.split == split)]
            supported = subset[subset.status.eq("defined")]
            ranking_rows.append({
                "encoder": encoder, "split": split,
                "coverage": len(supported) / len(GOALS),
                "defined_goals": len(supported), "total_goals": len(GOALS),
                "conditional_silhouette": supported.silhouette.mean() if len(supported) else np.nan,
                "coarse_label_ari": supported.coarse_label_ari.mean() if len(supported) else np.nan,
                "coarse_label_purity": supported.coarse_label_purity.mean() if len(supported) else np.nan,
                "coarse_label_precision": supported.coarse_label_precision.mean() if len(supported) else np.nan,
                "coarse_label_recall": supported.coarse_label_recall.mean() if len(supported) else np.nan,
                "coarse_label_f1": supported.coarse_label_f1.mean() if len(supported) else np.nan,
            })
    ranking = pd.DataFrame(ranking_rows)
    ranking.to_csv(output / "encoder_ranking.csv", index=False)
    eligible = ranking[(ranking.split == "selection") & (ranking.coverage >= minimum_coverage)]
    if eligible.empty:
        raise ValueError("No encoder meets the minimum selection coverage")
    selected = eligible.sort_values(
        ["conditional_silhouette", "encoder"], ascending=[False, True]
    ).iloc[0]
    winner = str(selected.encoder)
    verification = ranking[(ranking.encoder == winner) & (ranking.split == "verification")].iloc[0]
    selection = {
        "selected_encoder": winner,
        "selection_coverage": float(selected.coverage),
        "selection_conditional_silhouette": float(selected.conditional_silhouette),
        "verification_coverage": float(verification.coverage),
        "verification_conditional_silhouette": (
            float(verification.conditional_silhouette)
            if pd.notna(verification.conditional_silhouette) else None
        ),
        "verification_supported": bool(verification.coverage >= minimum_coverage),
        "selection_rule": "Require minimum coverage, then maximize conditional selection silhouette.",
        "interpretation": "Coverage and separation are reported separately; undefined partitions are not assigned a silhouette of -1.",
    }
    write_json(output / "selection.json", selection)

    winner_assignments = assignment_frame[assignment_frame.encoder.eq(winner)].copy()
    winner_assignments.to_csv(output / "selected_encoder_assignments.csv.gz", index=False, compression="gzip")
    aggregate_company_year_actions(winner_assignments, output)
    create_human_validation_sample(winner_assignments, output)
    return selection


def aggregate_company_year_actions(assignments: pd.DataFrame, output: Path) -> None:
    rows = []
    for (company, year, goal), group in assignments.groupby(["company", "year", "goal"], sort=True):
        clusters = sorted(set(group.cluster_id))
        industry_clusters = sorted(set(group.industry_cluster_id))
        rows.append({
            "company": company, "year": int(year), "goal": goal,
            "action_cluster_ids": json.dumps(clusters), "action_cluster_count": len(clusters),
            "industry_action_cluster_ids": json.dumps(industry_clusters),
            "industry_action_cluster_count": len(industry_clusters),
            "item_count": len(group), "review_ids": json.dumps(sorted(set(group.review_id))),
            "industries": json.dumps(sorted(set(group.industry))),
        })
    pd.DataFrame(rows).to_csv(output / "company_year_multilabel_actions.csv", index=False)


def create_human_validation_sample(assignments: pd.DataFrame, output: Path, per_cluster: int = 5) -> None:
    rows = []
    eligible = assignments[assignments.split.isin(["selection", "verification"])]
    for (goal, cluster), group in eligible.groupby(["goal", "cluster_id"], sort=True):
        ordered = group.assign(
            sample_key=group.item_id.map(lambda value: digest("human-validation|" + value))
        ).sort_values("sample_key").head(per_cluster)
        for _, row in ordered.iterrows():
            rows.append({
                "item_id": row.item_id, "review_id": row.review_id, "goal": goal,
                "industry": row.industry, "source_field": row.source_field,
                "cluster_id": cluster, "cluster_label": row.cluster_label,
                "coarse_human_label": row.coarse_human_label,
                "original_evidence": row.original_evidence,
                "source_context": row.source_context,
                "coder1_same_operational_action": "",
                "coder1_label_fit": "", "coder1_multiple_actions": "",
                "coder1_implementation_not_intention": "",
                "coder1_action_label": "", "coder1_id": "", "coder1_notes": "",
                "coder2_same_operational_action": "",
                "coder2_label_fit": "", "coder2_multiple_actions": "",
                "coder2_implementation_not_intention": "",
                "coder2_action_label": "", "coder2_id": "", "coder2_notes": "",
            })
    pd.DataFrame(rows).to_csv(output / "human_validation_sample.csv", index=False, encoding="utf-8-sig")


def verify(output: Path, models: list[str]) -> dict:
    records = read_jsonl(output / "span_records.jsonl.gz")
    counts = Counter((row["goal"], row["split"]) for row in records)
    for goal in GOALS:
        if counts[(goal, "selection")] < 30 or counts[(goal, "verification")] < 30:
            raise ValueError("Evaluation sample requirement failed")
    for model in models:
        matrix = np.load(output / "encoders" / model / "embeddings.npy", allow_pickle=False)
        if len(matrix) != len(records) or not np.isfinite(matrix).all():
            raise ValueError(f"Invalid embeddings for {model}")
        if not np.allclose(np.linalg.norm(matrix, axis=1), 1, atol=1e-4):
            raise ValueError(f"Non-unit embeddings for {model}")
    metrics = pd.read_csv(output / "cohort_metrics.csv")
    supported = metrics[metrics.status.eq("defined")]
    if not supported.minimum_cluster_count.ge(5).all():
        raise ValueError("A reported silhouette violates the minimum cluster support rule")
    if metrics[metrics.status.ne("defined")].silhouette.notna().any():
        raise ValueError("Undefined partitions have been assigned silhouette values")
    searches = pd.read_csv(output / "hyperparameter_search.csv")
    trained = searches[searches.status.ne("unsupported_training_cluster_counts")]
    minimum_training = int(json.loads(
        (output / "benchmark_design.json").read_text(encoding="utf-8")
    )["minimum_training_cluster_size"])
    if "minimum_training_cluster_count" in trained and trained.minimum_training_cluster_count.notna().any():
        if not trained.minimum_training_cluster_count.dropna().ge(minimum_training).all():
            raise ValueError("A candidate violates the minimum training cluster support rule")
    result = {
        "records_sha256": file_digest(output / "span_records.jsonl.gz"),
        "models": models, "company_splits_disjoint": True,
        "minimum_evaluation_sample_met": True,
        "undefined_silhouettes_left_missing": True,
        "supported_partitions_have_five_items_per_cluster": True,
        "selection_sha256": file_digest(output / "selection.json"),
    }
    write_json(output / "verification_checks.json", result)
    return result


def require_stage_outputs(output: Path, models: list[str], stage: str) -> None:
    """Fail with the command needed to produce a missing prerequisite."""
    if stage in {"evaluate", "verify"}:
        missing = [
            model for model in models
            if not (output / "encoders" / model / "embeddings.npy").exists()
        ]
        if missing:
            names = " ".join(missing)
            raise SystemExit(
                "Missing embeddings for: " + ", ".join(missing) + ".\n"
                "Run the encoding stage first:\n"
                ".\\scripts\\run_cdp_action_taxonomy_benchmark.ps1 "
                f"-Stage encode -Models {names} -Device cpu"
            )
    if stage == "verify":
        required = (
            "cohort_metrics.csv", "hyperparameter_search.csv",
            "benchmark_design.json", "selection.json",
        )
        missing = [name for name in required if not (output / name).exists()]
        if missing:
            names = " ".join(models)
            raise SystemExit(
                "Missing evaluation outputs: " + ", ".join(missing) + ".\n"
                "Run the evaluation stage first:\n"
                ".\\scripts\\run_cdp_action_taxonomy_benchmark.ps1 "
                f"-Stage evaluate -Models {names}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("prepare", "encode", "evaluate", "verify", "all"), default="all")
    parser.add_argument("--models", nargs="+", choices=sorted(MODEL_SPECS), default=DEFAULT_MODELS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--answers", type=Path, default=DATA / "cdp_validation_answers.jsonl.gz")
    parser.add_argument("--labels", type=Path, default=DATA / "cdp_validation_detail_labels.jsonl.gz")
    parser.add_argument("--workbook", type=Path, default=VALIDATION_WORKBOOK)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--max-clusters", type=int, default=12)
    parser.add_argument("--minimum-cluster-size", type=int, default=10)
    parser.add_argument("--minimum-eval-per-cluster", type=int, default=5)
    parser.add_argument("--minimum-coverage", type=float, default=0.75)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    records = prepare(args.output, args.answers, args.labels, args.workbook)
    if args.stage in {"evaluate", "verify"}:
        require_stage_outputs(args.output, args.models, args.stage)
    if args.stage != "prepare":
        load_analysis_dependencies()
    if args.stage in {"encode", "all"}:
        for model in args.models:
            encode_model(model, records, args.output, batch_size=args.batch_size,
                         device=args.device, offline=args.offline)
    if args.stage in {"evaluate", "all"}:
        require_stage_outputs(args.output, args.models, "evaluate")
        evaluate(
            args.models, records, args.output, max_clusters=args.max_clusters,
            minimum_cluster_size=args.minimum_cluster_size,
            minimum_eval_per_cluster=args.minimum_eval_per_cluster,
            minimum_coverage=args.minimum_coverage,
        )
    if args.stage in {"verify", "all"}:
        require_stage_outputs(args.output, args.models, "verify")
        verify(args.output, args.models)


if __name__ == "__main__":
    main()

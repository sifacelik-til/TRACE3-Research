"""Sector-isolated, train-fitted semantic/lexical clustering of complete CDP fields."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix, hstack
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import normalize
from threadpoolctl import threadpool_limits

from src.cdp_text_clustering.review_cdp_initiatives import (
    HERE, ROOT, read_jsonl, reviewed_candidates, source_context, write_csv, write_json,
)

LOGGER = logging.getLogger(__name__)
SOURCE = ROOT / "data" / "outputs" / "cdp_text_clustering" / "cdp_field_chunks_20261001"
OUTPUT = ROOT / "data" / "outputs" / "cdp_text_clustering" / "cdp_field_chunks_sector_specific_20261001"
SEEDS = (42, 123, 2026)
SEMANTIC_WEIGHT = 0.7
STOP_WORDS = sorted(set(ENGLISH_STOP_WORDS) | {
    "annual", "annually", "company", "companies", "estimated", "group", "initiative",
    "initiatives", "investment", "monetary", "payback", "period", "project", "projects",
    "reported", "reporting", "required", "tco2e", "tonnes", "year", "years",
})


def text_key(text: str) -> str:
    return " ".join(text.casefold().split())


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_embeddings(source: Path) -> tuple[list[dict], dict[str, np.ndarray]]:
    fields = read_jsonl(source / "fields.jsonl")
    registry = {row["field_id"]: row for row in fields}
    if len(registry) != len(fields):
        raise ValueError("Duplicate field IDs")
    manifest = pd.read_csv(source / "response_field_embedding_manifest.csv",
                           dtype=str, keep_default_na=False)
    vectors = np.load(source / "response_field_embeddings.npy", allow_pickle=False)
    if (vectors.ndim != 2 or len(vectors) != len(manifest)
            or not manifest.field_id.is_unique or not np.isfinite(vectors).all()
            or not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-4)):
        raise ValueError("Invalid embedding matrix or row manifest")
    available = {row["field_id"] for row in fields if row["field_status"] == "available"}
    if set(manifest.field_id) != available:
        raise ValueError("Embedding manifest does not cover exactly the available fields")
    for row in manifest.to_dict("records"):
        if any(row[key] != registry[row["field_id"]][key]
               for key in ("dataset", "record_id", "source_field")):
            raise ValueError("Embedding manifest source identity mismatch")
    for dataset in {row["dataset"] for row in fields}:
        group = [row for row in fields if row["dataset"] == dataset]
        if any(row["split"] not in {"train", "holdout"} for row in group):
            raise ValueError("Unknown source split")
        for key in ("company_id", "connected_group"):
            train = {row[key] for row in group if row["split"] == "train"}
            holdout = {row[key] for row in group if row["split"] == "holdout"}
            if train & holdout:
                raise ValueError(f"Training/holdout {key} leakage in {dataset}")
    return fields, dict(zip(manifest.field_id, vectors))


def hybrid_features(semantic: np.ndarray, texts: list[str], vectorizer=None,
                    *, fit: bool = False):
    if fit:
        vectorizer = TfidfVectorizer(
            lowercase=True, strip_accents="unicode", stop_words=STOP_WORDS,
            token_pattern=r"(?u)\b[^\W\d_][\w-]+\b", ngram_range=(1, 2),
            sublinear_tf=True, max_features=4000, dtype=np.float32,
        )
        analyzer = vectorizer.build_analyzer()
        if not any(analyzer(text) for text in texts):
            LOGGER.warning("No lexical tokens in a training cohort; using semantic features only")
            vectorizer = None
        else:
            vectorizer.fit(texts)
    if vectorizer is None:
        return csr_matrix(semantic), None
    lexical = vectorizer.transform(texts)
    features = hstack([
        csr_matrix(semantic * np.sqrt(SEMANTIC_WEIGHT)),
        lexical * np.sqrt(1 - SEMANTIC_WEIGHT),
    ], format="csr")
    return normalize(features, copy=False), vectorizer


def fit_cohort(rows: list[dict], embeddings: dict[str, np.ndarray], *,
               max_clusters: int, min_cluster_size: int, tolerance: float) -> dict:
    train = [row for row in rows if row["split"] == "train"]
    unique = {}
    for row in train:
        unique.setdefault(text_key(row["text"]), row)
    fit_rows = list(unique.values())
    result = {"train_fields": len(train), "unique_train_fields": len(fit_rows),
              "train_companies": len({row["company_id"] for row in train}),
              "trials": [], "fit_rows": fit_rows}
    if len(fit_rows) < 2 * min_cluster_size or result["train_companies"] < 4:
        return {**result, "status": "unclustered_insufficient_training"}
    features, vectorizer = hybrid_features(
        np.stack([embeddings[row["field_id"]] for row in fit_rows]),
        [row["text"] for row in fit_rows], fit=True,
    )
    upper = min(max_clusters, len(fit_rows) // min_cluster_size)
    choices = []
    for k in range(2, upper + 1):
        models, scores, labels_by_seed = [], [], []
        for seed in SEEDS:
            model = KMeans(n_clusters=k, n_init=10, random_state=seed)
            labels = model.fit_predict(features)
            sizes = np.bincount(labels, minlength=k)
            companies = [len({row["company_id"] for row, label in zip(fit_rows, labels)
                              if label == cluster}) for cluster in range(k)]
            supported = sizes.min() >= min_cluster_size and min(companies) >= 2
            score = float(silhouette_score(features, labels, metric="cosine")) if supported else None
            result["trials"].append({
                "k": k, "seed": seed, "min_unique_fields": int(sizes.min()),
                "min_companies": min(companies), "train_silhouette": score,
                "status": "supported" if supported else "rejected_small_cluster",
            })
            models.append(model)
            scores.append(score)
            labels_by_seed.append(labels)
        if all(score is not None for score in scores):
            choices.append({
                "k": k, "score": float(np.mean(scores)),
                "model": models[int(np.argmax(scores))],
                "seed": SEEDS[int(np.argmax(scores))],
                "seed_ari": float(np.mean([
                    adjusted_rand_score(a, b) for a, b in combinations(labels_by_seed, 2)
                ])),
            })
    if not choices:
        return {**result, "status": "unclustered_no_supported_partition"}
    best = max(choice["score"] for choice in choices)
    if best <= 0:
        return {**result, "status": "unclustered_no_positive_separation"}
    # Prefer a finer supported partition only when it stays close to the best training score.
    chosen = max((choice for choice in choices
                  if choice["score"] > 0 and choice["score"] >= best - tolerance),
                 key=lambda choice: choice["k"])
    return {**result, **chosen, "vectorizer": vectorizer, "status": "clustered",
            "feature_status": "semantic_lexical" if vectorizer is not None else "semantic_only"}


def descriptive_terms(vectorizer, fit_rows: list[dict], labels: np.ndarray, cluster: int) -> list[str]:
    if vectorizer is None:
        return []
    lexical = vectorizer.transform([row["text"] for row in fit_rows])
    inside = np.asarray(lexical[labels == cluster].mean(axis=0)).ravel()
    outside = np.asarray(lexical[labels != cluster].mean(axis=0)).ravel()
    weights = inside - outside
    terms = vectorizer.get_feature_names_out()
    selected = []
    for index in np.argsort(-weights):
        if weights[index] <= 0 or len(selected) == 5:
            break
        term = terms[index]
        if not any(set(term.split()) <= set(other.split()) for other in selected):
            selected = [other for other in selected
                        if not set(other.split()) < set(term.split())]
            selected.append(term)
    return selected


def review_overlay(fields: list[dict], chunks: list[dict], contexts: dict[str, dict]) -> dict:
    review = json.loads((HERE / "cdp_initiative_review.json").read_text(encoding="utf-8"))
    codebook = json.loads((HERE / "cdp_field_codebook.json").read_text(encoding="utf-8"))
    subset = [row for row in fields if row["dataset"] in review["scope"]
              and row["record_id"] in review["evidence"] and row["field_status"] == "available"]
    selected = {row["record_id"] for row in subset}
    scoped_review = {
        **review, "evidence": {key: value for key, value in review["evidence"].items() if key in selected},
        "notes": {key: value for key, value in review["notes"].items() if key in selected},
    }
    proposals = reviewed_candidates(subset, chunks, scoped_review, codebook, contexts)
    grouped = defaultdict(list)
    for proposal in proposals:
        grouped[proposal["field_id"]].append(proposal)
    return grouped


def specific_initiative_groups(assignments: dict[str, dict], overlay: dict) -> tuple[list[dict], list[dict]]:
    members, grouped = [], defaultdict(list)
    for field_id, row in assignments.items():
        hints = overlay.get(field_id, [])
        valid = [hint for hint in hints if hint["sector_initiative_cluster_key"]]
        row["specific_initiative_group_ids"] = json.dumps(
            [hint["sector_initiative_cluster_key"] for hint in valid], ensure_ascii=False)
        row["specific_initiative_group_status"] = (
            "pending_evidence_guided_group" if valid else
            "unassigned_missing_sector" if hints and row["sector_label_source"] != "cdp_primary_industry" else
            "unassigned_no_specific_mechanism" if hints else "not_evidence_reviewed"
        )
        for hint in valid:
            member = {
                **{key: row[key] for key in (
                    "dataset", "record_id", "field_id", "source_field", "company_id",
                    "company_name", "year", "split", "sector_label",
                    "primary_sector_reported", "primary_industry_reported",
                )},
                "specific_group_id": hint["sector_initiative_cluster_key"],
                "specific_group_label": f"{row['sector_label']} | {hint['initiative_name']}",
                "code": hint["code"], "initiative_name": hint["initiative_name"],
                "parent_code": hint["parent_code"], "review_status": hint["review_status"],
                "evidence_start": hint["evidence_start"], "evidence_end": hint["evidence_end"],
                "evidence_text": hint["evidence_text"],
                "model_cluster_id": row["cluster_id"], "model_cluster_label": row["cluster_label"],
                "model_assignment_status": row["assignment_status"],
                "grouping_method": "sector_and_pending_evidence_code_not_fitted_model",
            }
            members.append(member)
            grouped[member["specific_group_id"]].append(member)
    summaries = []
    for group_id, rows in sorted(grouped.items()):
        summaries.append({
            "specific_group_id": group_id, "specific_group_label": rows[0]["specific_group_label"],
            "sector_label": rows[0]["sector_label"], "code": rows[0]["code"],
            "initiative_name": rows[0]["initiative_name"],
            "fields": len({row["field_id"] for row in rows}),
            "companies": len({row["company_id"] for row in rows}),
            "train_fields": sum(row["split"] == "train" for row in rows),
            "holdout_fields": sum(row["split"] == "holdout" for row in rows),
            "model_clusters": len({row["model_cluster_id"] for row in rows if row["model_cluster_id"]}),
            "review_status": "pending_ai_suggestions",
            "support_status": "multiple_fields" if len(rows) > 1 else "single_field_review_group",
        })
    return members, summaries


def run(source: Path, output: Path, *, max_clusters: int = 16,
        min_cluster_size: int = 3, tolerance: float = 0.02) -> dict:
    if max_clusters < 2 or min_cluster_size < 2 or not 0 <= tolerance <= 0.1:
        raise ValueError("Invalid cluster count, minimum size, or granularity tolerance")
    if source.resolve() == output.resolve():
        raise ValueError("Sector clustering must not overwrite the baseline directory")
    fields, embeddings = load_embeddings(source)
    contexts = source_context(fields, ROOT)
    overlay = review_overlay(fields, read_jsonl(source / "chunks.jsonl"), contexts)
    fingerprint = {
        "pipeline_version": 1,
        **{name: sha(source / name) for name in (
            "fields.jsonl", "response_field_embeddings.npy",
            "response_field_embedding_manifest.csv", "experiment.json",
        )},
        "context_sha256": hashlib.sha256(
            json.dumps(contexts, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
        "review_sha256": sha(HERE / "cdp_initiative_review.json"),
        "codebook_sha256": sha(HERE / "cdp_field_codebook.json"),
        "max_clusters": max_clusters, "min_cluster_size": min_cluster_size,
        "granularity_tolerance": tolerance, "semantic_weight": SEMANTIC_WEIGHT,
        "seeds": list(SEEDS), "sector_level": "cdp_primary_industry",
    }
    experiment = output / "experiment.json"
    if output.exists() and any(output.iterdir()):
        if not experiment.exists() or json.loads(experiment.read_text())["fingerprint"] != fingerprint:
            raise ValueError("Output has different inputs/settings; choose a new output directory")
    output.mkdir(parents=True, exist_ok=True)
    (output / "completion.json").unlink(missing_ok=True)
    model_dir = output / "models"
    model_dir.mkdir(exist_ok=True)
    import importlib.metadata
    write_json(experiment, {
        "fingerprint": fingerprint, "source_directory": str(source.resolve()),
        "implementation_sha256": sha(Path(__file__)),
        "source_encoder": json.loads((source / "experiment.json").read_text())["fingerprint"],
        "packages": {name: importlib.metadata.version(name)
                     for name in ("numpy", "scipy", "scikit-learn", "pandas")},
        "fit_policy": "Unique training field texts only; no holdout fitting or tuning.",
        "label_policy": "Training-only lexical descriptors; reviewed codes are overlays, never features.",
    })
    train_texts = defaultdict(set)
    for row in fields:
        if row["split"] == "train" and row["field_status"] == "available":
            train_texts[(row["dataset"], row["source_field"])].add(text_key(row["text"]))
    assignments, cohorts = {}, defaultdict(list)
    for row in fields:
        context = contexts[row["field_id"]]
        hints = overlay.get(row["field_id"], [])
        assignments[row["field_id"]] = {
            **{key: row[key] for key in (
                "dataset", "record_id", "field_id", "source_field", "role", "split",
            )},
            **context, "cluster_id": "", "cluster_label": "", "cluster_terms": "",
            "assignment_cosine": "", "assignment_distance_margin": "",
            "reviewed_initiative_codes": "; ".join(hint["code"] for hint in hints),
            "reviewed_initiative_names": "; ".join(
                hint["initiative_name"] for hint in hints if hint["initiative_name"]
            ),
            "coding_status": "pending_ai_suggestion" if hints else "not_evidence_reviewed",
            "source_text": row["text"],
            "holdout_diagnostic_status": (
                "not_holdout" if row["split"] == "train" else
                "excluded_exact_field_duplicate_of_training"
                if text_key(row["text"]) in train_texts[(row["dataset"], row["source_field"])]
                else "eligible_holdout"
            ),
        }
        if row["field_status"] != "available":
            assignments[row["field_id"]]["assignment_status"] = "unclustered_blank_source"
        elif context["sector_label_source"] != "cdp_primary_industry":
            assignments[row["field_id"]]["assignment_status"] = "unclustered_missing_sector"
        else:
            cohorts[(row["dataset"], row["source_field"], context["sector_label"])].append(row)
    summaries, cohort_metrics, trials, representatives = [], [], [], []
    with threadpool_limits(limits=2):
        for number, (key, rows) in enumerate(sorted(cohorts.items()), 1):
            dataset, source_field, sector = key
            identity = {"dataset": dataset, "source_field": source_field, "sector_label": sector}
            result = fit_cohort(rows, embeddings, max_clusters=max_clusters,
                                min_cluster_size=min_cluster_size, tolerance=tolerance)
            trials.extend({**identity, **trial} for trial in result["trials"])
            metric = {
                **identity, **{key: result[key] for key in (
                    "status", "train_fields", "unique_train_fields", "train_companies")},
                "holdout_fields": sum(row["split"] == "holdout" for row in rows),
                "selected_k": result.get("k", 0), "selected_seed": result.get("seed", ""),
                "train_silhouette_mean": result.get("score", ""),
                "seed_ari_mean": result.get("seed_ari", ""),
                "feature_status": result.get("feature_status", "not_fitted"),
                "holdout_silhouette": "", "holdout_metric_status": "no_model",
            }
            cohort_metrics.append(metric)
            if result["status"] != "clustered":
                for row in rows:
                    assignments[row["field_id"]]["assignment_status"] = result["status"]
                LOGGER.warning("%s/%s/%s: %s", *key, result["status"])
                continue
            model, vectorizer, fit_rows = result["model"], result["vectorizer"], result["fit_rows"]
            features, _ = hybrid_features(
                np.stack([embeddings[row["field_id"]] for row in rows]),
                [row["text"] for row in rows], vectorizer,
            )
            labels = model.predict(features)
            similarities = np.asarray(features @ normalize(model.cluster_centers_).T)
            distances = np.sort(model.transform(features), axis=1)
            fit_labels = model.labels_
            eligible = [i for i, row in enumerate(rows)
                        if assignments[row["field_id"]]["holdout_diagnostic_status"] == "eligible_holdout"]
            metric["eligible_holdout_fields"] = len(eligible)
            if len(eligible) >= 3 and 2 <= len(set(labels[eligible])) < len(eligible):
                metric["holdout_silhouette"] = float(
                    silhouette_score(features[eligible], labels[eligible], metric="cosine"))
                metric["holdout_metric_status"] = "defined"
            else:
                metric["holdout_metric_status"] = "undefined_sample_or_cluster_count"
            names, terms_by_cluster = {}, {}
            for cluster in range(result["k"]):
                cluster_id = f"{dataset}|{source_field}|{sector}|{cluster:02d}"
                terms = descriptive_terms(vectorizer, fit_rows, fit_labels, cluster)
                terms_by_cluster[cluster] = "; ".join(terms)
                names[cluster] = f"{sector} | " + ("; ".join(terms) or f"semantic subcluster {cluster:02d}")
                members = [row for row, label in zip(rows, labels) if label == cluster]
                fit_members = [row for row, label in zip(fit_rows, fit_labels) if label == cluster]
                code_counts = Counter(
                    hint["code"] for row in fit_members for hint in overlay.get(row["field_id"], [])
                )
                summaries.append({
                    **identity, "cluster_id": cluster_id, "cluster_label": names[cluster],
                    "cluster_terms": terms_by_cluster[cluster], "fields": len(members),
                    "train_fields": sum(row["split"] == "train" for row in members),
                    "holdout_fields": sum(row["split"] == "holdout" for row in members),
                    "unique_train_fields": len(fit_members),
                    "train_companies": len({row["company_id"] for row in fit_members}),
                    "reviewed_train_code_counts": json.dumps(dict(code_counts), sort_keys=True),
                })
                fit_ids = {row["field_id"] for row in fit_members}
                positions = sorted((i for i, row in enumerate(rows) if row["field_id"] in fit_ids),
                                   key=lambda i: -similarities[i, cluster])[:3]
                for rank, i in enumerate(positions, 1):
                    row = rows[i]
                    representatives.append({
                        **identity, "cluster_id": cluster_id, "rank": rank,
                        "field_id": row["field_id"], "record_id": row["record_id"],
                        "company_id": row["company_id"], "split": row["split"],
                        "centroid_cosine": float(similarities[i, cluster]), "source_text": row["text"],
                    })
            for i, (row, cluster) in enumerate(zip(rows, labels)):
                assignments[row["field_id"]].update({
                    "assignment_status": "clustered", "cluster_id": f"{dataset}|{source_field}|{sector}|{cluster:02d}",
                    "cluster_label": names[cluster], "cluster_terms": terms_by_cluster[cluster],
                    "assignment_cosine": float(similarities[i, cluster]),
                    "assignment_distance_margin": float(distances[i, 1] - distances[i, 0]),
                })
            cohort_id = hashlib.sha256(json.dumps(key).encode("utf-8")).hexdigest()[:16]
            joblib.dump({
                **identity, "model": model, "vectorizer": vectorizer,
                "semantic_weight": SEMANTIC_WEIGHT,
                "fit_field_ids": [row["field_id"] for row in fit_rows],
                "cluster_names": names, "cluster_terms": terms_by_cluster,
            }, model_dir / f"{cohort_id}.joblib")
            LOGGER.info("Cohort %s/%s: %s/%s/%s -> %s subclusters",
                        number, len(cohorts), *key, result["k"])
    specific_members, specific_summary = specific_initiative_groups(assignments, overlay)
    outputs = {
        "cluster_assignments.csv": list(assignments.values()),
        "cluster_summary.csv": summaries, "cohort_metrics.csv": cohort_metrics,
        "granularity_search.csv": trials, "representative_fields.csv": representatives,
    }
    if specific_members:
        outputs["initiative_specific_groups.csv"] = specific_members
        outputs["initiative_specific_group_summary.csv"] = specific_summary
    for filename, rows in outputs.items():
        if not rows:
            raise ValueError(f"No rows produced for {filename}; clustering did not produce a usable result")
        columns = list(dict.fromkeys(column for row in rows for column in row))
        write_csv(output / filename, rows, columns)
    write_json(output / "codebook.json", {
        "status": "draft_for_human_review",
        "codes": json.loads((HERE / "cdp_field_codebook.json").read_text(encoding="utf-8")),
    })
    with (output / "reviewed_initiative_evidence.jsonl").open("w", encoding="utf-8") as stream:
        for hints in overlay.values():
            for hint in hints:
                stream.write(json.dumps(hint, ensure_ascii=False, allow_nan=False) + "\n")
    summary = {
        "source_fields": len(fields), "available_fields": len(embeddings),
        "clusters": len(summaries), "sector_field_cohorts": len(cohorts),
        "fitted_cohorts": sum(row["status"] == "clustered" for row in cohort_metrics),
        "assignment_status_counts": dict(Counter(
            row["assignment_status"] for row in assignments.values())),
        "reviewed_initiative_fields": len(overlay),
        "reviewed_initiative_suggestions": sum(len(hints) for hints in overlay.values()),
        "specific_initiative_groups": len(specific_summary),
        "specific_initiative_group_memberships": len(specific_members),
        "specifically_grouped_initiative_fields": len({row["field_id"] for row in specific_members}),
        "mixed_sector_clusters": 0,
        "limitations": [
            "Sectors are reported broad CDP industries, not inferred classifications.",
            "Training selection and descriptive labels never use holdout texts or reviewed codes.",
            "Minimum support is counted on unique training texts, with at least two companies per cluster.",
            f"Granularity is exploratory: a larger k within {tolerance} of the best training silhouette is preferred.",
            "Unknown/sparse sectors and unsupported partitions are explicitly unclustered, not pooled.",
            "Reviewed initiative codes remain AI suggestions, including development holdout reviews.",
            "Unreviewed fields receive lexical cluster names, not extrapolated canonical code annotations.",
            "Specific initiative groups are overlapping sector-plus-evidence-code groups, not fitted K-means clusters.",
            "Small evidence groups are retained with support flags; reviewed codes are never propagated to unreviewed fields.",
            "One field gets one model cluster; multi-label mechanisms remain in the separate coding overlay.",
            "Cosines and margins are descriptive, not calibrated probabilities or correctness measures.",
            "The original complete-versus-truncated benchmark and all source artifacts are unchanged.",
        ],
    }
    cluster_sectors = defaultdict(set)
    for row in assignments.values():
        if row["cluster_id"]:
            cluster_sectors[row["cluster_id"]].add(row["sector_label"])
    if any(len(sectors) != 1 for sectors in cluster_sectors.values()):
        raise ValueError("A cluster crosses sector boundaries")
    write_json(output / "completion.json", summary)
    LOGGER.info("Completed %s clusters across %s fitted sector/field cohorts",
                len(summaries), summary["fitted_cohorts"])
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--max-clusters", type=int, default=16)
    parser.add_argument("--min-cluster-size", type=int, default=3)
    parser.add_argument("--granularity-tolerance", type=float, default=0.02)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run(args.source, args.output, max_clusters=args.max_clusters,
        min_cluster_size=args.min_cluster_size, tolerance=args.granularity_tolerance)

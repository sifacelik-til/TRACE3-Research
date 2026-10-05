"""Compare cached CDP embeddings with company-grouped, repeated-seed fits.

No model downloads or external text processing. Run with numpy, pandas,
scikit-learn, scipy, umap-learn, hdbscan, joblib, and threadpoolctl installed.
The density method reproduces BERTopic's clustering core, not its c-TF-IDF
topic representation. Outputs are internal diagnostics, not human accuracy.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import itertools
import json
import os
from pathlib import Path

os.environ.setdefault("NUMBA_NUM_THREADS", "4")
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "4")

import joblib
import numpy as np
import pandas as pd
from hdbscan import HDBSCAN, approximate_predict
from sklearn.cluster import KMeans
from sklearn.decomposition import NMF
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.model_selection import GroupShuffleSplit
from threadpoolctl import threadpool_limits
from umap import UMAP


ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed" / "cdp_2016_2024_climate_actions"
INITIATIVES = ROOT / "data" / "outputs" / "cdp_text_clustering" / "cdp_2024_emissions_initiative_clusters"
CACHE = (ROOT / "data" / "outputs" / "cdp_text_clustering" / "cdp_topic_model_benchmark"
         / "n200_seq256_initiative-risk-opportunity")
SEEDS = (42, 43, 44, 45, 46)
METHODS = ("TF-IDF + NMF", "MiniLM + k-means", "MiniLM + UMAP/HDBSCAN")


def normalized(values: pd.Series) -> pd.Series:
    return values.fillna("").str.casefold().str.replace(r"\s+", " ", regex=True).str.strip()


def check_embeddings(embeddings: np.ndarray, rows: int) -> None:
    if embeddings.shape != (rows, 384) or not np.isfinite(embeddings).all():
        raise ValueError("Invalid cached embedding shape or nonfinite values")
    if not np.allclose(np.linalg.norm(embeddings, axis=1), 1, atol=1e-4):
        raise ValueError("Expected normalized cached embeddings")


def load_datasets():
    manifest = pd.read_json(
        CACHE / "models_k12_mcs25_ms1" / "sample_manifest.jsonl", lines=True
    ).drop(columns="split")
    metadata = json.loads((CACHE / "sample_embeddings_metadata.json").read_text())
    digest = hashlib.sha256("\n".join(manifest.record_id).encode()).hexdigest()
    if digest != metadata["fingerprint"]["record_ids_sha256"]:
        raise ValueError("Longitudinal manifest differs from embedding fingerprint")
    source = PROCESSED / "climate_action_risk_opportunity_records.csv.gz"
    if source.stat().st_size != metadata["fingerprint"]["source_size_bytes"]:
        raise ValueError("Longitudinal source size differs from embedding provenance")
    if source.stat().st_mtime_ns != metadata["fingerprint"]["source_mtime_ns"]:
        raise ValueError("Longitudinal source timestamp differs from embedding provenance")
    records = pd.read_csv(
        source, usecols=["record_id", "cdp_account_number", "narrative_for_clustering"],
        dtype={"cdp_account_number": "string"}, low_memory=False,
    )
    manifest = manifest.merge(records, on="record_id", validate="one_to_one", how="left")
    if manifest[["cdp_account_number", "narrative_for_clustering"]].isna().any().any():
        raise ValueError("Missing source records or company identifiers")
    embeddings = np.load(CACHE / "sample_embeddings.npy")
    check_embeddings(embeddings, len(manifest))
    manifest = manifest.rename(columns={
        "cdp_account_number": "company_id", "narrative_for_clustering": "text"
    })
    for record_type in ("initiative", "risk", "opportunity"):
        mask = manifest.record_type.eq(record_type).to_numpy()
        yield f"longitudinal_{record_type}", manifest.loc[mask].reset_index(drop=True), embeddings[mask]

    for stem in ("q7_55_2", "q7_55_3", "q7_55_4"):
        frame = pd.read_csv(INITIATIVES / f"{stem}_assignments.csv.gz", low_memory=False)
        digest = hashlib.sha256("\n".join(
            f"{org}:{row}:{text}" for org, row, text in zip(
                frame.cdp_disclosing_org_number, frame.row_order, frame.text
            )
        ).encode()).hexdigest()[:12]
        vectors = np.load(INITIATIVES / f"{stem}_{digest}_embeddings.npy")
        check_embeddings(vectors, len(frame))
        frame["record_id"] = (
            "2024:" + frame.question_number + ":"
            + frame.cdp_disclosing_org_number.astype(str) + ":" + frame.row_order.astype(str)
        )
        frame["company_id"] = frame.cdp_disclosing_org_number.astype(str)
        frame["year"] = 2024
        frame = frame.rename(columns={"cluster": "original_bertopic_cluster"})
        yield stem, frame, vectors


def company_text_groups(frame: pd.DataFrame) -> np.ndarray:
    """Link companies sharing exact normalized narratives before splitting."""
    companies = frame.company_id.astype(str).tolist()
    parent = {company: company for company in companies}

    def find(company: str) -> str:
        while parent[company] != company:
            parent[company] = parent[parent[company]]
            company = parent[company]
        return company

    first_company: dict[str, str] = {}
    for company, text in zip(companies, normalized(frame.text)):
        if text in first_company:
            parent[find(company)] = find(first_company[text])
        else:
            first_company[text] = company
    return np.asarray([find(company) for company in companies])


def partition(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    groups = company_text_groups(frame)
    candidates = frame.assign(normalized_text=normalized(frame.text)).drop_duplicates("normalized_text")
    candidates = candidates.sample(n=min(1800, len(candidates)), random_state=20260929)
    train_local, test_local = next(GroupShuffleSplit(
        n_splits=1, test_size=0.2, random_state=20260929
    ).split(candidates, groups=groups[candidates.index]))
    train = candidates.index.to_numpy()[train_local]
    test = candidates.index.to_numpy()[test_local]
    if set(groups[train]) & set(groups[test]):
        raise AssertionError("Company/duplicate connected groups leak across splits")
    if set(normalized(frame.iloc[train].text)) & set(normalized(frame.iloc[test].text)):
        raise AssertionError("Exact normalized texts leak across splits")
    if len(train) < 50 or len(test) < 20:
        raise ValueError("Insufficient independent train or holdout rows")
    return train, test, groups


def hard_nmf(weights: np.ndarray) -> np.ndarray:
    labels = weights.argmax(axis=1)
    labels[weights.sum(axis=1) <= 1e-12] = -1
    return labels


def measure(labels: np.ndarray, embeddings: np.ndarray, lexical) -> dict:
    assigned = labels >= 0
    n_topics = len(np.unique(labels[assigned]))
    result = {
        "holdout_rows": len(labels), "assigned_rows": int(assigned.sum()),
        "outlier_pct": float(100 * (~assigned).mean()),
        "holdout_topics": n_topics,
        "semantic_silhouette": np.nan, "lexical_silhouette": np.nan,
        "largest_holdout_topic_share": np.nan,
    }
    if assigned.any():
        result["largest_holdout_topic_share"] = float(
            pd.Series(labels[assigned]).value_counts(normalize=True).max()
        )
    if 2 <= n_topics < assigned.sum():
        result["semantic_silhouette"] = float(silhouette_score(
            embeddings[assigned], labels[assigned], metric="cosine"
        ))
        result["lexical_silhouette"] = float(silhouette_score(
            lexical[assigned], labels[assigned], metric="cosine"
        ))
    return result


def pairwise_stability(dataset: str, method: str, predictions: list[np.ndarray]) -> list[dict]:
    rows = []
    for (i, first), (j, second) in itertools.combinations(enumerate(predictions), 2):
        common = (first >= 0) & (second >= 0)
        ari = np.nan
        if common.sum() >= 2:
            ari = float(adjusted_rand_score(first[common], second[common]))
        rows.append({
            "dataset": dataset, "method": method,
            "first_seed": SEEDS[i], "second_seed": SEEDS[j],
            "ari_including_noise": float(adjusted_rand_score(first, second)),
            "ari_common_assigned": ari,
            "common_assigned_fraction": float(common.mean()),
        })
    return rows


def cluster_table(frame: pd.DataFrame, labels: np.ndarray, features, words: np.ndarray) -> pd.DataFrame:
    rows = []
    for topic in sorted(set(labels)):
        members = np.flatnonzero(labels == topic)
        scores = np.asarray(features[members].mean(axis=0)).ravel()
        terms = words[np.argsort(scores)[-10:][::-1]]
        rows.append({
            "cluster": int(topic), "responses": len(members),
            "companies": frame.iloc[members].company_id.nunique(),
            "top_words": "; ".join(terms),
            "label_status": "automatic_words_not_human_validated",
        })
    return pd.DataFrame(rows)


def run(output: Path) -> None:
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing results: {output}")
    output.mkdir(parents=True, exist_ok=True)
    metrics, stability, splits, sensitivity, provenance = [], [], [], [], []
    with threadpool_limits(limits=4):
        for name, frame, embeddings in load_datasets():
            if not frame.record_id.is_unique:
                raise ValueError(f"Nonunique source IDs: {name}")
            train, test, groups = partition(frame)
            k = 6 if name == "q7_55_4" else 12
            vectorizer = TfidfVectorizer(
                stop_words="english", min_df=2, max_df=0.9,
                max_features=15000, sublinear_tf=True,
            )
            x_train = vectorizer.fit_transform(frame.iloc[train].text)
            x_test = vectorizer.transform(frame.iloc[test].text)
            provenance.append({
                "dataset": name, "source_rows": len(frame), "sample_rows": len(train) + len(test),
                "train_rows": len(train), "holdout_rows": len(test),
                "train_companies": frame.iloc[train].company_id.nunique(),
                "holdout_companies": frame.iloc[test].company_id.nunique(),
                "company_overlap": 0, "normalized_exact_text_overlap": 0,
                "source_text_sha256": hashlib.sha256("\n".join(frame.text).encode()).hexdigest(),
                "embedding_sha256": hashlib.sha256(embeddings.tobytes()).hexdigest(),
                "kmeans_clusters": k,
            })
            for positions, split in ((train, "train"), (test, "holdout")):
                selected = frame.iloc[positions][["record_id", "company_id", "year"]].copy()
                selected["dataset"], selected["split"] = name, split
                selected["connected_group"] = groups[positions]
                splits.append(selected)
            predictions = {method: [] for method in METHODS}
            print(f"{name}: {len(train)} train / {len(test)} holdout; k={k}", flush=True)
            base_kmeans = None
            for seed in SEEDS:
                nmf = NMF(n_components=k, init="nndsvdar", max_iter=1000, random_state=seed)
                nmf_train = hard_nmf(nmf.fit_transform(x_train))
                nmf_test = hard_nmf(nmf.transform(x_test))
                km = KMeans(n_clusters=k, n_init=10, random_state=seed)
                km_train = km.fit_predict(embeddings[train])
                km_test = km.predict(embeddings[test])
                if seed == SEEDS[0]:
                    base_kmeans = km
                reducer = UMAP(
                    n_neighbors=15, n_components=5, min_dist=0.0,
                    metric="cosine", random_state=seed, n_jobs=1,
                    transform_seed=seed, low_memory=True,
                )
                reduced = reducer.fit_transform(embeddings[train])
                density = HDBSCAN(
                    min_cluster_size=15 if k == 6 else 25, min_samples=1,
                    prediction_data=True, core_dist_n_jobs=4,
                )
                density_train = density.fit_predict(reduced)
                if (density_train >= 0).any():
                    density_test, _ = approximate_predict(
                        density, reducer.transform(embeddings[test])
                    )
                else:
                    # No discovered topic legitimately means total abstention.
                    print(f"  WARNING: {name} seed {seed}: no density topics", flush=True)
                    density_test = np.full(len(test), -1)
                for method, labels_train, labels_test in zip(
                    METHODS, (nmf_train, km_train, density_train),
                    (nmf_test, km_test, density_test),
                ):
                    predictions[method].append(labels_test)
                    row = measure(labels_test, embeddings[test], x_test)
                    row.update({
                        "dataset": name, "method": method, "seed": seed,
                        "train_topics": len(set(labels_train) - {-1}),
                        "train_rows": len(train),
                    })
                    metrics.append(row)
                    assignments = pd.DataFrame({
                        "record_id": frame.iloc[test].record_id.to_numpy(),
                        "cluster": labels_test,
                    })
                    safe_method = ("nmf", "kmeans", "density")[METHODS.index(method)]
                    assignments.to_csv(output / f"{name}_{safe_method}_seed{seed}_holdout.csv", index=False)
                print(f"  seed {seed}: density topics={len(set(density_train) - {-1})}, "
                      f"outliers={(density_test < 0).mean():.1%}", flush=True)
            for method, labels in predictions.items():
                stability.extend(pairwise_stability(name, method, labels))
            for trial_k in ((4, 6, 8) if k == 6 else (8, 12, 16)):
                candidate = KMeans(n_clusters=trial_k, n_init=10, random_state=42)
                candidate.fit(embeddings[train])
                row = measure(candidate.predict(embeddings[test]), embeddings[test], x_test)
                row.update({"dataset": name, "k": trial_k})
                sensitivity.append(row)
            if base_kmeans is None:
                raise AssertionError("Missing reference k-means model")
            labels = base_kmeans.predict(embeddings)
            columns = ["record_id", "company_id", "year", "text"]
            if "original_bertopic_cluster" in frame:
                columns.append("original_bertopic_cluster")
            assignments = frame[columns].copy()
            assignments["cluster"] = labels
            assignments["assignment_method"] = "direct_cached_MiniLM_seed42_train_fitted_kmeans"
            assignments["evaluation_role"] = "outside_selected_sample"
            assignments.loc[train, "evaluation_role"] = "train"
            assignments.loc[test, "evaluation_role"] = "holdout"
            assignments.to_csv(output / f"{name}_kmeans_assignments.csv.gz", index=False)
            all_features = vectorizer.transform(frame.text)
            summary = cluster_table(
                frame, labels, all_features, np.asarray(vectorizer.get_feature_names_out())
            )
            summary.to_csv(output / f"{name}_kmeans_summary.csv", index=False)
            # Examples use training responses; summaries describe all assignments.
            example_rows = []
            rng = np.random.default_rng(42)
            for topic in range(k):
                members = train[labels[train] == topic]
                center = base_kmeans.cluster_centers_[topic]
                nearest = members[np.argsort(np.linalg.norm(
                    embeddings[members] - center, axis=1
                ))[:2]]
                remaining = np.setdiff1d(members, nearest)
                random_members = rng.choice(remaining, min(2, len(remaining)), replace=False)
                for index in np.concatenate([nearest, random_members]):
                    example_rows.append({
                        "cluster": topic, "record_id": frame.iloc[index].record_id,
                        "selection": "centroid_nearest" if index in nearest else "random",
                        "text": frame.iloc[index].text,
                    })
            pd.DataFrame(example_rows).to_json(
                output / f"{name}_kmeans_examples.json", orient="records",
                indent=2, force_ascii=False,
            )
            joblib.dump(base_kmeans, output / f"{name}_kmeans_model.joblib")
            pd.DataFrame(metrics).to_csv(output / "metrics_by_seed.csv", index=False)
    pd.DataFrame(stability).to_csv(output / "stability_seed_pairs.csv", index=False)
    pd.DataFrame(sensitivity).to_csv(output / "k_sensitivity.csv", index=False)
    pd.concat(splits, ignore_index=True).to_csv(output / "split_manifest.csv", index=False)
    pd.DataFrame(provenance).to_csv(output / "dataset_audit.csv", index=False)
    aggregate = pd.DataFrame(metrics).groupby(["dataset", "method"]).agg(
        train_topics_mean=("train_topics", "mean"),
        train_topics_min=("train_topics", "min"), train_topics_max=("train_topics", "max"),
        outlier_pct_mean=("outlier_pct", "mean"),
        semantic_silhouette_mean=("semantic_silhouette", "mean"),
        lexical_silhouette_mean=("lexical_silhouette", "mean"),
        largest_topic_share_mean=("largest_holdout_topic_share", "mean"),
    )
    seed_summary = pd.DataFrame(stability).groupby(["dataset", "method"]).agg(
        stability_ari_mean=("ari_common_assigned", "mean"),
        stability_ari_min=("ari_common_assigned", "min"),
        common_assigned_fraction_mean=("common_assigned_fraction", "mean"),
    )
    aggregate.join(seed_summary).reset_index().to_csv(output / "comparison_summary.csv", index=False)
    metadata = {
        "seeds": SEEDS, "split_seed": 20260929,
        "packages": {name: importlib.metadata.version(name) for name in (
            "numpy", "pandas", "scikit-learn", "umap-learn", "hdbscan", "scipy"
        )},
        "scope": "Cached embeddings only; no new encoder comparison or full-corpus longitudinal fit.",
        "method": "Company/normalized-exact-text connected groups; deduplicate then sample up to 1800; fixed 20% group holdout; five initialization seeds.",
        "density": "UMAP/HDBSCAN clustering core of BERTopic, not BERTopic topic-word representation.",
        "limitations": [
            "Internal diagnostics, not human accuracy; holdout reused across seeds and k sensitivity.",
            "Not a temporal test; near-duplicate text and corporate-parent links are not resolved.",
            "Silhouette evaluated only on assigned rows; embedding-space score favors embedding methods.",
            "Seed-pair ARIs are dependent; their range is not a confidence interval.",
            "Longitudinal narratives include structured options; 2024 models use narrative only.",
            "English lexical analyzer underrepresents languages without whitespace tokenization.",
            "K-means forces assignment; coverage is not correctness or calibrated confidence.",
            "Exported seed42 models retain the training fit; topic IDs differ from existing models.",
            "Pilot annotations are not used to train, tune, or calculate accuracy; their source texts may occur in the unsupervised sample.",
            "2024 cache sequence length was not explicitly recorded; no claim of matching 256-token settings.",
        ],
    }
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Completed: {output}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=(
        ROOT / "data" / "outputs" / "cdp_text_clustering" / "cdp_clustering_verification_20260929"
    ))
    run(parser.parse_args().output)

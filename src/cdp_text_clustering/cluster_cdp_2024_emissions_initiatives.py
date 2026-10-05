"""Analyze CDP 2024 Q7.55.1--Q7.56 with BERTopic for narratives.

The CDP extract stores one questionnaire cell per row. This script rebuilds
initiative/method rows before analyzing them. BERTopic is fit separately to
the narrative answers to Q7.55.2, Q7.55.3, and Q7.55.4. Q7.55.1's stage
counts are clustered numerically; Q7.56 has too few narratives to fit alone.

Run from a terminal:
    python -m src.cdp_text_clustering.cluster_cdp_2024_emissions_initiatives
"""

from __future__ import annotations

import argparse
import hashlib
import html
import re
import sys
from pathlib import Path

import torch  # Import before BERTopic's other Windows DLL dependencies.
import numpy as np
import pandas as pd
import pyarrow.dataset as ds
from bertopic import BERTopic
from bertopic.vectorizers import ClassTfidfTransformer
from hdbscan import HDBSCAN
from sentence_transformers import SentenceTransformer
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.preprocessing import StandardScaler
from umap import UMAP


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_FILE = (
    PROJECT_ROOT
    / "data/raw/CDP/2024/"
    / "full_extract_cm_eds_c_isin_2024_responses_v1_20250623_125717.parquet"
)
OUTPUT_DIR = PROJECT_ROOT / "data/outputs/cdp_text_clustering/cdp_2024_emissions_initiative_clusters"
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
QUESTIONS = ["Q7.55.1", "Q7.55.2", "Q7.55.3", "Q7.55.4", "Q7.56"]
KEY = ["cdp_disclosing_org_number", "question_number", "row_order"]
META = ["disclosing_organization", "isin", "primary_industry_name", "row_name"]
STAGES = [
    "Under investigation",
    "To be implemented",
    "Implementation commenced",
    "Implemented",
    "Not to be implemented",
]


def clean_text(value: object) -> str:
    """Remove CDP HTML markup and normalize whitespace."""
    if pd.isna(value):
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def combine_cells(values: pd.Series) -> str:
    """Preserve multi-select fields (notably Q7.55.2 Scope categories)."""
    unique = list(dict.fromkeys(value for value in values if value))
    return " | ".join(unique)


def load_rows() -> tuple[pd.DataFrame, pd.DataFrame]:
    dataset = ds.dataset(INPUT_FILE, format="parquet")
    cells = dataset.to_table(
        columns=KEY[:2]
        + ["row_order", "column_header", "content_full", "public_status"]
        + META,
        filter=ds.field("question_number").isin(QUESTIONS),
    ).to_pandas()
    cells = cells.loc[cells["public_status"].eq("Public")].copy()
    cells["row_order"] = cells["row_order"].fillna(1).astype(int)
    cells["field"] = cells["column_header"].str.extract(r"^(col\d+)_", expand=False)
    cells["value"] = cells["content_full"].map(clean_text)

    answers = (
        cells.groupby(KEY + ["field"], dropna=False, sort=False)["value"]
        .agg(combine_cells)
        .unstack("field")
        .reset_index()
    )
    metadata = cells.groupby(KEY, sort=False)[META].first().reset_index()
    answers = answers.merge(metadata, on=KEY, how="left", validate="one_to_one")
    return cells, answers


def cluster_text(
    answers: pd.DataFrame,
    question: str,
    text_field: str,
    minimum_length: int,
    minimum_topic_size: int,
    embedder: SentenceTransformer,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    frame = answers.loc[answers["question_number"].eq(question)].copy()
    frame["text"] = frame[text_field].fillna("").map(clean_text)
    frame = frame.loc[frame["text"].str.len().ge(minimum_length)].copy()
    if frame.empty:
        return frame, pd.DataFrame(), pd.DataFrame()

    docs = frame["text"].tolist()
    digest = hashlib.sha256(
        "\n".join(
            f"{org_id}:{row_order}:{text}"
            for org_id, row_order, text in zip(
                frame["cdp_disclosing_org_number"], frame["row_order"], docs
            )
        ).encode("utf-8")
    ).hexdigest()[:12]
    cache_file = OUTPUT_DIR / f"{question.lower().replace('.', '_')}_{digest}_embeddings.npy"
    if cache_file.exists():
        embeddings = np.load(cache_file)
        if embeddings.shape[0] != len(docs):
            raise ValueError(f"Embedding cache row count mismatch: {cache_file}")
    else:
        embeddings = embedder.encode(
            docs,
            batch_size=32,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        np.save(cache_file, embeddings)

    model = BERTopic(
        embedding_model=embedder,
        umap_model=UMAP(
            n_neighbors=15,
            n_components=5,
            min_dist=0.0,
            metric="cosine",
            random_state=42,
            low_memory=True,
        ),
        hdbscan_model=HDBSCAN(
            min_cluster_size=minimum_topic_size,
            min_samples=5,
            metric="euclidean",
            cluster_selection_method="eom",
            prediction_data=True,
        ),
        vectorizer_model=CountVectorizer(
            stop_words="english", ngram_range=(1, 2), min_df=3, max_df=0.85
        ),
        ctfidf_model=ClassTfidfTransformer(reduce_frequent_words=True),
        low_memory=True,
        calculate_probabilities=False,
        verbose=True,
    )
    topics, _ = model.fit_transform(docs, embeddings=embeddings)
    frame["cluster"] = topics
    topic_info = model.get_topic_info().set_index("Topic")
    frame["cluster_terms"] = frame["cluster"].map(topic_info["Name"])

    summary = (
        frame.groupby("cluster", as_index=False)
        .agg(
            responses=("text", "size"),
            companies=("cdp_disclosing_org_number", "nunique"),
        )
        .sort_values("responses", ascending=False)
    )
    summary.insert(0, "question_number", question)
    summary["cluster_terms"] = summary["cluster"].map(topic_info["Name"])
    if question in {"Q7.55.2", "Q7.55.3"}:
        summary["most_common_structured_answer"] = summary["cluster"].map(
            frame.groupby("cluster")["col1"].agg(
                lambda values: values.value_counts().index[0]
            )
        )

    # BERTopic identifies actual representative responses for each topic.
    document_info = model.get_document_info(docs)
    frame["is_representative"] = document_info["Representative_document"].to_numpy()
    examples = (
        frame.loc[frame["is_representative"] & frame["cluster"].ne(-1)]
        .drop_duplicates(["cluster", "cdp_disclosing_org_number"])
        .groupby("cluster", group_keys=False)
        .head(3)[
            KEY
            + ["disclosing_organization", "cluster", "cluster_terms", "text"]
        ]
    )
    model.save(
        OUTPUT_DIR / f"{question.lower().replace('.', '_')}_bertopic_model",
        serialization="safetensors",
        save_ctfidf=True,
        save_embedding_model=EMBEDDING_MODEL,
    )
    return frame, summary, examples


def cluster_stage_profiles(answers: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cluster Q7.55.1 company profiles using five reported stage counts."""
    frame = answers.loc[answers["question_number"].eq("Q7.55.1")].copy()
    frame["initiative_count"] = pd.to_numeric(frame["col1"], errors="coerce")
    frame["estimated_savings_tco2e"] = pd.to_numeric(
        frame["col2"], errors="coerce"
    )
    counts = frame.pivot_table(
        index="cdp_disclosing_org_number",
        columns="row_name",
        values="initiative_count",
        aggfunc="first",
    ).reindex(columns=STAGES)
    counts = counts.dropna(subset=STAGES)
    counts = counts.loc[counts.ge(0).all(axis=1)].copy()
    if len(counts) < 20:
        raise ValueError("Too few complete Q7.55.1 stage profiles")

    values = StandardScaler().fit_transform(np.log1p(counts))
    counts["cluster"] = KMeans(
        n_clusters=4, random_state=42, n_init=10
    ).fit_predict(values)
    profiles = counts.reset_index()
    company_meta = (
        frame.groupby("cdp_disclosing_org_number")
        [["disclosing_organization", "isin", "primary_industry_name"]]
        .first()
        .reset_index()
    )
    profiles = profiles.merge(
        company_meta, on="cdp_disclosing_org_number", validate="one_to_one"
    )
    summary = profiles.groupby("cluster")[STAGES].median().reset_index()
    summary.insert(
        1,
        "companies",
        summary["cluster"].map(profiles["cluster"].value_counts()),
    )
    return profiles, summary


def build_company_topic_profile(answers: pd.DataFrame) -> None:
    """Summarize saved row-level topics into a merge-ready 2024 firm table."""
    firm = (
        answers.groupby("cdp_disclosing_org_number")
        [["disclosing_organization", "isin", "primary_industry_name"]]
        .first()
        .reset_index()
    )
    for question in ("Q7.55.2", "Q7.55.3", "Q7.55.4"):
        stem = question.lower().replace(".", "_")
        path = OUTPUT_DIR / f"{stem}_assignments.csv.gz"
        if not path.exists():
            continue
        rows = pd.read_csv(
            path, usecols=["cdp_disclosing_org_number", "cluster"]
        )
        grouped = rows.groupby("cdp_disclosing_org_number")
        counts = grouped.agg(
            response_rows=("cluster", "size"),
            assigned_rows=("cluster", lambda values: values.ne(-1).sum()),
        )
        assigned = rows.loc[rows["cluster"].ne(-1)]
        dominant = (
            assigned.groupby("cdp_disclosing_org_number")["cluster"]
            .agg(lambda values: values.value_counts().index[0])
            .rename("dominant_topic")
        )
        counts = counts.join(dominant).reset_index()
        counts = counts.rename(
            columns={column: f"{stem}_{column}" for column in counts if column != "cdp_disclosing_org_number"}
        )
        firm = firm.merge(counts, on="cdp_disclosing_org_number", how="left")

    stage_path = OUTPUT_DIR / "q7_55_1_stage_profile_assignments.csv"
    if stage_path.exists():
        stages = pd.read_csv(
            stage_path, usecols=["cdp_disclosing_org_number", "cluster"]
        ).rename(columns={"cluster": "q7_55_1_stage_cluster"})
        firm = firm.merge(stages, on="cdp_disclosing_org_number", how="left")

    project_path = OUTPUT_DIR / "q7_56_described_projects.csv"
    if project_path.exists():
        projects = pd.read_csv(project_path)
        project_counts = (
            projects.groupby("cdp_disclosing_org_number")
            .size()
            .rename("q7_56_described_projects")
            .reset_index()
        )
        firm = firm.merge(project_counts, on="cdp_disclosing_org_number", how="left")

    firm.insert(0, "year", 2024)
    firm.to_csv(OUTPUT_DIR / "company_2024_topic_profile.csv.gz", index=False)
    print(f"Company-level topic index: {len(firm):,} CDP organizations")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--question",
        choices=["all", "Q7.55.1", "Q7.55.2", "Q7.55.3", "Q7.55.4", "Q7.56"],
        default="all",
        help="Run one question as a trial, or all five (default).",
    )
    args = parser.parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cells, answers = load_rows()
    print(f"Read {len(cells):,} public response cells from {len(answers):,} form rows")

    text_questions = [
        ("Q7.55.2", "col9", 80, 30),
        ("Q7.55.3", "col2", 80, 30),
        ("Q7.55.4", "col1", 80, 15),
    ]
    if args.question != "all":
        text_questions = [item for item in text_questions if item[0] == args.question]
    if text_questions:
        torch.set_num_threads(min(8, torch.get_num_threads()))
        try:
            embedder = SentenceTransformer(
                EMBEDDING_MODEL, device="cpu", local_files_only=True
            )
        except (OSError, TypeError):
            embedder = SentenceTransformer(EMBEDDING_MODEL, device="cpu")
    for question, field, minimum_length, minimum_topic_size in text_questions:
        assignments, summary, examples = cluster_text(
            answers, question, field, minimum_length, minimum_topic_size, embedder
        )
        stem = question.lower().replace(".", "_")
        assignments.to_csv(OUTPUT_DIR / f"{stem}_assignments.csv.gz", index=False)
        summary.to_csv(OUTPUT_DIR / f"{stem}_cluster_summary.csv", index=False)
        examples.to_csv(OUTPUT_DIR / f"{stem}_representative_answers.csv", index=False)
        print(
            f"{question}: clustered {len(assignments):,} narrative rows "
            f"from {assignments['cdp_disclosing_org_number'].nunique():,} companies"
        )
        print(summary.to_string(index=False, max_colwidth=65))

    if args.question in {"all", "Q7.55.1"}:
        profiles, profile_summary = cluster_stage_profiles(answers)
        profiles.to_csv(OUTPUT_DIR / "q7_55_1_stage_profile_assignments.csv", index=False)
        profile_summary.to_csv(OUTPUT_DIR / "q7_55_1_stage_profile_summary.csv", index=False)
        print(f"Q7.55.1: clustered {len(profiles):,} complete company stage profiles")
        print(profile_summary.to_string(index=False))

    if args.question in {"all", "Q7.56"}:
        projects = answers.loc[
            answers["question_number"].eq("Q7.56")
            & answers["col6"].fillna("").str.len().ge(80)
        ].copy()
        projects.to_csv(OUTPUT_DIR / "q7_56_described_projects.csv", index=False)
        print(
            f"Q7.56: exported {len(projects)} described projects without "
            "fitting an unstable cluster model on such a small sample"
        )

    existing_summaries = [
        OUTPUT_DIR / f"{question.lower().replace('.', '_')}_cluster_summary.csv"
        for question in ("Q7.55.2", "Q7.55.3", "Q7.55.4")
    ]
    existing_summaries = [path for path in existing_summaries if path.exists()]
    if existing_summaries:
        pd.concat(
            [pd.read_csv(path) for path in existing_summaries], ignore_index=True
        ).to_csv(OUTPUT_DIR / "all_text_cluster_summary.csv", index=False)
    build_company_topic_profile(answers)
    print(f"Saved results to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()

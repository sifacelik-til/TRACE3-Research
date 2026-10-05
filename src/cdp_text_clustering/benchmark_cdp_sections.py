"""Matched four-encoder section benchmark, locked verification, and deployment driver."""

from __future__ import annotations

if __name__ == "__main__":
    import torch  # Initialize the Windows inference DLLs before NumPy.

from src.cdp_text_clustering.encode_cdp_section_fields import encode_benchmark, record_environment, section_codebook, MODELS

import argparse
import json
import logging
import os
import sqlite3
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import silhouette_score
from threadpoolctl import threadpool_limits

from src.cdp_extraction.cdp_section_fields import (
    OUTPUT, ROOT, benchmark_sample, file_digest, prepare, read_fields, write_json,
)
from src.cdp_text_clustering.cluster_cdp_fields_by_sector import fit_cohort, hybrid_features

LOGGER = logging.getLogger(__name__)
REPORT = ROOT / "reports" / "cdp_text_clustering" / "cdp_sections_encoder_benchmark_msom.tex"


def partition_score(reference_spaces: dict[str, object], labels: np.ndarray) -> dict:
    if len(labels) < 3 or not 2 <= len(set(labels)) < len(labels):
        return {"score": -1.0, "status": "undefined_partition", "space_scores": {}}
    scores = {name: float(silhouette_score(matrix, labels, metric="cosine"))
              for name, matrix in reference_spaces.items()}
    return {"score": float(np.mean(list(scores.values()))), "status": "defined",
            "space_scores": scores}


def paired_cohort_interval(differences: pd.DataFrame, *, draws: int = 2000) -> tuple[float, float]:
    rng = np.random.default_rng(20261001)
    samples = []
    for _, rows in differences.groupby("goal", sort=True):
        values = rows.difference.to_numpy(dtype=float)
        samples.append(rng.choice(values, size=(draws, len(values)), replace=True).mean(axis=1))
    distribution = np.mean(samples, axis=0)
    # Three competitors: Bonferroni-adjusted descriptive bootstrap interval.
    return tuple(float(x) for x in np.quantile(distribution, [0.05 / 6, 1 - 0.05 / 6]))


def choose_encoder(metrics: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    complete = metrics[metrics["mode"].eq("complete")]
    goal_scores = complete.groupby(["encoder", "split", "goal"], as_index=False).score.mean()
    ranking = goal_scores.groupby(["encoder", "split"], as_index=False).score.mean()
    selected = ranking[ranking.split.eq("selection")].sort_values(
        ["score", "encoder"], ascending=[False, True]).iloc[0]
    if selected.score <= -1:
        raise ValueError("No encoder has an evaluable selection partition; increase the matched sample")
    winner = selected.encoder
    verification = complete[complete.split.eq("verification")]
    winner_rows = verification[verification.encoder.eq(winner)][["cohort", "goal", "score"]]
    comparisons = []
    for competitor in sorted(set(complete.encoder) - {winner}):
        other = verification[verification.encoder.eq(competitor)][["cohort", "score"]]
        paired = winner_rows.merge(other, on="cohort", validate="one_to_one", suffixes=("_winner", "_other"))
        paired["difference"] = paired.score_winner - paired.score_other
        lower, upper = paired_cohort_interval(paired)
        comparisons.append({
            "competitor": competitor, "verification_macro_difference": float(
                paired.groupby("goal").difference.mean().mean()),
            "descriptive_interval_lower": lower, "descriptive_interval_upper": upper,
        })
    confirmed = bool(comparisons) and all(row["descriptive_interval_lower"] > 0 for row in comparisons)
    return {
        "selected_encoder": winner, "selection_macro_score": float(selected.score),
        "verification_confirmed": confirmed,
        "choice_status": "verification_supported_operational_choice" if confirmed else "provisional_best_selection_score",
        "comparisons": comparisons,
        "selection_rule": "Equal-goal mean of cohort scores, each the equal-weight silhouette in four complete-encoder spaces and training-fitted TF-IDF; undefined/unsupported partitions score -1.",
        "verification_rule": "Winner is frozen before verification; paired, goal-stratified cohort bootstrap versus all three rivals. No switching to the verification winner.",
        "caution": "Cohorts can share companies. Bootstrap intervals are descriptive robustness diagnostics, not independent-sample inferential confidence intervals or human coding accuracy.",
    }, ranking


def evaluate(output: Path = OUTPUT) -> dict:
    fields = read_fields(output / "sample_fields.jsonl")
    complete, prefix = {}, {}
    for key in MODELS:
        folder = output / "encoders" / key
        state = json.loads((folder / "benchmark_complete.json").read_text())
        if state["sample_sha256"] != file_digest(output / "sample_fields.jsonl"):
            raise ValueError("Encoder sample fingerprint mismatch")
        complete[key] = np.load(folder / "complete.npy", allow_pickle=False)
        prefix[key] = np.load(folder / "prefix.npy", allow_pickle=False)
        for matrix in (complete[key], prefix[key]):
            if len(matrix) != len(fields) or not np.isfinite(matrix).all():
                raise ValueError("Encoder matrices are not aligned to the matched sample")
    design = {
        "sample_sha256": file_digest(output / "sample_fields.jsonl"),
        "selection_split": "selection", "verification_split": "verification",
        "max_clusters": 16, "minimum_cluster_size": 3, "granularity_tolerance": 0.02,
        "semantic_weight": 0.7, "seeds": [42, 123, 2026],
        "reference_spaces": [*MODELS, "tfidf"], "undefined_score": -1,
        "aggregation": "equal weight per goal, then equal weight per cohort",
        "bootstrap": "2000 paired goal-stratified cohort draws; descriptive adjusted intervals",
    }
    path = output / "benchmark_design.json"
    if path.exists() and json.loads(path.read_text()) != design:
        raise ValueError("Benchmark design changed; choose a new output directory")
    write_json(path, design)
    metrics, space_rows, searches = [], [], []
    assignments = []
    model_dir = output / "benchmark_models"
    model_dir.mkdir(exist_ok=True)
    cohorts = sorted({row["cohort"] for row in fields})
    with threadpool_limits(limits=2):
        for cohort in cohorts:
            indices = np.array([i for i, row in enumerate(fields) if row["cohort"] == cohort])
            original = [fields[i] for i in indices]
            rows = [{**row, "split": "train" if row["split"] == "train" else "holdout"}
                    for row in original]
            train = [i for i, row in enumerate(original) if row["split"] == "train"]
            _, common_vectorizer = hybrid_features(
                complete["minilm"][indices[train]], [original[i]["text"] for i in train], fit=True)
            if common_vectorizer is None:
                raise ValueError("Benchmark reference cohort has no lexical vocabulary")
            lexical = common_vectorizer.transform([row["text"] for row in original])
            for key in MODELS:
                for mode, all_vectors in (("complete", complete[key]), ("prefix", prefix[key])):
                    vectors = {row["field_id"]: all_vectors[index]
                               for row, index in zip(rows, indices)}
                    fitted = fit_cohort(rows, vectors, max_clusters=16, min_cluster_size=3, tolerance=0.02)
                    searches.extend({"cohort": cohort, "encoder": key, "mode": mode, **trial}
                                    for trial in fitted["trials"])
                    predicted = None
                    if fitted["status"] == "clustered":
                        features, _ = hybrid_features(
                            all_vectors[indices], [row["text"] for row in rows], fitted["vectorizer"])
                        predicted = fitted["model"].predict(features)
                        model_name = f"{key}_{mode}_{cohorts.index(cohort):03d}.joblib"
                        joblib.dump({
                            "cohort": cohort, "encoder": key, "mode": mode,
                            "model": fitted["model"], "vectorizer": fitted["vectorizer"],
                            "fit_field_ids": [row["field_id"] for row in fitted["fit_rows"]],
                        }, model_dir / model_name)
                    for split in ("selection", "verification"):
                        local = np.array([i for i, row in enumerate(original) if row["split"] == split])
                        reference = {
                            name: matrix[indices[local]] for name, matrix in complete.items()
                        }
                        reference["tfidf"] = lexical[local]
                        outcome = (partition_score(reference, predicted[local]) if predicted is not None else
                                   {"score": -1.0, "status": fitted["status"], "space_scores": {}})
                        entry = {
                            "cohort": cohort, "goal": original[0]["goal"], "encoder": key,
                            "mode": mode, "split": split, "fields": len(local),
                            "selected_k": fitted.get("k", 0), "seed_ari": fitted.get("seed_ari"),
                            "score": outcome["score"], "metric_status": outcome["status"],
                            "train_fit_status": fitted["status"],
                        }
                        metrics.append(entry)
                        space_rows.extend({**entry, "reference_space": space, "silhouette": score}
                                          for space, score in outcome["space_scores"].items())
                    if predicted is not None:
                        assignments.extend({
                            "field_id": row["field_id"], "cohort": cohort, "encoder": key,
                            "mode": mode, "split": row["split"], "cluster": int(label),
                        } for row, label in zip(original, predicted))
            LOGGER.info("Compared complete/prefix encoders: %s", cohort)
    frame = pd.DataFrame(metrics)
    frame.to_csv(output / "cohort_metrics.csv", index=False)
    pd.DataFrame(space_rows).to_csv(output / "cross_space_metrics.csv", index=False)
    pd.DataFrame(searches).to_csv(output / "granularity_search.csv", index=False)
    pd.DataFrame(assignments).to_csv(output / "benchmark_assignments.csv", index=False)
    selection, ranking = choose_encoder(frame)
    ranking.to_csv(output / "encoder_ranking.csv", index=False)
    frame.groupby(["encoder", "mode", "split"], as_index=False).agg(
        macro_score=("score", "mean"), defined_cohorts=("metric_status", lambda x: (x == "defined").sum()),
    ).to_csv(output / "complete_vs_prefix.csv", index=False)
    write_json(output / "selection.json", selection)
    return selection


def verify_benchmark(output: Path = OUTPUT) -> dict:
    fields = read_fields(output / "sample_fields.jsonl")
    registry = {row["field_id"]: row for row in fields}
    if len(registry) != len(fields):
        raise ValueError("Duplicate benchmark field IDs")
    groups = {split: {row["connected_group"] for row in fields if row["split"] == split}
              for split in ("train", "selection", "verification")}
    if any(groups[first] & groups[second] for first, second in (
        ("train", "selection"), ("train", "verification"), ("selection", "verification"))):
        raise ValueError("Connected-company split leakage")
    texts = {split: {row["normalized_sha256"] for row in fields if row["split"] == split}
             for split in groups}
    if texts["train"] & (texts["selection"] | texts["verification"]) or texts["selection"] & texts["verification"]:
        raise ValueError("Exact-text leakage in evaluation sample")
    coverage = {}
    for key in MODELS:
        folder = output / "encoders" / key
        audit = pd.read_csv(folder / "coverage_audit.csv")
        if audit.field_id.tolist() != [row["field_id"] for row in fields]:
            raise ValueError("Coverage ledger identity mismatch")
        if not audit.source_characters.eq(audit.covered_characters).all() or audit.max_chunk_tokens.max() > 128:
            raise ValueError("Coverage or token-budget verification failed")
        complete = np.load(folder / "complete.npy", allow_pickle=False)
        prefix = np.load(folder / "prefix.npy", allow_pickle=False)
        for vectors in (complete, prefix):
            if not np.isfinite(vectors).all() or not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-4):
                raise ValueError("Non-unit or nonfinite embeddings")
        with sqlite3.connect(folder / "text_cache.sqlite3") as connection:
            for i, field in enumerate(fields):
                cached = connection.execute(
                    "SELECT vector,prefix_vector FROM texts WHERE text_hash=?",
                    (field["text_sha256"],),
                ).fetchone()
                if cached is None or cached[1] is None:
                    raise ValueError("Missing exact-text encoder cache entry")
                if not np.array_equal(complete[i], np.frombuffer(cached[0], dtype="float32")):
                    raise ValueError("Complete embedding is assigned to the wrong exact source text")
                if not np.array_equal(prefix[i], np.frombuffer(cached[1], dtype="float32")):
                    raise ValueError("Prefix embedding is assigned to the wrong exact source text")
        single = audit.chunks.eq(1).to_numpy()
        if not np.allclose(complete[single], prefix[single], atol=1e-4):
            raise ValueError("Single-chunk fields differ from their matched prefix comparator")
        coverage[key] = {"fields": len(audit), "chunks": int(audit.chunks.sum()),
                         "single_chunk_comparisons": int(single.sum()), "all_characters_retained": True}
    fitted_models = 0
    for path in (output / "benchmark_models").glob("*.joblib"):
        bundle = joblib.load(path)
        fit_rows = [registry[field_id] for field_id in bundle["fit_field_ids"]]
        if any(row["split"] != "train" or row["cohort"] != bundle["cohort"] for row in fit_rows):
            raise ValueError("Saved model crosses fitting split or sector/field cohort")
        vectorizer = bundle["vectorizer"]
        if vectorizer is not None:
            analyzer = vectorizer.build_analyzer()
            tokens = {token for row in fit_rows for token in analyzer(row["text"])}
            if not set(vectorizer.vocabulary_) <= tokens:
                raise ValueError("Vocabulary contains non-training tokens")
        fitted_models += 1
    recomputed, _ = choose_encoder(pd.read_csv(output / "cohort_metrics.csv"))
    chosen = json.loads((output / "selection.json").read_text())
    if recomputed["selected_encoder"] != chosen["selected_encoder"] or recomputed["verification_confirmed"] != chosen["verification_confirmed"]:
        raise ValueError("Selected model cannot be reproduced from saved metrics")
    result = {
        "sample_sha256": file_digest(output / "sample_fields.jsonl"),
        "selection_sha256": file_digest(output / "selection.json"),
        "connected_company_splits_disjoint": True, "evaluation_text_duplicates_excluded": True,
        "coverage": coverage, "training_only_models_checked": fitted_models,
        "selection_reproduced": True, "human_coding_accuracy_verified": False,
    }
    write_json(output / "verification_checks.json", result)
    return result


def latex_escape(value) -> str:
    text = str(value)
    replacements = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
                    "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}"}
    return "".join(replacements.get(char, char) for char in text)


def render_report(output: Path = OUTPUT, report: Path = REPORT) -> None:
    data_path = output / "data_manifest.json"
    data = json.loads(data_path.read_text(encoding="utf-8")) if data_path.exists() else {}
    sample_path = output / "sample_manifest.json"
    sample = json.loads(sample_path.read_text()) if sample_path.exists() else {}
    selection_path = output / "selection.json"
    selection = json.loads(selection_path.read_text()) if selection_path.exists() else None
    full_path = output / "full" / "completion.json"
    full = json.loads(full_path.read_text()) if full_path.exists() else None
    progress_path = output / "full" / "progress.json"
    progress = json.loads(progress_path.read_text()) if progress_path.exists() else None
    failure_path = output / "failure.json"
    failure = json.loads(failure_path.read_text()) if failure_path.exists() else None
    ranking_path = output / "encoder_ranking.csv"
    figure_tex = ""
    figure_manifest = output / "figures" / "figure_manifest.json"
    if figure_manifest.exists() and selection_path.exists():
        figures = json.loads(figure_manifest.read_text(encoding="utf-8"))
        expected = {
            "selection_sha256": file_digest(selection_path),
            "metrics_sha256": file_digest(output / "cohort_metrics.csv"),
            "ranking_sha256": file_digest(ranking_path),
            "ablation_sha256": file_digest(output / "complete_vs_prefix.csv"),
        }
        if any(figures.get(name) != value for name, value in expected.items()):
            raise ValueError("Benchmark figures are stale; regenerate them before rendering the report")
        captions = {
            "encoder_selection_verification": (
                "Locked encoder selection and separate verification. Values are equal-goal macro scores "
                "including the declared $-1$ penalty for unsupported or undefined partitions. "
                "Verification does not confirm superiority over all rivals."),
            "encoder_cohort_scores": (
                "Heterogeneity across sector/source-field cohorts. Circles show selection, squares "
                "verification; points at $-1$ represent undefined or unsupported partitions, "
                "not a measured silhouette."),
            "encoder_complete_vs_prefix": (
                "Complete-text aggregation versus truncated-prefix comparison on identical fields. "
                "Bar labels give the number of defined cohorts out of 16; scores include $-1$ penalties."),
            "encoder_runtime_and_truncation": (
                "Observed CPU chunk-and-prefix encoding time and share of fields whose original "
                "input exceeds the common 128-token cap. Runtime is hardware-specific."),
        }
        relative = Path(os.path.relpath(output / "figures", report.parent)).as_posix()
        if set(figures["plots"]) != set(captions):
            raise ValueError("Benchmark figures are incomplete")
        for name in figures["plots"]:
            if not (output / "figures" / f"{name}.pdf").exists():
                raise FileNotFoundError(f"Benchmark figure missing: {name}")
            figure_tex += (
                "\n\\begin{figure}[!htbp]\n\\centering\n"
                f"\\includegraphics[width=0.94\\textwidth]{{{relative}/{name}.pdf}}\n"
                f"\\caption{{{captions[name]}}}\n"
                f"\\label{{fig:{name}}}\n\\end{{figure}}\n"
            )
    table = []
    ranking = pd.read_csv(ranking_path) if ranking_path.exists() else None
    for key, name in (("minilm", "MiniLM"), ("e5", "E5-base"), ("bge_m3", "BGE-M3"), ("qwen3", "Qwen3-0.6B")):
        state_path = output / "encoders" / key / "benchmark_complete.json"
        if not state_path.exists():
            table.append(f"{name} & Pending & -- & -- & -- \\\\")
            continue
        state = json.loads(state_path.read_text())
        score = {}
        if ranking is not None:
            score = dict(zip(ranking[ranking.encoder.eq(key)].split, ranking[ranking.encoder.eq(key)].score))
        formatted = [f"{score[split]:.4f}" if split in score else "--" for split in ("selection", "verification")]
        table.append(f"{name} & Complete & {state['chunk_and_prefix_compute_seconds']:.1f} & "
                     + " & ".join(formatted) + r" \\")
    if selection:
        choice = (
            "The locked selection rule chooses \\textbf{" + latex_escape(MODELS[selection["selected_encoder"]])
            + "}. The verification status is \\textbf{" + latex_escape(selection["choice_status"]) + "}."
        )
        if not selection["verification_confirmed"]:
            choice += (" The independent diagnostic does not establish superiority over all competitors. "
                       "Deployment uses the best observed selection score provisionally, not a proven universal winner.")
        comparisons = "\n".join(
            latex_escape(row["competitor"]) + f" & {row['verification_macro_difference']:.4f} & "
            + f"[{row['descriptive_interval_lower']:.4f}, {row['descriptive_interval_upper']:.4f}]" + r" \\"
            for row in selection["comparisons"])
        verification_table = (r"\begin{tabular}{lrr}Comparator & Difference & Descriptive interval \\ \hline"
                              + "\n" + comparisons + "\n" + r"\end{tabular}")
    else:
        choice = r"\textbf{Model selection is pending. No encoder has yet been established as the winner.}"
        verification_table = "Verification is pending; no comparative estimates are fabricated."
    if full:
        deployment = (
            f"Full processing is complete for {full['fields']:,} eligible fields. "
            f"There are {full['clustered_fields']:,} model assignments and {full['clusters']:,} "
            "sector--field clusters. Remaining records retain explicit unclustered statuses. "
            f"The evidence export contains {full['coding_candidates']:,} pending code--span suggestions."
        )
    elif progress:
        deployment = (
            r"\textbf{Full-corpus deployment is not complete.} "
            + f"The last recorded stage is {latex_escape(progress['stage'])}; "
            + f"{progress.get('encoded_fields', 0):,} of {data.get('available_fields', 0):,} fields "
            + "have completed checkpointed encoding. These are progress counts, not final clustering results."
        )
    else:
        deployment = r"\textbf{Full-corpus clustering has not completed; no full-data results are claimed.}"
    if failure:
        deployment = (
            r"\textbf{Last recorded execution failure:} "
            + latex_escape(failure["stage"] + ": " + failure["message"]) + ". "
            + deployment
        )
    year_rows = "\n".join(f"{year} & {count:,}" + r" \\" for year, count in data.get("year_counts", {}).items())
    text = r"""\documentclass[12pt]{article}
\usepackage[margin=1in]{geometry}
\usepackage{amsmath,booktabs,hyperref,setspace,graphicx}
\doublespacing
\title{Measuring Operational Climate Responses from Corporate Disclosures:
A Sector-Specific, Complete-Text Encoder Benchmark}
\author{Anonymous methodological manuscript}
\date{1 October 2026}
\begin{document}
\maketitle
\begin{abstract}
We develop a reproducible measurement pipeline for corporate emissions-reduction
strategies, climate risks and opportunities, and value-chain engagement.
The design preserves separate answer fields, encodes complete text through
lossless chunking and token-weighted response-level aggregation, and fits
sector-specific semantic--lexical clusters. Four multilingual encoders are
compared on identical connected-company-separated data. Model selection and
verification use separate companies and a common set of evaluation spaces.
Evidence-linked multi-label suggestions remain distinct from validated human
annotations. All numerical results below are read from completed local artifacts;
unfinished stages are explicitly identified.
\end{abstract}
\noindent\textbf{Keywords:} sustainable operations; supply chains; climate disclosure;
text measurement; clustering; reproducibility.

\section{Operations-management motivation and estimand}
Operational climate responses may involve equipment, energy sourcing, logistics,
supplier relationships, or resilience investments. A single disclosure can
describe several mechanisms; a single company can submit many distinct answers.
Our measurement unit is an extracted response/source-field pair, not a company,
sentence, chunk, or accepted action. Clustering is exploratory organization of
answers, not a causal estimate of abatement or an independently validated measure
of operational capability. Initiative savings and target statements are reported
claims and can refer to planned rather than realized changes.

\section{Data and scope}
The inputs are the targets/performance, risks/opportunities, and engagement
section datasets. We retain disclosure years 2020--2025, rather than interpreting
disclosure year as a financial or emissions reporting period. Verification,
carbon-pricing, assessment-process, numerical-only and unrelated questionnaire
rows are outside the specified narrative scope. Detailed field eligibility,
blank/placeholder counts and original source coordinates are retained.
Explicitly unspecified environmental records remain flagged; they are not
silently relabeled as climate-specific.
""" + (
        f"\nThe source files contain {data.get('source_rows_2020_2025', 0):,} rows in the six-year window. "
        f"The registry contains {data.get('available_fields', 0):,} eligible nonblank answer fields "
        f"and {data.get('unique_texts', 0):,} distinct exact texts.\n"
    ) + r"""
\begin{center}\begin{tabular}{lr}\toprule
Disclosure year & Eligible fields \\\midrule
""" + year_rows + r"""
\bottomrule\end{tabular}\end{center}

Risk descriptions, opportunity descriptions, response strategies and combined
response/cost explanations are separate fields. Legacy combined fields are not
artificially split into raw cells. Targets and initiative explanations are not
concatenated. Engagement detail, effect, coverage rationale and compliance
explanations retain separate identities. Multi-select values are represented as
stored in the extracted CSV; character offsets refer to that exact stored field,
not the original spreadsheet layout or a translated answer.

\section{Leakage control and matched sample}
We connect CDP accounts sharing a FactSet entity, Trucost company, or LSEG ISIN
over the study window. Connected components are deterministically assigned to
training, selection or verification pools using a fixed hash, with 60/20/20
population allocation probabilities. Allocation probabilities need not equal
realized field shares. All years of a linked component remain in one pool.
Evaluation texts identical after case/whitespace normalization to any training
text are excluded from evaluation sampling; verification also excludes matches
to selection-pool texts. This does not eliminate near-duplicate language.

The bounded comparison uses two high-support reported industries for each of
eight primary goal/field combinations: initiative details and target plans;
risk descriptions and responses; opportunity descriptions and responses; and
engagement details and effects. Fields are sampled cyclically across available
years within each cohort and split. Questionnaire changes mean that not every
field exists in every year. This is company-separated verification across the
study period, not an out-of-time forecasting experiment.
""" + (
        f"\nThe matched sample has {sample.get('fields', 0):,} fields across "
        f"{sample.get('cohorts', 0)} sector/field cohorts. The per-cohort budgets are "
        + latex_escape(str(sample.get("budgets", {}))) + ".\n"
    ) + r"""
The common primary-field benchmark does not establish encoder superiority for
rare sectors, all supplemental fields, every language, or every questionnaire
pathway. These are external-validity limitations, not reasons to hide records.

\section{Complete-text representations}
We compare multilingual MiniLM-L12-v2, multilingual E5-base, BGE-M3 and
Qwen3-Embedding-0.6B using pinned local revisions and CPU float32 inference.
No answer text is sent to a remote service. E5 uses its query prefix; Qwen3 uses
one fixed clustering instruction. Prompt and encoder are therefore evaluated
jointly. All models use a 128-input-token chunk budget, including special tokens
and prompts, respecting MiniLM's distributed limit. This is a controlled
protocol, not a test of the larger models' maximum long-context capability.

For field $i$, lossless nonoverlapping chunks retain every original character.
Sentence boundaries are preferred; tokenizer-checked character/whitespace
fallback handles oversized sentences. Offsets are zero-based Unicode character
indices with an exclusive end. Let $z_{ij}$ be normalized chunk embeddings and
$w_{ij}$ the positive content-token counts. The field representation is
\[
 x_i=\frac{\sum_j w_{ij}z_{ij}}{\left\|\sum_j w_{ij}z_{ij}\right\|_2}.
\]
Chunking changes tokenization at boundaries and weighted averaging may blur
multiple mechanisms. Neither issue is hidden by treating chunks as independent
observations. A matched ablation encodes only the truncated prefix of the same
field, using the same encoder, prompt, split and clustering procedure.

\section{Sector-specific clustering and model selection}
Reported CDP primary industry is the consistent broad sector level; detailed
primary sector remains metadata. Missing or unrecognized sectors do not enter
pooled fallback clusters. Within each sector/goal/source-field cohort, training-only
word/bigram TF--IDF augments the semantic representation:
\[
 h_i=\operatorname{normalize}
 [\sqrt{0.7}\,x_i;\sqrt{0.3}\,t_i].
\]
Duplicate normalized training texts contribute one fitting observation.
K-means considers $k=2,\ldots,16$, bounded by sample size, with seeds 42, 123
and 2026 and ten initializations per seed. Every accepted partition must have
at least three unique training fields and two companies in each cluster in every
seed. The largest supported $k$ within 0.02 of the best positive mean training
cosine silhouette is selected. Sparse or unsupported cohorts are explicitly
unclustered. Names use distinctive training terms, not holdout labels.

Selection evaluates each partition in the same five reference spaces: the four
complete encoder spaces and training-fitted TF--IDF. Each cohort score averages
these five cosine silhouettes. Undefined or unsupported partitions score $-1$,
making the ranking explicitly coverage-adjusted rather than selectively omitting
hard cases. Scores are averaged within each of four goals and then equally
across goals. This reduces dependence on an encoder's own geometry but is not an
external ground truth. The lexical reference is also part of the hybrid feature
design, an acknowledged source of criterion dependence.

The best selection score determines the operational choice before verification.
Verification repeats the fixed evaluation on disjoint connected companies.
Paired, goal-stratified bootstrap resampling of cohorts supplies descriptive
robustness intervals against all three rivals, with adjusted tail probabilities.
Because cohorts may share companies, these are not independent-cluster
inferential confidence intervals. A negative result does not trigger a switch
to whichever encoder looks best on verification.

\section{Observed benchmark results}
\begin{center}\small
\begin{tabular}{llrrr}\toprule
Encoder & Encoding & Seconds & Selection & Verification \\\midrule
""" + "\n".join(table) + r"""
\bottomrule\end{tabular}\end{center}
Seconds cover checkpointed chunk-plus-prefix computation, not a hardware-neutral
speed claim. Undefined metrics carry the declared penalty; they are not zeros.
Cross-space scores, fitted granularity, seed stability and complete-versus-prefix
results are retained in machine-readable outputs for audit.

""" + figure_tex + "\n" + choice + "\n\n" + verification_table + r"""

\section{Full-corpus categorization and evidence-linked coding}
""" + deployment + r"""

For deployment, the selected encoder embeds every eligible field, with exact-text
cache reuse rather than a lexical surrogate. Sector-specific cluster fitting
uses at most 256 year-balanced unique training fields per cohort to bound
computation; every eligible field is predicted directly from its selected-encoder
representation. This fitting cap is explicit and does not imply every field was
used to fit centroids. Supplementary fields and less frequent sectors are covered
at deployment but were not all in the primary encoder comparison.

The expanded codebook includes concrete reduction and engagement mechanisms,
physical adaptation, business continuity and risk transfer. Applicable code
definitions are compared with each chunk, with insufficient-information
abstention and a maximum of two mechanism suggestions per chunk. Exact evidence
spans and similarities are retained; similarities are not probabilities. The
same field can have multiple code--span pairs. Whole-chunk suggestions require
human verification and, where appropriate, narrower evidence.
No AI proposal is marked as human accepted. Pending code-based sector groups
must not be confused with learned K-means clusters or accepted measurements.

\section{Validity, reproducibility and research use}
The benchmark cannot establish causal effects, realized emissions savings,
cross-language coding accuracy or economically meaningful action prevalence.
Before estimating downstream operations models, independent coders should label
a blinded sample with exact evidence, adjudicate disagreements, and estimate
per-code precision/recall and agreement. Company dependence, questionnaire
changes, sector coverage, temporal variation and environmental-unspecified
answers require sensitivity analysis. The selected encoder is an operational
choice under the recorded protocol, not a universal state-of-the-art ranking.

Source hashes, source coordinates, linkage/split rules, sample identities,
model revisions, exact chunk coverage, fit IDs, candidate scores and checkpoint
statuses are recorded locally. The code and licensed datasets have not been
uploaded or represented as publicly available. Authors must determine the
permitted data/code access statement before submission.

\paragraph{Manuscript status.}
This is an anonymous M\&SOM-oriented methodological draft, not a submission-ready
claim of validated empirical findings. It uses a portable article class because
the official journal class is not bundled with the repository. Transfer
the final verified manuscript to the current INFORMS author template and confirm
current submission requirements with the journal.

\section*{Reproduction}
From the repository root using the configured encoder environment:
\begin{verbatim}
python -m src.cdp_text_clustering.benchmark_cdp_sections --stage all
\end{verbatim}
Stages can be resumed separately with \texttt{prepare}, \texttt{encode},
\texttt{evaluate}, \texttt{deploy}, or \texttt{report}. The local output folder is
\path{data/outputs/cdp_text_clustering/cdp_sections_benchmark_2020_2025}.
Completion markers are written only after their stage succeeds.

\begin{thebibliography}{9}
\bibitem{silhouette} Rousseeuw, P. J. 1987. Silhouettes: A graphical aid to the
interpretation and validation of cluster analysis. \emph{Journal of Computational
and Applied Mathematics} 20, 53--65.
\bibitem{ari} Hubert, L., and P. Arabie. 1985. Comparing partitions.
\emph{Journal of Classification} 2, 193--218.
\bibitem{informs} INFORMS. Author information for \emph{Manufacturing \& Service
Operations Management}. \url{https://pubsonline.informs.org/journal/msom}.
\end{thebibliography}
\end{document}
"""
    report.parent.mkdir(parents=True, exist_ok=True)
    pending = report.with_suffix(".tex.pending")
    pending.write_text(text, encoding="utf-8")
    pending.replace(report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--stage", choices=("all", "prepare", "encode", "evaluate", "figures", "deploy", "report"), default="all")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        record_environment(args.output)
        if not (args.output / "codebook.json").exists():
            write_json(args.output / "codebook.json", {
                "status": "draft_for_human_review", "codes": section_codebook(),
            })
        if args.stage in {"all", "prepare"}:
            fields = prepare(args.output)
            benchmark_sample(fields, args.output)
            del fields
            write_json(args.output / "codebook.json", {"status": "draft_for_human_review", "codes": section_codebook()})
        render_report(args.output)
        if args.stage in {"all", "encode"}:
            for key in MODELS:
                encode_benchmark(key, args.output)
                render_report(args.output)
        if args.stage in {"all", "evaluate"}:
            evaluate(args.output)
            verify_benchmark(args.output)
            render_report(args.output)
        if args.stage in {"all", "figures"}:
            from src.cdp_text_clustering.plot_cdp_section_benchmark import plot
            plot(args.output)
            render_report(args.output)
        if args.stage in {"all", "deploy"}:
            from src.cdp_text_clustering.deploy_cdp_section_clusters import deploy
            deploy(args.output, progress_callback=lambda: render_report(args.output))
            render_report(args.output)
        if args.stage == "report":
            failure = args.output / "failure.json"
            if failure.exists() and json.loads(failure.read_text())["stage"] == "report":
                failure.unlink()
            render_report(args.output)
        failure = args.output / "failure.json"
        if failure.exists() and (args.stage == "all" or json.loads(failure.read_text())["stage"] == args.stage):
            failure.unlink()
    except Exception as exc:
        write_json(args.output / "failure.json", {
            "stage": args.stage, "exception": type(exc).__name__, "message": str(exc),
            "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        render_report(args.output)
        raise


if __name__ == "__main__":
    main()

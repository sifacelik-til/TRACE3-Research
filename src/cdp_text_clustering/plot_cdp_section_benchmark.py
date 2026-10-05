"""Reproducible, benchmark-only comparison figures; no model inference."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.cdp_extraction.cdp_section_fields import OUTPUT, file_digest, write_json

ENCODERS = ("minilm", "e5", "bge_m3", "qwen3")
LABELS = {"minilm": "MiniLM", "e5": "E5-base", "bge_m3": "BGE-M3", "qwen3": "Qwen3-0.6B"}
COLORS = {"minilm": "#3274a1", "e5": "#e1812c", "bge_m3": "#3a923a", "qwen3": "#a352a3"}
SPLITS = ("selection", "verification")
MODES = ("complete", "prefix")
GOALS = ("reduction", "risk", "opportunity", "engagement")
PENALTY = -1.0


def load_benchmark(output: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    metrics_path = output / "cohort_metrics.csv"
    ranking_path = output / "encoder_ranking.csv"
    ablation_path = output / "complete_vs_prefix.csv"
    selection_path = output / "selection.json"
    for path in (metrics_path, ranking_path, ablation_path, selection_path,
                 output / "verification_checks.json"):
        if not path.exists():
            raise FileNotFoundError(f"Completed verified benchmark required: {path}")
    metrics = pd.read_csv(metrics_path)
    ranking = pd.read_csv(ranking_path)
    ablation = pd.read_csv(ablation_path)
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    if not json.loads((output / "verification_checks.json").read_text())["selection_reproduced"]:
        raise ValueError("Encoder choice has not passed benchmark verification")
    expected = pd.MultiIndex.from_product(
        [ENCODERS, MODES, SPLITS], names=["encoder", "mode", "split"])
    cohorts = set(metrics.cohort)
    if len(cohorts) != 16 or set(metrics.goal) != set(GOALS):
        raise ValueError("Benchmark cohort/goal coverage differs from the matched design")
    counts = metrics.groupby(["encoder", "mode", "split"], dropna=False).size()
    if not counts.index.equals(expected.sort_values()) and (
        set(counts.index) != set(expected) or not counts.eq(len(cohorts)).all()
    ):
        raise ValueError("Benchmark metrics have missing/duplicate cohort results")
    for cohort, group in metrics.groupby("cohort"):
        if len(group) != len(expected) or group.goal.nunique() != 1:
            raise ValueError(f"Incomplete or inconsistent cohort: {cohort}")
    if not np.isfinite(metrics.score).all():
        raise ValueError("Nonfinite benchmark score")
    if not metrics.loc[metrics.metric_status.ne("defined"), "score"].eq(PENALTY).all():
        raise ValueError("Undefined partitions must retain the declared -1 penalty")
    if not metrics.loc[metrics.metric_status.eq("defined"), "score"].between(-1, 1).all():
        raise ValueError("Silhouette score outside [-1, 1]")
    if set(ranking.encoder) != set(ENCODERS) or set(ranking.split) != set(SPLITS):
        raise ValueError("Encoder ranking incomplete")
    if ranking.duplicated(["encoder", "split"]).any():
        raise ValueError("Duplicate encoder ranking")
    if set(ablation.set_index(["encoder", "mode", "split"]).index) != set(expected):
        raise ValueError("Complete/prefix comparison incomplete")
    if ablation.duplicated(["encoder", "mode", "split"]).any():
        raise ValueError("Duplicate complete/prefix comparison")
    if selection["selected_encoder"] not in ENCODERS:
        raise ValueError("Unknown selected encoder")
    recomputed = metrics.groupby(["encoder", "mode", "split", "goal"]).score.mean().groupby(
        ["encoder", "mode", "split"]).mean()
    for row in ablation.itertuples():
        if not np.isclose(row.macro_score, recomputed[row.encoder, row.mode, row.split]):
            raise ValueError("Ablation mean differs from cohort metrics")
        defined = metrics.loc[
            metrics.encoder.eq(row.encoder) & metrics["mode"].eq(row.mode)
            & metrics.split.eq(row.split) & metrics.metric_status.eq("defined")
        ]
        if row.defined_cohorts != len(defined):
            raise ValueError("Defined cohort count differs from cohort metrics")
    for row in ranking.itertuples():
        if not np.isclose(row.score, recomputed[row.encoder, "complete", row.split]):
            raise ValueError("Encoder ranking differs from cohort metrics")
    best = ranking[ranking.split.eq("selection")].sort_values(
        ["score", "encoder"], ascending=[False, True]).iloc[0].encoder
    if best != selection["selected_encoder"]:
        raise ValueError("Plotted winner differs from locked selection")
    return metrics, ranking, ablation, selection


def plot(output: Path = OUTPUT) -> dict:
    metrics, ranking, ablation, selection = load_benchmark(output)
    folder = output / "figures"
    folder.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                         "pdf.fonttype": 42, "savefig.dpi": 180})
    images = []

    fig, ax = plt.subplots(figsize=(7.5, 4.4))
    x = np.arange(len(ENCODERS))
    for offset, split in ((-0.18, "selection"), (0.18, "verification")):
        records = ranking.set_index(["encoder", "split"])
        scores = [records.loc[(key, split), "score"] for key in ENCODERS]
        bars = ax.bar(x + offset, scores, width=0.33,
                      color=[COLORS[key] for key in ENCODERS],
                      alpha=1 if split == "selection" else 0.48,
                      label=split.capitalize())
        for bar, score in zip(bars, scores):
            ax.annotate(f"{score:+.3f}", (bar.get_x() + bar.get_width() / 2, score),
                        xytext=(0, -12 if score < 0 else 3), textcoords="offset points",
                        ha="center", va="top" if score < 0 else "bottom", fontsize=8)
    ax.set_xticks(x, [LABELS[key] for key in ENCODERS])
    ax.set_ylim(min(-0.68, ranking.score.min() - 0.12), max(0.15, ranking.score.max() + 0.12))
    ax.axhline(0, color="#444444", linewidth=0.8)
    ax.set_ylabel("Equal-goal macro score (undefined partitions = -1)")
    ax.set_title("Locked selection and separate verification")
    ax.legend(frameon=False, ncol=2)
    fig.tight_layout()
    images.append(("encoder_selection_verification", fig))

    fig, axes = plt.subplots(2, 2, figsize=(10.5, 7), sharey=True)
    for ax, goal in zip(axes.flat, GOALS):
        subset = metrics[metrics.goal.eq(goal) & metrics["mode"].eq("complete")]
        goal_cohorts = sorted(subset.cohort.unique())
        positions = np.arange(len(goal_cohorts))
        offsets = np.linspace(-0.27, 0.27, len(ENCODERS))
        for key, offset in zip(ENCODERS, offsets):
            for split, marker, shift in (("selection", "o", -0.028), ("verification", "s", 0.028)):
                rows = subset[subset.encoder.eq(key) & subset.split.eq(split)].set_index("cohort")
                values = rows.loc[goal_cohorts, "score"].to_numpy()
                ax.scatter(positions + offset + shift, values, color=COLORS[key],
                           marker=marker, s=28, alpha=0.82, label=f"{LABELS[key]} {split}")
        ax.axhline(PENALTY, color="#777777", ls=":", linewidth=0.8)
        ax.axhline(0, color="#777777", linewidth=0.7)
        ax.set_xticks(positions, [name.split("|")[-1] + "\n" + name.split("|")[1].replace("_", " ")
                                  for name in goal_cohorts], fontsize=7)
        ax.set_title(goal.capitalize())
        ax.set_ylim(-1.13, 0.65)
    axes[0, 0].set_ylabel("Cohort score (penalty at -1)")
    axes[1, 0].set_ylabel("Cohort score (penalty at -1)")
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=4, fontsize=8, frameon=False)
    fig.suptitle("Sector / source-field heterogeneity: complete text", y=0.99)
    fig.tight_layout(rect=(0, 0.10, 1, 0.98))
    images.append(("encoder_cohort_scores", fig))

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.1), sharey=True)
    for ax, split in zip(axes, SPLITS):
        group = ablation[ablation.split.eq(split)].set_index(["encoder", "mode"])
        x = np.arange(len(ENCODERS))
        for mode, offset, alpha in (("complete", -0.18, 1), ("prefix", 0.18, 0.48)):
            values = [group.loc[(key, mode), "macro_score"] for key in ENCODERS]
            counts = [group.loc[(key, mode), "defined_cohorts"] for key in ENCODERS]
            bars = ax.bar(x + offset, values, width=0.33,
                          color=[COLORS[key] for key in ENCODERS], alpha=alpha,
                          label="Complete text" if mode == "complete" else "Truncated prefix")
            for bar, n in zip(bars, counts):
                y = bar.get_height()
                ax.annotate(f"{n}/16", (bar.get_x() + bar.get_width() / 2, y),
                            xytext=(0, -12 if y < 0 else 3), textcoords="offset points",
                            ha="center", va="top" if y < 0 else "bottom", fontsize=8)
        ax.set_title(split.capitalize())
        ax.set_xticks(x, [LABELS[key] for key in ENCODERS], rotation=20)
        ax.axhline(0, color="#444444", linewidth=0.8)
    axes[0].set_ylabel("Macro score (undefined partitions = -1)")
    axes[0].set_ylim(min(-0.8, ablation.macro_score.min() - 0.16), 0.2)
    axes[0].legend(frameon=False, loc="lower left")
    fig.suptitle("Complete fields vs. truncated prefixes; labels show defined cohorts")
    fig.tight_layout()
    images.append(("encoder_complete_vs_prefix", fig))

    seconds, chunks, truncation = [], [], []
    for key in ENCODERS:
        state = json.loads((output / "encoders" / key / "benchmark_complete.json").read_text())
        if state["fields"] != 768 or not state["all_characters_covered"]:
            raise ValueError("Missing/incomplete encoder chunk coverage")
        seconds.append(state["chunk_and_prefix_compute_seconds"])
        chunks.append(state["chunks"])
        truncation.append(state["prefix_truncation_fraction"])
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.8))
    x = np.arange(len(ENCODERS))
    axes[0].bar(x, np.asarray(seconds) / 60, color=[COLORS[key] for key in ENCODERS])
    axes[0].set_ylabel("Chunk + prefix inference time (minutes)")
    axes[0].set_title("Observed CPU time on 768 fields")
    axes[1].bar(x, np.asarray(truncation) * 100, color=[COLORS[key] for key in ENCODERS])
    axes[1].set_ylabel("Fields requiring >128 input tokens (%)")
    axes[1].set_title("Truncated-prefix exposure")
    for ax in axes:
        ax.set_xticks(x, [LABELS[key] for key in ENCODERS], rotation=20)
    fig.tight_layout()
    images.append(("encoder_runtime_and_truncation", fig))

    for name, fig in images:
        fig.savefig(folder / f"{name}.pdf", bbox_inches="tight")
        fig.savefig(folder / f"{name}.png", bbox_inches="tight")
        plt.close(fig)
    manifest = {
        "status": "benchmark_only_full_corpus_not_required",
        "selection_sha256": file_digest(output / "selection.json"),
        "metrics_sha256": file_digest(output / "cohort_metrics.csv"),
        "ranking_sha256": file_digest(output / "encoder_ranking.csv"),
        "ablation_sha256": file_digest(output / "complete_vs_prefix.csv"),
        "selected_encoder": selection["selected_encoder"],
        "verification_confirmed": selection["verification_confirmed"],
        "cohorts": metrics.cohort.nunique(),
        "undefined_penalty": PENALTY,
        "plots": [name for name, _ in images],
        "chunk_counts": dict(zip(ENCODERS, chunks)),
        "limitations": "All figures describe the matched benchmark, not human coding accuracy or full-data clustering.",
    }
    write_json(folder / "figure_manifest.json", manifest)
    return manifest


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(plot(args.output), indent=2))

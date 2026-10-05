import csv
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.cdp_extraction.cdp_section_fields import (
    BENCHMARK_FIELDS, benchmark_sample, connected_accounts, digest,
    field_definitions, file_digest, split_for, year_balanced,
)
from src.cdp_text_clustering.benchmark_cdp_sections import choose_encoder, partition_score, render_report
from src.cdp_text_clustering.deploy_cdp_section_clusters import deploy, evidence_candidates
from src.cdp_text_clustering.encode_cdp_section_fields import section_codebook
from src.cdp_text_clustering.plot_cdp_section_benchmark import load_benchmark, plot


class SectionDataTests(unittest.TestCase):
    def test_linked_accounts_share_split_across_years(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "links.csv"
            rows = [
                [2020, "a", "fact1", "", ""], [2025, "b", "fact1", "truc1", ""],
                [2021, "c", "", "truc1", ""], [2022, "d", "fact2", "", ""],
            ]
            with path.open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["year", "cdp_account_number", "factset_entity_id", "trucost_company_id", "lseg_isin"])
                writer.writerows(rows)
            groups = connected_accounts(path)
            self.assertEqual(groups["a"], groups["b"])
            self.assertEqual(groups["b"], groups["c"])
            self.assertNotEqual(groups["a"], groups["d"])
            self.assertEqual(split_for(groups["a"]), split_for(groups["c"]))

    def test_field_roles_and_out_of_scope_records(self):
        self.assertEqual(field_definitions("risks_opportunities", "risk")[1]["description"], "risk")
        self.assertEqual(field_definitions("risks_opportunities", "opportunity")[1]["description"], "opportunity")
        self.assertEqual(field_definitions("risks_opportunities", "risk")[1]["response_cost_desc"], "action")
        self.assertEqual(field_definitions("risks_opportunities", "assessment"), ("", {}))
        self.assertFalse(field_definitions("targets_performance", "initiative_stage")[1])
        self.assertEqual(field_definitions("engagement", "supplier_engagement")[1]["engagement_effect"], "engagement")

    def test_year_balance_deduplicates_training_text(self):
        rows = [{"field_id": str(i), "year": 2020 + i % 6, "normalized_sha256": str(i // 2)}
                for i in range(24)]
        result = year_balanced(rows, 18)
        self.assertEqual(len(result), 12)
        self.assertEqual(len({row["normalized_sha256"] for row in result}), 12)

    def test_matched_sample_is_repeatable_and_retains_all_years(self):
        rows = []
        for goal, fields in BENCHMARK_FIELDS.items():
            for field in fields:
                for sector in ("Manufacturing", "Services"):
                    for split, size in (("train", 40), ("selection", 12), ("verification", 12)):
                        for i in range(size):
                            field_id = f"{goal}|{field}|{sector}|{split}|{i}"
                            rows.append({
                                "goal": goal, "source_field": field, "sector_label": sector,
                                "sector_status": "reported", "split": split,
                                "evaluation_status": "training" if split == "train" else "eligible",
                                "year": 2020 + i % 6, "field_id": field_id,
                                "text_sha256": digest(field_id), "normalized_sha256": digest(field_id),
                            })
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            first = benchmark_sample(rows, output)
            second = benchmark_sample(rows, output)
            self.assertEqual(first, second)
            self.assertEqual(len(first), 768)
            self.assertEqual(len({row["cohort"] for row in first}), 16)
            for cohort in {row["cohort"] for row in first}:
                for split in ("train", "selection", "verification"):
                    part = [row for row in first if row["cohort"] == cohort and row["split"] == split]
                    self.assertEqual({row["year"] for row in part}, set(range(2020, 2026)))
        with self.assertRaises(ValueError):
            benchmark_sample(rows, Path("."), per_cohort=30)


class BenchmarkDecisionTests(unittest.TestCase):
    def metrics(self, verification_flip=False):
        rows = []
        models = {"minilm": 0.4, "e5": 0.3, "bge_m3": 0.2, "qwen3": 0.1}
        for goal in ("reduction", "risk", "opportunity", "engagement"):
            for cohort in range(4):
                for split in ("selection", "verification"):
                    for encoder, score in models.items():
                        if verification_flip and split == "verification" and encoder == "qwen3":
                            score = 0.9
                        rows.append({"goal": goal, "cohort": f"{goal}{cohort}", "split": split,
                                     "encoder": encoder, "mode": "complete", "score": score})
        return pd.DataFrame(rows)

    def test_selection_is_locked_before_verification(self):
        choice, _ = choose_encoder(self.metrics())
        self.assertEqual(choice["selected_encoder"], "minilm")
        self.assertTrue(choice["verification_confirmed"])
        choice, _ = choose_encoder(self.metrics(verification_flip=True))
        self.assertEqual(choice["selected_encoder"], "minilm")
        self.assertFalse(choice["verification_confirmed"])

    def test_no_valid_partition_does_not_manufacture_a_winner(self):
        frame = self.metrics()
        frame["score"] = -1
        with self.assertRaises(ValueError):
            choose_encoder(frame)

    def test_undefined_silhouette_is_penalized_not_zero(self):
        matrix = np.array([[1., 0.], [0.9, 0.1], [0., 1.], [0.1, 0.9]])
        undefined = partition_score({"a": matrix}, np.zeros(4))
        self.assertEqual(undefined["score"], -1)
        result = partition_score({"a": matrix, "b": matrix}, np.array([0, 0, 1, 1]))
        self.assertGreater(result["score"], 0.5)
        self.assertEqual(result["score"], result["space_scores"]["a"])

    def test_pending_manuscript_never_claims_completed_results(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            report = output / "report.tex"
            render_report(output, report)
            text = report.read_text()
            self.assertIn("Model selection is pending", text)
            self.assertIn("Full-corpus clustering has not completed", text)
            self.assertNotIn("Full processing is complete", text)


class SectionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.field = {
            "field_id": "f1", "record_id": "r1", "dataset": "d", "goal": "engagement",
            "source_field": "detail", "role": "engagement", "year": 2024,
            "company_id": "c1", "sector_label": "Services", "text": "Supplier training.",
        }
        self.book = [
            {"code": "supplier_capacity_building", "roles": ["engagement"], "definition": "Supplier training"},
            {"code": "insufficient_information", "roles": ["engagement"], "definition": "Not enough information"},
            {"code": "risk", "roles": ["risk"], "definition": "Risk"},
        ]
        self.payload = {"spans": [{"start": 0, "end": len(self.field["text"])}],
                        "code_scores": [[0.8, 0.2, 0.99]]}

    def test_exact_evidence_role_constraint_and_pending_status(self):
        rows = evidence_candidates(self.field, self.payload, self.book)
        self.assertEqual([row["code"] for row in rows], ["supplier_capacity_building"])
        self.assertEqual(rows[0]["evidence_text"], self.field["text"])
        self.assertEqual(rows[0]["review_status"], "unreviewed_ai_candidate")
        self.assertEqual(rows[0]["reviewer_id"], "")

    def test_abstention_and_incomplete_spans_fail(self):
        self.payload["code_scores"] = [[0.3, 0.4, 0.99]]
        rows = evidence_candidates(self.field, self.payload, self.book)
        self.assertEqual(rows[0]["code"], "insufficient_information")
        self.payload["spans"][0]["start"] = 1
        with self.assertRaises(ValueError):
            evidence_candidates(self.field, self.payload, self.book)
        self.payload["code_scores"] = []
        with self.assertRaises(ValueError):
            evidence_candidates(self.field, self.payload, self.book)

    def test_engagement_codebook_is_distinct_and_role_complete(self):
        book = section_codebook()
        self.assertEqual(len(book), len({row["code"] for row in book}))
        self.assertEqual(len(book), 82)
        self.assertIn("engagement", next(row for row in book if row["code"] == "insufficient_information")["roles"])
        self.assertIn("customer_engagement", {row["code"] for row in book})


class FullDeploymentTests(unittest.TestCase):
    def test_deployment_resume_and_checkpoint_corruption(self):
        class FakeCache:
            dimension = 2
            codebook = [
                {"code": "lighting", "roles": ["action"], "definition": "LED lights"},
                {"code": "solar", "roles": ["action"], "definition": "Solar panels"},
                {"code": "insufficient_information", "roles": ["action"], "definition": "Unclear"},
            ]

            def __init__(self, key, output):
                self.values = {}

            def ensure(self, rows):
                for row in rows:
                    lighting = "LED" in row["text"]
                    vector = np.array([1., 0.] if lighting else [0., 1.], dtype="float32")
                    self.values[row["text_sha256"]] = (vector, None, {
                        "spans": [{"start": 0, "end": len(row["text"]), "weight": 8, "input_tokens": 10}],
                        "code_scores": [[0.9, 0.1, 0.2] if lighting else [0.1, 0.9, 0.2]],
                    })

            def get(self, key):
                return self.values.get(key)

            def close(self):
                pass

        fields = []
        for i in range(18):
            text = ("LED lighting retrofit" if i % 2 == 0 else "Solar panels installation") + f" branch{i}"
            fields.append({
                "field_id": f"f{i}", "record_id": f"r{i}", "dataset": "targets_performance",
                "goal": "reduction", "source_field": "initiative_details", "role": "action",
                "text": text, "text_sha256": digest(text), "normalized_sha256": digest(text.lower()),
                "year": 2020 + i % 6, "company_id": f"company{i}", "company_name": f"Company {i}",
                "split": "train" if i < 12 else "selection" if i < 15 else "verification",
                "sector_label": "Manufacturing", "sector_status": "reported",
                "primary_sector_reported": "", "climate_relevance": "climate_questionnaire",
            })
        with tempfile.TemporaryDirectory() as directory, patch(
                "src.cdp_text_clustering.deploy_cdp_section_clusters.EncoderCache", FakeCache):
            output = Path(directory)
            with gzip.open(output / "fields.jsonl.gz", "wt", encoding="utf-8") as stream:
                stream.writelines(json.dumps(row) + "\n" for row in fields)
            (output / "data_manifest.json").write_text(json.dumps({
                "registry_sha256": file_digest(output / "fields.jsonl.gz")}))
            (output / "selection.json").write_text(json.dumps({
                "selected_encoder": "minilm", "choice_status": "synthetic_test"}))
            (output / "verification_checks.json").write_text(json.dumps({
                "selection_sha256": file_digest(output / "selection.json")}))
            result = deploy(output)
            self.assertEqual(result["fields"], 18)
            self.assertEqual(result["clustered_fields"], 18)
            self.assertEqual(result["coding_candidates"], 18)
            self.assertFalse(result["accepted_human_codes_generated"])
            with gzip.open(output / "full" / "cluster_assignments.csv.gz", "rt", encoding="utf-8-sig") as stream:
                assigned = list(csv.DictReader(stream))
            self.assertEqual({row["field_id"] for row in assigned}, {row["field_id"] for row in fields})
            self.assertTrue(all(row["coding_status"] == "pending_ai_suggestions" for row in assigned))
            self.assertEqual(deploy(output), result)
            (output / "full" / "completion.json").unlink()
            checkpoint = output / "full" / "blocks" / "00000000" / "embeddings.npy"
            matrix = np.load(checkpoint)
            matrix[0] = 0
            np.save(checkpoint, matrix)
            with self.assertRaisesRegex(ValueError, "Corrupt completed block"):
                deploy(output)


class BenchmarkFigureTests(unittest.TestCase):
    def test_figures_match_completed_benchmark_and_report(self):
        output = Path(__file__).resolve().parents[2] / "data" / "outputs" / "cdp_text_clustering" / "cdp_sections_benchmark_2020_2025"
        if not (output / "verification_checks.json").exists():
            self.skipTest("Recorded four-encoder benchmark is not available")
        metrics, ranking, ablation, selection = load_benchmark(output)
        self.assertEqual(metrics.cohort.nunique(), 16)
        self.assertEqual(selection["selected_encoder"], "qwen3")
        self.assertFalse(selection["verification_confirmed"])
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            for name in ("cohort_metrics.csv", "encoder_ranking.csv",
                         "complete_vs_prefix.csv", "selection.json", "verification_checks.json"):
                (destination / name).write_bytes((output / name).read_bytes())
            (destination / "encoders").mkdir()
            for key in ("minilm", "e5", "bge_m3", "qwen3"):
                folder = destination / "encoders" / key
                folder.mkdir()
                (folder / "benchmark_complete.json").write_bytes(
                    (output / "encoders" / key / "benchmark_complete.json").read_bytes())
            result = plot(destination)
            self.assertEqual(result["cohorts"], 16)
            for name in result["plots"]:
                self.assertGreater((destination / "figures" / f"{name}.pdf").stat().st_size, 1000)
                self.assertGreater((destination / "figures" / f"{name}.png").stat().st_size, 1000)
            report = destination / "report.tex"
            render_report(destination, report)
            self.assertEqual(report.read_text().count("\\includegraphics"), 4)
            self.assertIn("Full-corpus clustering has not completed", report.read_text())
            altered = pd.read_csv(destination / "cohort_metrics.csv")
            altered.loc[altered.metric_status.ne("defined"), "score"] = 0
            altered.to_csv(destination / "cohort_metrics.csv", index=False)
            with self.assertRaisesRegex(ValueError, "declared -1 penalty"):
                load_benchmark(destination)
            with self.assertRaisesRegex(ValueError, "stale"):
                render_report(destination, report)


if __name__ == "__main__":
    unittest.main()

import copy
import csv
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

from src.cdp_text_clustering.cluster_cdp_fields_by_sector import (
    descriptive_terms, fit_cohort, hybrid_features, load_embeddings, specific_initiative_groups,
)


class SectorClusteringTests(unittest.TestCase):
    def setUp(self):
        self.threads = threadpool_limits(limits=2)
        self.addCleanup(self.threads.restore_original_limits)
        self.rows, self.embeddings = [], {}
        qualifiers = ("north", "south", "east", "west", "central", "remote")
        for cluster, description in enumerate(("LED lighting retrofit", "Solar panels installation")):
            for i, qualifier in enumerate(qualifiers):
                field_id = f"f{cluster}_{i}"
                self.rows.append({
                    "field_id": field_id, "record_id": field_id, "dataset": "initiative",
                    "source_field": "comment", "split": "train",
                    "company_id": f"company_{cluster}_{i}",
                    "connected_group": f"company_{cluster}_{i}",
                    "field_status": "available", "text": f"{description} {qualifier}",
                })
                vector = np.array([1., 0.02 * (i + 1)], dtype=np.float32)
                if cluster:
                    vector = vector[::-1].copy()
                self.embeddings[field_id] = vector / np.linalg.norm(vector)

    def fit(self, rows=None):
        return fit_cohort(self.rows if rows is None else rows, self.embeddings,
                          max_clusters=2, min_cluster_size=3, tolerance=0.02)

    def test_supported_specific_partition(self):
        result = self.fit()
        self.assertEqual(result["status"], "clustered")
        self.assertEqual(result["k"], 2)
        labels = result["model"].labels_
        self.assertEqual(len(set(labels[:6])), 1)
        self.assertEqual(len(set(labels[6:])), 1)
        self.assertNotEqual(labels[0], labels[-1])
        self.assertTrue(all(trial["min_unique_fields"] >= 3 for trial in result["trials"]))
        self.assertTrue(all(trial["min_companies"] >= 2 for trial in result["trials"]))
        terms = descriptive_terms(result["vectorizer"], result["fit_rows"], labels, labels[0])
        self.assertTrue(any("led" in term or "lighting" in term for term in terms))
        self.assertFalse(any("solar" in term for term in terms))

    def test_holdout_never_changes_fitting_or_vocabulary(self):
        before = self.fit()
        holdout = {**self.rows[0], "field_id": "holdout", "split": "holdout",
                   "company_id": "new_company", "text": "unseenholdouttoken"}
        self.embeddings["holdout"] = np.array([0., 1.], dtype=np.float32)
        after = self.fit(self.rows + [holdout])
        self.assertNotIn("unseenholdouttoken", after["vectorizer"].vocabulary_)
        self.assertEqual(before["k"], after["k"])
        np.testing.assert_array_equal(before["model"].cluster_centers_,
                                      after["model"].cluster_centers_)
        self.assertNotIn("holdout", [row["field_id"] for row in after["fit_rows"]])

    def test_duplicate_answers_do_not_inflate_minimum_support(self):
        repeated = []
        for index in range(12):
            repeated.append({**self.rows[index], "text": " LED   retrofit " if index < 6 else "SOLAR panels"})
        result = self.fit(repeated)
        self.assertEqual(result["unique_train_fields"], 2)
        self.assertEqual(result["status"], "unclustered_insufficient_training")

    def test_sparse_or_holdout_only_cohorts_are_unclustered(self):
        self.assertEqual(self.fit(self.rows[:5])["status"], "unclustered_insufficient_training")
        holdout = [{**row, "split": "holdout"} for row in self.rows]
        self.assertEqual(self.fit(holdout)["status"], "unclustered_insufficient_training")

    def test_company_dominated_clusters_are_rejected(self):
        rows = [{**row, "company_id": "one_company" if i < 6 else row["company_id"]}
                for i, row in enumerate(self.rows)]
        self.assertEqual(self.fit(rows)["status"], "unclustered_no_supported_partition")

    def test_empty_lexical_input_has_explicit_semantic_only_mode(self):
        with self.assertLogs(level="WARNING"):
            features, vectorizer = hybrid_features(
                np.array([[1., 0.], [0., 1.]]), ["123", "456"], fit=True)
        self.assertIsNone(vectorizer)
        np.testing.assert_array_equal(features.toarray(), [[1., 0.], [0., 1.]])

    def test_embedding_manifest_order_and_identity_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            rows = copy.deepcopy(self.rows)
            (path / "fields.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            columns = ["field_id", "dataset", "record_id", "source_field"]
            manifest_rows = list(reversed(rows))
            with (path / "response_field_embedding_manifest.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(manifest_rows)
            np.save(path / "response_field_embeddings.npy",
                    np.stack([self.embeddings[row["field_id"]] for row in manifest_rows]))
            _, vectors = load_embeddings(path)
            for field_id, vector in self.embeddings.items():
                np.testing.assert_array_equal(vectors[field_id], vector)
            manifest_rows[0]["record_id"] = "wrong_record"
            with (path / "response_field_embedding_manifest.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(manifest_rows)
            with self.assertRaises(ValueError):
                load_embeddings(path)

    def test_company_split_leakage_fails_before_clustering(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            rows = copy.deepcopy(self.rows)
            rows[-1]["split"] = "holdout"
            rows[-1]["company_id"] = rows[0]["company_id"]
            (path / "fields.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            columns = ["field_id", "dataset", "record_id", "source_field"]
            with (path / "response_field_embedding_manifest.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
            np.save(path / "response_field_embeddings.npy",
                    np.stack([self.embeddings[row["field_id"]] for row in rows]))
            with self.assertRaisesRegex(ValueError, "leakage"):
                load_embeddings(path)

    def test_specific_groups_separate_mechanisms_even_in_same_model_cluster(self):
        assignments, overlay = {}, {}
        for index, code in enumerate(("it_efficiency", "circularity", "it_efficiency")):
            field_id = f"f{index}"
            sector = "Services" if index < 2 else "Manufacturing"
            row = {
                "dataset": "initiative", "record_id": field_id, "field_id": field_id,
                "source_field": "comment", "company_id": field_id, "company_name": field_id,
                "year": "2024", "split": "train", "sector_label": sector,
                "sector_label_source": "cdp_primary_industry",
                "primary_sector_reported": "", "primary_industry_reported": sector,
                "cluster_id": "broad_model_topic", "cluster_label": "Paper and office costs",
                "assignment_status": "clustered",
            }
            assignments[field_id] = row
            overlay[field_id] = [{
                "code": code, "initiative_name": code, "parent_code": "",
                "sector_initiative_cluster_key": f"{sector}|{code}",
                "evidence_start": 0, "evidence_end": 3, "evidence_text": "abc",
                "review_status": "unreviewed_ai_candidate",
            }]
        assignments["unreviewed"] = {**assignments["f0"], "field_id": "unreviewed"}
        members, summaries = specific_initiative_groups(assignments, overlay)
        self.assertEqual(len(summaries), 3)
        self.assertEqual(len({row["specific_group_id"] for row in members}), 3)
        self.assertEqual(assignments["unreviewed"]["specific_initiative_group_ids"], "[]")
        self.assertTrue(all(row["review_status"] == "unreviewed_ai_candidate" for row in members))
        # Multiple explicit mechanisms remain multiple groups without refitting/duplicating observations.
        overlay["f0"].append({**overlay["f1"][0]})
        members, _ = specific_initiative_groups(assignments, overlay)
        self.assertEqual(len([row for row in members if row["field_id"] == "f0"]), 2)
        overlay["f0"] = [{**overlay["f0"][0], "sector_initiative_cluster_key": ""}]
        members, _ = specific_initiative_groups(assignments, overlay)
        self.assertFalse(any(row["field_id"] == "f0" for row in members))


if __name__ == "__main__":
    unittest.main()

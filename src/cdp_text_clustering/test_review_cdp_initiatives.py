import copy
import csv
import json
import tempfile
import unittest
from pathlib import Path

from src.cdp_text_clustering.review_cdp_initiatives import (
    HERE, METHOD, ROOT, label_context, populate_template, read_jsonl,
    reviewed_candidates, source_context,
)


class InitiativeReviewTests(unittest.TestCase):
    def setUp(self):
        self.field = {
            "dataset": "initiative", "record_id": "r1", "field_id": "f1",
            "source_field": "comment", "role": "action", "text": "LED lights. Solar panels.",
            "field_status": "available",
        }
        self.chunks = [
            {"field_id": "f1", "chunk_id": "c1", "start": 0, "end": 12},
            {"field_id": "f1", "chunk_id": "c2", "start": 12, "end": 25},
        ]
        self.codes = [
            {"code": "lighting", "label": "LED lighting", "roles": ["action"],
             "definition": "Efficient lighting"},
            {"code": "solar", "label": "Solar generation", "roles": ["action"],
             "definition": "Solar panels"},
        ]
        self.context = {
            "company_id": "123", "company_name": "Example", "year": "2024",
            "primary_sector_reported": "", "primary_industry_reported": "Manufacturing",
            "sector_label": "Manufacturing", "sector_label_source": "cdp_primary_industry",
            "reported_initiative_name": "Lighting",
        }
        self.review = {
            "scope": ["initiative"],
            "evidence": {"r1": [["lighting", "LED lights"], ["solar", "Solar panels"]]},
        }

    def candidates(self):
        return reviewed_candidates([self.field], self.chunks, self.review,
                                   self.codes, {"f1": self.context})

    def test_exact_multilabel_evidence_and_no_invented_similarity(self):
        rows = self.candidates()
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(self.field["text"][row["evidence_start"]:row["evidence_end"]],
                             row["evidence_text"])
            self.assertIsNone(row["similarity"])
            self.assertEqual(row["review_status"], "unreviewed_ai_candidate")
        self.assertEqual(rows[1]["chunk_id"], "c2")
        self.assertEqual(rows[0]["sector_initiative_cluster_key"],
                         "cdp_primary_industry:manufacturing|lighting")

    def test_cross_chunk_evidence_keeps_all_chunk_ids(self):
        self.review["evidence"]["r1"] = [["lighting", "lights. Solar"]]
        row = self.candidates()[0]
        self.assertIsNone(row["chunk_id"])
        self.assertEqual(row["chunk_ids"], ["c1", "c2"])

    def test_invalid_evidence_code_and_coverage_fail(self):
        for change in (
            {"r1": [["lighting", "Missing text"]]},
            {"r1": [["unknown", "LED lights"]]},
            {"r1": [["lighting", "LED lights"], ["lighting", "Solar panels"]]},
            {},
        ):
            with self.subTest(change=change):
                self.review["evidence"] = change
                with self.assertRaises(ValueError):
                    self.candidates()

    def test_chunk_gap_fails(self):
        self.review["evidence"]["r1"] = [["lighting", "lights. Solar"]]
        self.chunks[1]["start"] = 14
        with self.assertRaises(ValueError):
            self.candidates()

    def test_sector_is_not_inferred_and_generic_codes_do_not_cluster(self):
        unknown = {**self.context, "sector_label": "unknown",
                   "sector_label_source": "missing_in_source"}
        row = label_context(unknown, self.codes[0], True)
        self.assertEqual(row["initiative_cluster_key"], "lighting")
        self.assertEqual(row["sector_initiative_cluster_key"], "")
        for code in ("insufficient_information", "general_environmental_effort"):
            row = label_context(self.context, {"code": code}, True)
            self.assertEqual(row["initiative_name"], "")
            self.assertEqual(row["initiative_cluster_key"], "")
        self.assertEqual(label_context(self.context, self.codes[0], False)["initiative_name"], "")

    def test_template_stays_pending_and_preserves_all_existing_work(self):
        blank = {**{key: self.field[key] for key in (
            "dataset", "record_id", "field_id", "source_field")},
            "code": "", "review_status": "pending", "reviewer_id": ""}
        proposals = self.candidates()
        rows = populate_template([blank], proposals, {"f1": self.context})
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["review_status"] == "pending" and not row["reviewer_id"]
                            for row in rows))
        self.assertEqual(populate_template(rows, proposals, {"f1": self.context}), rows)
        for change in (
            {"code": "human_code", "notes": "Work in progress"},
            {"review_status": "accepted", "reviewer_id": "human"},
            {"review_status": "rejected"},
            {"notes": "Need to check this"},
            {"code": "human_change", "suggestion_method": METHOD},
        ):
            edited = {**blank, **change}
            with self.subTest(change=change):
                kept = populate_template([edited], proposals, {"f1": self.context})
                self.assertEqual(len(kept), 1)
                for key, value in edited.items():
                    self.assertEqual(kept[0][key], value)

    def test_exact_source_join_and_missing_industry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = {"record_id": "r1", "cdp_account_number": "123", "year": "2024",
                      "organization": "Example", "primary_sector": "Financial services",
                      "primary_industry": "", "comment": self.field["text"]}
            with (root / "source.csv").open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(record))
                writer.writeheader()
                writer.writerow(record)
            field = {**self.field, "source_path": "source.csv", "company_id": "123",
                     "year": "2024", "source_metadata": {}}
            context = source_context([field], root)["f1"]
            self.assertEqual(context["primary_sector_reported"], "Financial services")
            self.assertEqual(context["sector_label"], "unknown")
            self.assertEqual(context["sector_label_source"], "missing_in_source")
            for change in ({"company_id": "456"}, {"year": "2023"}, {"text": "changed"}):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    source_context([{**field, **change}], root)

    def test_review_manifest_regressions(self):
        review = json.loads((HERE / "cdp_initiative_review.json").read_text(encoding="utf-8"))
        expected = {
            "2022:C4.3b:1040": {"lighting_efficiency"},
            "2020:C4.3b:6396": {"it_efficiency"},
            "2022:C4.3b:15094": {"fleet_electrification"},
            "2024:Q7.55.2:36623:1": {"solar_generation"},
            "2024:Q7.55.2:22684:3": {"fleet_electrification"},
            "2024:Q7.55.2:851786:3": {"fleet_electrification"},
            "2024:Q7.55.2:18435:5": {"energy_storage"},
        }
        for record_id, codes in expected.items():
            self.assertEqual({entry[0] for entry in review["evidence"][record_id]}, codes)
        self.assertEqual(len(review["evidence"]), 182)
        output = ROOT / "data" / "outputs" / "cdp_text_clustering" / "cdp_field_chunks_minilm_development"
        if not (output / "fields.jsonl").exists():
            return
        fields = read_jsonl(output / "fields.jsonl")
        codes = json.loads((HERE / "cdp_field_codebook.json").read_text(encoding="utf-8"))
        contexts = {field["field_id"]: copy.deepcopy(self.context) for field in fields}
        proposals = reviewed_candidates(fields, read_jsonl(output / "chunks.jsonl"),
                                        review, codes, contexts)
        self.assertEqual(len({row["field_id"] for row in proposals}), 182)


if __name__ == "__main__":
    unittest.main()

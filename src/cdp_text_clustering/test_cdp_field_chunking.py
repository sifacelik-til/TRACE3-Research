import unittest

import numpy as np
import pandas as pd

from src.cdp_text_clustering.cdp_field_chunking import (
    aggregate_chunks, chunk_text, coding_candidates, token_count,
    validate_annotations, validate_codebook, verify_spans,
)


class CharacterTokenizer:
    def encode(self, text, *, add_special_tokens):
        return [ord(char) for char in text] + ([1, 2] if add_special_tokens else [])


class ChunkingTests(unittest.TestCase):
    def setUp(self):
        self.tokenizer = CharacterTokenizer()

    def test_complete_multilingual_coverage_and_prompt_budget(self):
        texts = [
            "First sentence. A second sentence!\nA final sentence.",
            "  Leading spaces.\r\n\r\nTrailing spaces   ",
            "\u65e5\u672c\u8a9e\u3002\u4e2d\u6587\uff01" * 20,
            "\u0645\u0646\u0627\u062e \u062a\u063a\u064a\u0631\n" * 10,
            "A\U0001f30dB\u0301C" * 25,
            "z" * 230,
        ]
        for text in texts:
            with self.subTest(text=text[:15]):
                chunks = chunk_text(text, self.tokenizer, 30, "query: ")
                self.assertEqual("".join(chunk["text"] for chunk in chunks), text)
                self.assertTrue(all(token_count(self.tokenizer, chunk["text"], "query: ") <= 30
                                    for chunk in chunks))
                self.assertEqual(sum(chunk["end"] - chunk["start"] for chunk in chunks), len(text))
                self.assertEqual(chunks[-1]["end"], len(text))

    def test_short_text_is_unchanged(self):
        chunks = chunk_text("one sentence", self.tokenizer, 32)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["text"], "one sentence")

    def test_empty_text_and_invalid_budget(self):
        self.assertEqual(chunk_text("", self.tokenizer, 20), [])
        with self.assertRaises(ValueError):
            chunk_text("test", self.tokenizer, 5, "query: ")

    def test_long_sentence_fallback_reaches_final_evidence(self):
        text = "x" * 200 + " SOLAR PANELS INSTALLED"
        chunks = chunk_text(text, self.tokenizer, 32)
        self.assertEqual("".join(chunk["text"] for chunk in chunks)[200:], text[200:])
        self.assertGreater(chunks[-1]["start"], 32)

    def test_gap_is_rejected(self):
        chunks = chunk_text("a" * 100, self.tokenizer, 32)
        chunks[1]["start"] += 1
        with self.assertRaises(ValueError):
            verify_spans("a" * 100, chunks, 32)

    def test_aggregation_is_weighted_and_normalized(self):
        result = aggregate_chunks(np.array([[1, 0], [0, 1]]), np.array([3, 1]))
        np.testing.assert_allclose(result, np.array([3, 1]) / np.sqrt(10), atol=1e-6)

    def test_single_chunk_and_equivalent_repartition(self):
        vector = np.array([[0.6, 0.8]])
        np.testing.assert_allclose(aggregate_chunks(vector, np.array([50])), vector[0])
        np.testing.assert_allclose(
            aggregate_chunks(np.repeat(vector, 2, axis=0), np.array([20, 30])), vector[0])

    def test_invalid_aggregation_fails(self):
        for vectors, weights in [
            (np.empty((0, 2)), np.array([])),
            (np.array([[1., 0.]]), np.array([0.])),
            (np.array([[np.nan, 0.]]), np.array([1.])),
            (np.array([[1., 0.], [-1., 0.]]), np.array([1., 1.])),
        ]:
            with self.assertRaises(ValueError):
                aggregate_chunks(vectors, weights)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fields = pd.DataFrame([{
            "field_id": "f1", "dataset": "d1", "record_id": "r1", "role": "action",
            "source_field": "comment", "text": "Solar panels. LED lights.",
        }])
        self.codebook = [
            {"code": "solar", "roles": ["action"], "definition": "Solar panels"},
            {"code": "lighting", "roles": ["action"], "definition": "LED lighting"},
            {"code": "flood", "roles": ["risk"], "definition": "Flood risk"},
        ]
        self.entry = {
            "field_id": "f1", "dataset": "d1", "record_id": "r1", "code": "solar",
            "evidence_start": "0", "evidence_end": "12", "evidence_text": "Solar panels",
            "review_status": "accepted", "reviewer_id": "coder1",
        }

    def test_multiple_codes_link_to_distinct_evidence(self):
        second = {**self.entry, "code": "lighting", "evidence_start": "14",
                  "evidence_end": "24", "evidence_text": "LED lights"}
        accepted, counts = validate_annotations([self.entry, second], self.fields, self.codebook)
        self.assertEqual(counts["accepted"], 2)
        self.assertEqual({row["code"] for row in accepted}, {"solar", "lighting"})

    def test_invalid_evidence_identity_and_review_are_rejected(self):
        changes = [
            {"evidence_text": "Solar cells"}, {"evidence_end": "200"},
            {"evidence_start": "-1"}, {"evidence_start": 0.5}, {"reviewer_id": ""},
            {"reviewer_id": None},
            {"code": "unknown"}, {"code": "flood"}, {"field_id": "missing"},
            {"record_id": "other"}, {"review_status": "approved"},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_annotations([{**self.entry, **change}], self.fields, self.codebook)

    def test_pending_and_rejected_are_not_accepted(self):
        accepted, counts = validate_annotations([
            {**self.entry, "review_status": "pending"},
            {**self.entry, "review_status": "rejected"},
        ], self.fields, self.codebook)
        self.assertEqual(accepted, [])
        self.assertEqual(counts, {"accepted": 0, "pending": 1, "rejected": 1})

    def test_duplicate_entries_fail_but_two_coders_remain_distinct(self):
        with self.assertRaises(ValueError):
            validate_annotations([self.entry, self.entry], self.fields, self.codebook)
        accepted, _ = validate_annotations(
            [self.entry, {**self.entry, "reviewer_id": "coder2"}], self.fields, self.codebook)
        self.assertEqual(len(accepted), 2)

    def test_candidates_are_role_constrained_and_unreviewed(self):
        chunks = pd.DataFrame([{
            "field_id": "f1", "chunk_id": "c1", "start": 0, "end": 12, "text": "Solar panels",
        }])
        proposals = coding_candidates(self.fields, chunks, np.array([[1., 0.]]),
                                      self.codebook, np.array([[1., 0.], [0., 1.], [1., 0.]]))
        self.assertEqual({row["code"] for row in proposals}, {"solar", "lighting"})
        self.assertTrue(all(row["review_status"] == "unreviewed_ai_candidate" for row in proposals))
        self.assertTrue(all(row["evidence_text"] == "Solar panels" for row in proposals))

    def test_duplicate_codebook_ids_fail(self):
        with self.assertRaises(ValueError):
            validate_codebook([self.codebook[0], self.codebook[0]])


if __name__ == "__main__":
    unittest.main()

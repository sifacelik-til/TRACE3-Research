"""Lossless text spans, response-level pooling, and evidence-code validation."""

from __future__ import annotations

import re
from typing import Protocol

import numpy as np
import pandas as pd


class Tokenizer(Protocol):
    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]: ...


BOUNDARY = re.compile(r"(?:[.!?。！？]+[\"'\u201d\u2019]*\s*|\r?\n\s*)")


def token_count(tokenizer: Tokenizer, text: str, prefix: str = "") -> int:
    return len(tokenizer.encode(prefix + text, add_special_tokens=True))


def chunk_text(text: str, tokenizer: Tokenizer, max_tokens: int, prefix: str = "") -> list[dict]:
    """Partition every character exactly once; offsets are Python [start,end)."""
    if not isinstance(text, str):
        raise TypeError("Chunk input must be a string")
    if max_tokens <= token_count(tokenizer, "", prefix):
        raise ValueError("Token budget leaves no room after prompt/special tokens")
    if not text:
        return []
    boundaries = [match.end() for match in BOUNDARY.finditer(text)]
    chunks = []
    start = 0
    while start < len(text):
        if token_count(tokenizer, text[start:], prefix) <= max_tokens:
            end = len(text)
        else:
            low, high, fitting = start + 1, len(text), start
            while low <= high:
                middle = (low + high) // 2
                if token_count(tokenizer, text[start:middle], prefix) <= max_tokens:
                    fitting, low = middle, middle + 1
                else:
                    high = middle - 1
            if fitting == start:
                raise ValueError(f"Cannot fit a source character at offset {start}")
            preferred = [end for end in boundaries if start < end <= fitting]
            end = preferred[-1] if preferred else fitting
            if not preferred:
                spaces = list(re.finditer(r"\s+", text[start:end]))
                if spaces:
                    end = start + spaces[-1].end()
            # Token counts need not be monotonic across character boundaries.
            while end > start and token_count(tokenizer, text[start:end], prefix) > max_tokens:
                end -= 1
            if end == start:
                raise ValueError(f"No valid chunk boundary at offset {start}")
        excerpt = text[start:end]
        chunks.append({
            "start": start, "end": end, "text": excerpt,
            "input_tokens": token_count(tokenizer, excerpt, prefix),
            "weight": max(1, len(tokenizer.encode(excerpt, add_special_tokens=False))),
        })
        start = end
    verify_spans(text, chunks, max_tokens)
    return chunks


def verify_spans(text: str, chunks: list[dict], max_tokens: int) -> None:
    position = 0
    for chunk in chunks:
        if chunk["start"] != position or not position < chunk["end"] <= len(text):
            raise ValueError("Gap, overlap, or invalid chunk offsets")
        if text[position:chunk["end"]] != chunk["text"]:
            raise ValueError("Chunk text differs from the source span")
        if chunk["input_tokens"] > max_tokens or chunk["weight"] <= 0:
            raise ValueError("Invalid chunk token count or aggregation weight")
        position = chunk["end"]
    if position != len(text):
        raise ValueError("Chunk coverage does not reach the end of the source")


def aggregate_chunks(vectors: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """One normalized weighted mean per response/field, not per sentence."""
    vectors = np.asarray(vectors)
    weights = np.asarray(weights)
    if vectors.ndim != 2 or weights.shape != (len(vectors),) or not len(vectors):
        raise ValueError("Expected nonempty chunk vectors and matching weights")
    if not np.isfinite(vectors).all() or not np.isfinite(weights).all() or (weights <= 0).any():
        raise ValueError("Invalid chunk vectors or weights")
    mean = np.average(vectors, weights=weights, axis=0)
    norm = np.linalg.norm(mean)
    if norm <= 1e-12:
        raise ValueError("Chunk aggregation has a zero-norm representation")
    return (mean / norm).astype("float32")


def validate_codebook(codebook: list[dict]) -> None:
    if not codebook or len({code["code"] for code in codebook}) != len(codebook):
        raise ValueError("Codebook must have unique, nonempty code IDs")
    for code in codebook:
        if not code["code"] or not code["definition"] or not code["roles"]:
            raise ValueError("Each code needs an ID, definition, and applicable field roles")


def coding_candidates(fields: pd.DataFrame, chunks: pd.DataFrame, embeddings: np.ndarray,
                      codebook: list[dict], code_vectors: np.ndarray) -> list[dict]:
    """Top-two semantic suggestions per chunk; scores are not probabilities."""
    validate_codebook(codebook)
    if len(chunks) != len(embeddings) or len(codebook) != len(code_vectors):
        raise ValueError("Candidate embedding rows do not match their manifests")
    if embeddings.shape[1] != code_vectors.shape[1]:
        raise ValueError("Chunk and code embedding dimensions differ")
    source = fields.set_index("field_id")
    proposals = []
    for position, chunk in enumerate(chunks.to_dict("records")):
        field = source.loc[chunk["field_id"]]
        applicable = [i for i, code in enumerate(codebook) if field["role"] in code["roles"]]
        if not applicable:
            raise ValueError(f"No codebook entries for role {field['role']}")
        scores = embeddings[position] @ code_vectors[applicable].T
        for rank in np.argsort(scores)[::-1][:2]:
            code = codebook[applicable[int(rank)]]
            proposals.append({
                "dataset": field["dataset"], "record_id": field["record_id"],
                "field_id": chunk["field_id"], "source_field": field["source_field"],
                "chunk_id": chunk["chunk_id"], "code": code["code"],
                "evidence_start": chunk["start"], "evidence_end": chunk["end"],
                "evidence_text": chunk["text"], "similarity": float(scores[rank]),
                "review_status": "unreviewed_ai_candidate",
                "interpretation": "Whole-chunk retrieval suggestion; reviewer must verify and narrow evidence.",
            })
    return proposals


def validate_annotations(annotations: list[dict], fields: pd.DataFrame,
                         codebook: list[dict]) -> tuple[list[dict], dict]:
    validate_codebook(codebook)
    source = fields.set_index("field_id")
    allowed = {code["code"]: code for code in codebook}
    accepted, seen = [], set()
    counts = {"accepted": 0, "pending": 0, "rejected": 0}
    for number, row in enumerate(annotations, 1):
        status = row.get("review_status", "").strip()
        if status in {"", "pending", "unreviewed_ai_candidate"}:
            counts["pending"] += 1
            continue
        if status == "rejected":
            counts["rejected"] += 1
            continue
        if status != "accepted":
            raise ValueError(f"Annotation {number}: unknown review status {status!r}")
        field_id = row.get("field_id", "")
        if field_id not in source.index:
            raise ValueError(f"Annotation {number}: unknown field ID")
        field = source.loc[field_id]
        if row.get("dataset") != field["dataset"] or row.get("record_id") != field["record_id"]:
            raise ValueError(f"Annotation {number}: source identity does not match field")
        code = row.get("code", "")
        if code not in allowed or field["role"] not in allowed[code]["roles"]:
            raise ValueError(f"Annotation {number}: invalid or inapplicable code")
        if not isinstance(row.get("reviewer_id"), str) or not row["reviewer_id"].strip():
            raise ValueError(f"Annotation {number}: accepted evidence requires a reviewer")
        try:
            start, end = int(row["evidence_start"]), int(row["evidence_end"])
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(f"Annotation {number}: integer evidence offsets required") from exc
        # Reject lossy coercion of JSON floating point coordinates.
        if str(start) != str(row["evidence_start"]) or str(end) != str(row["evidence_end"]):
            raise ValueError(f"Annotation {number}: offsets must be exact integers")
        text = field["text"]
        if not 0 <= start < end <= len(text):
            raise ValueError(f"Annotation {number}: evidence outside source field")
        if text[start:end] != row.get("evidence_text"):
            raise ValueError(f"Annotation {number}: evidence text is not the exact source span")
        key = (field_id, code, start, end, row["reviewer_id"])
        if key in seen:
            raise ValueError(f"Annotation {number}: duplicate coding entry")
        seen.add(key)
        accepted.append({**row, "evidence_start": start, "evidence_end": end})
        counts["accepted"] += 1
    return accepted, counts

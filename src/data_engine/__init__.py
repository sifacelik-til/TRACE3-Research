"""Backward-compatible imports for modules reorganized under ``src``."""

from pathlib import Path

_src_root = Path(__file__).resolve().parents[1]
__path__ = [
    str(_src_root / "dataset_readers"),
    str(_src_root / "cdp_extraction"),
    str(_src_root / "cdp_text_clustering"),
]

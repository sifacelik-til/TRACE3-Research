"""Shared encoder identities and prompts without importing inference libraries."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PREVIOUS = ROOT / "data" / "outputs" / "cdp_text_clustering" / "cdp_clustering_verification_20260929"
DEFAULT_OUTPUT = ROOT / "data" / "outputs" / "cdp_text_clustering" / "cdp_encoder_competition_20260929"
MODEL_CACHE = ROOT / "data" / "models" / "cdp_encoder_competition"
MODELS = {
    "minilm": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "e5": "intfloat/multilingual-e5-base",
    "bge_m3": "BAAI/bge-m3",
    "qwen3": "Qwen/Qwen3-Embedding-0.6B",
}
PREFIXES = {
    "minilm": "", "e5": "query: ", "bge_m3": "",
    "qwen3": "Instruct: Identify the main climate-related theme of this corporate disclosure for clustering.\nQuery: ",
}
SEEDS = (42, 43, 44, 45, 46)

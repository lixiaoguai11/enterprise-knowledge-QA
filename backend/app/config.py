import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
load_dotenv(PROJECT_ROOT / ".env")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-chat")

# Select the provider protocol explicitly. Anthropic-compatible gateways can be
# configured with ANTHROPIC_BASE_URL while using the native Messages API shape.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek").strip().lower()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "") or DEEPSEEK_API_KEY
ANTHROPIC_BASE_URL = (
    os.getenv("ANTHROPIC_BASE_URL", "")
    or os.getenv("DEEPSEEK_BASE_URL", "")
    or "https://api.anthropic.com"
)
ANTHROPIC_MODEL = (
    os.getenv("ANTHROPIC_MODEL", "")
    or os.getenv("MODEL_NAME", "")
    or "claude-sonnet-4-5"
)

# Optional OpenAI-compatible embedding endpoint. When no key is configured,
# retrieval keeps using the local FastEmbed model.
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "")
EMBEDDING_MODEL_NAME = os.getenv(
    "EMBEDDING_MODEL_NAME", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "https://api.openai.com/v1")

# Reranking backend is deliberately separate from the embedding provider. The
# default reuses the BGE vectors already produced for hybrid retrieval.
RERANKER_PROVIDER = os.getenv("RERANKER_PROVIDER", "bge_similarity").strip().lower()
RERANK_API_KEY = os.getenv("RERANK_API_KEY", "")
RERANK_MODEL_NAME = os.getenv("RERANK_MODEL_NAME", "Qwen/Qwen3-Reranker-8B")
RERANK_BASE_URL = os.getenv("RERANK_BASE_URL", "")

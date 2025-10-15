"""Local Text2Vec provider for query embeddings at search time.

This provider talks to the same local transformers inference service used at
ingest time (TEXT2VEC_INFERENCE_URL), enabling fully offline neural/hybrid search
without any cloud API keys.
"""

from typing import Any, Dict, List

import httpx

from airweave.api.context import ApiContext
from airweave.core.config import settings

from ._base import BaseProvider
from .schemas import ProviderModelSpec


class LocalText2VecProvider(BaseProvider):
    """Embedding-only provider backed by local text2vec service."""

    TIMEOUT = 120.0

    def __init__(self, api_key: str, model_spec: ProviderModelSpec, ctx: ApiContext) -> None:  # noqa: D401
        # api_key is ignored (no key required); kept for BaseProvider signature
        super().__init__(api_key, model_spec, ctx)
        self.base_url = settings.TEXT2VEC_INFERENCE_URL.rstrip("/")
        if not self.base_url:
            raise RuntimeError("TEXT2VEC_INFERENCE_URL is not configured")

        # This provider does not use an LLM; tokenizers only apply to LLM ops
        self.llm_tokenizer = None
        self.embedding_tokenizer = None
        self.rerank_tokenizer = None

    # --- LLM interfaces not supported here ---
    async def generate(self, messages: List[Dict[str, str]]) -> str:  # pragma: no cover - not used
        raise RuntimeError("LocalText2VecProvider does not support text generation")

    async def structured_output(self, messages: List[Dict[str, str]], schema):  # pragma: no cover - not used
        raise RuntimeError("LocalText2VecProvider does not support structured output")

    async def rerank(self, query: str, documents: List[str], top_n: int) -> List[Dict[str, Any]]:  # pragma: no cover - not used
        raise RuntimeError("LocalText2VecProvider does not support reranking")

    # --- Embeddings ---
    async def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        vectors: List[List[float]] = []
        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            for text in texts:
                payload = {"text": text or ""}
                # Prefer the /vectors (without trailing slash) path; fall back to /vectors/
                try:
                    resp = await client.post(f"{self.base_url}/vectors", json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    vectors.append(data["vector"])  # type: ignore[index]
                except Exception:
                    # Fallback path used by some images
                    resp = await client.post(f"{self.base_url}/vectors/", json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    vectors.append(data["vector"])  # type: ignore[index]

        if not vectors or len(vectors) != len(texts):
            raise RuntimeError(
                f"Local text2vec returned {len(vectors)} vectors for {len(texts)} texts"
            )
        return vectors


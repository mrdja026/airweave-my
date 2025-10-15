"""Ollama provider for local answer generation.

Uses the Ollama HTTP API to run chat completions against a local model
(e.g., gemma:7b). Token counting uses a configurable tokenizer name from
defaults.yml (approximate), enabling context budgeting.
"""

from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel

from airweave.api.context import ApiContext
from airweave.core.config import settings

from ._base import BaseProvider
from .schemas import ProviderModelSpec


class OllamaProvider(BaseProvider):
    """Local LLM provider via Ollama REST API."""

    TIMEOUT = 600.0

    def __init__(self, api_key: str, model_spec: ProviderModelSpec, ctx: ApiContext) -> None:  # noqa: D401
        # api_key ignored (no key required); BaseProvider signature only
        super().__init__(api_key, model_spec, ctx)

        self.base_url = (settings.OLLAMA_BASE_URL or "").rstrip("/")
        if not self.base_url:
            raise RuntimeError("OLLAMA_BASE_URL is not configured")

        # Initialize tokenizers if provided
        self.llm_tokenizer = None
        self.embedding_tokenizer = None
        self.rerank_tokenizer = None

        if model_spec.llm_model and model_spec.llm_model.tokenizer:
            self.llm_tokenizer = self._load_tokenizer(model_spec.llm_model.tokenizer, "llm")

    # --- Generation ---
    async def generate(self, messages: List[Dict[str, str]]) -> str:
        if not self.model_spec.llm_model or not self.model_spec.llm_model.name:
            raise RuntimeError("LLM model not configured for Ollama provider")

        model = settings.OLLAMA_MODEL or self.model_spec.llm_model.name

        # Convert to Ollama chat format
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            # You can extend with options: temperature, top_p, etc.
        }

        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            resp = await client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()

        # Try common shapes
        # Newer Ollama returns { message: { role, content }, done: true }
        if isinstance(data, dict):
            msg = data.get("message")
            if msg and isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str):
                    return content
            # Some variants return { response: "..." }
            if isinstance(data.get("response"), str):
                return data["response"]

        raise RuntimeError("Unexpected Ollama response format")

    # --- Not used in MVP ---
    async def structured_output(self, messages: List[Dict[str, str]], schema: type[BaseModel]) -> BaseModel:  # pragma: no cover - not used
        raise RuntimeError("Ollama structured output not implemented")

    async def embed(self, texts: List[str]) -> List[List[float]]:  # pragma: no cover - not used
        raise RuntimeError("Ollama embeddings not implemented")

    async def rerank(self, query: str, documents: List[str], top_n: int) -> List[Dict[str, Any]]:  # pragma: no cover - not used
        raise RuntimeError("Ollama reranking not implemented")


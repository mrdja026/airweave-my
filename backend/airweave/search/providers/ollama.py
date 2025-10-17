"""Ollama provider for local answer generation.

Uses the Ollama HTTP API to run chat completions against a local model
(e.g., gemma:7b). Token counting uses a configurable tokenizer name from
defaults.yml (approximate), enabling context budgeting.
"""

from typing import Any, Dict, List, Optional
import json
import re

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

    async def rerank(self, query: str, documents: List[str], top_n: int) -> List[Dict[str, Any]]:
        """Rerank documents using an Ollama chat prompt.

        The model is asked to return pure JSON of the form:
          {"rankings": [{"index": <int>, "relevance_score": <float 0..1>}, ...]}

        We then map the indices back to the original documents and truncate to top_n.
        """
        if not self.model_spec.llm_model or not self.model_spec.llm_model.name:
            raise RuntimeError("LLM model not configured for Ollama provider")

        if not documents:
            return []

        # Build a compact list of docs with indices for the prompt
        lines = [f"Query: {query}", "", "Documents (index: content):"]
        # Keep input size bounded: if extremely large, cap to 100 to avoid very slow prompts
        capped_docs = documents[: min(len(documents), 100)]
        for i, doc in enumerate(capped_docs):
            # Truncate individual document text to keep the prompt reasonable
            text = (doc or "").replace("\n", " ")
            if len(text) > 2000:
                text = text[:2000] + "…"
            lines.append(f"[{i}] {text}")

        user_prompt = "\n".join(lines) + (
            "\n\nPlease return only JSON in the following schema (no prose):\n"
            '{"rankings": [{"index": <int>, "relevance_score": <float 0..1>}]}'
            "\n- Include each index at most once.\n"
            f"- Return at most {top_n} items.\n"
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "You rerank search results. Output strictly JSON only. "
                    "Do not include code fences or explanations."
                ),
            },
            {"role": "user", "content": user_prompt},
        ]

        model = settings.OLLAMA_MODEL or self.model_spec.llm_model.name
        payload = {"model": model, "messages": messages, "stream": False}

        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            resp = await client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()

        content: Optional[str] = None
        if isinstance(data, dict):
            msg = data.get("message")
            if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                content = msg["content"]
            elif isinstance(data.get("response"), str):
                content = data["response"]
        if not content:
            raise RuntimeError("Unexpected Ollama response format for reranking")

        # Extract JSON from the response (robust to accidental prose or fences)
        parsed = self._parse_rankings_json(content)
        rankings = parsed.get("rankings") if isinstance(parsed, dict) else None
        if not isinstance(rankings, list) or not rankings:
            raise RuntimeError("Ollama returned empty rankings JSON")

        # Normalize, bound indices to provided docs, and slice to top_n
        out: List[Dict[str, Any]] = []
        for item in rankings:
            try:
                idx = int(item.get("index"))
                score = float(item.get("relevance_score", 0))
            except Exception:
                continue
            if 0 <= idx < len(capped_docs):
                out.append({"index": idx, "relevance_score": max(0.0, min(1.0, score))})
            if len(out) >= top_n:
                break

        if not out:
            raise RuntimeError("Ollama produced no usable rankings")

        return out

    def _parse_rankings_json(self, text: str) -> Any:
        """Best-effort extraction of a JSON object from a free-form response."""
        # Common case: the whole content is JSON
        try:
            return json.loads(text)
        except Exception:
            pass

        # Code-fence style
        fence_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text, re.IGNORECASE)
        if fence_match:
            try:
                return json.loads(fence_match.group(1))
            except Exception:
                pass

        # First { ... } block heuristic
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            snippet = text[start : end + 1]
            try:
                return json.loads(snippet)
            except Exception:
                pass

        raise RuntimeError("Failed to parse JSON rankings from Ollama response")

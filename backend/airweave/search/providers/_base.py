"""Base provider for LLM operations."""

import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from tiktoken import Encoding, get_encoding

from airweave.api.context import ApiContext

from .schemas import ProviderModelSpec


class BaseProvider(ABC):
    """Base class for LLM providers."""

    def __init__(self, api_key: str, model_spec: ProviderModelSpec, ctx: ApiContext) -> None:
        """Initialize provider with API key and model specifications."""
        self.api_key = api_key
        self.model_spec = model_spec
        self.ctx = ctx

    @staticmethod
    def is_retryable_error(error: Exception) -> bool:
        """Check if error should trigger provider fallback.

        Retryable errors:
        - Rate limiting (429)
        - Server errors (500, 502, 503, 504)

        Non-retryable errors:
        - Authentication (401, 403)
        - Validation errors (400, 422)
        - Not found (404)

        Args:
            error: Exception to check

        Returns:
            True if error should trigger fallback to next provider
        """
        error_str = str(error).lower()

        # Check for HTTP status codes and error patterns in error message
        retryable_patterns = [
            r"429",  # Rate limit
            r"500",  # Internal server error
            r"502",  # Bad gateway
            r"503",  # Service unavailable
            r"504",  # Gateway timeout
            r"too[_\s]many[_\s]requests",
            r"rate[_\s]limit",
            r"queue[_\s]exceeded",
            r"server[_\s]error",
        ]

        for pattern in retryable_patterns:
            if re.search(pattern, error_str):
                return True

        return False

    def _load_tokenizer(self, tokenizer_name: str, model_type: str) -> Optional[Encoding]:
        """Load a tokenizer by name with consistent error handling."""
        try:
            return get_encoding(tokenizer_name)
        except Exception as e:
            raise RuntimeError(
                f"Failed to load {model_type} tokenizer '{tokenizer_name}': {e}"
            ) from e

    def count_tokens(self, text: str, tokenizer: Optional[Encoding]) -> int:
        """Count tokens in text using a specific tokenizer."""
        if tokenizer is None:
            raise RuntimeError("Tokenizer not initialized for token counting")
        if text is None:
            return 0
        return len(tokenizer.encode(text))

    @abstractmethod
    async def generate(self, messages: List[Dict[str, str]]) -> str:
        """Generate text completion."""
        pass

    @abstractmethod
    async def structured_output(
        self, messages: List[Dict[str, str]], schema: type[BaseModel]
    ) -> BaseModel:
        """Generate structured output conforming to Pydantic schema."""
        pass

    @abstractmethod
    async def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for text."""
        pass

    @abstractmethod
    async def rerank(self, query: str, documents: List[str], top_n: int) -> List[Dict[str, Any]]:
        """Rerank documents by relevance to query."""
        pass

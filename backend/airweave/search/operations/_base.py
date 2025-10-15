from abc import ABC, abstractmethod
from typing import Any, Callable, List, TypeVar

from airweave.api.context import ApiContext
from airweave.search.context import SearchContext
from airweave.search.providers._base import BaseProvider

T = TypeVar("T")


class SearchOperation(ABC):
    """Base class for all search operations."""

    @abstractmethod
    def depends_on(self) -> List[str]:
        """List of operation names this operation depends on."""
        pass

    @abstractmethod
    async def execute(
        self,
        context: SearchContext,
        state: dict[str, Any],
        ctx: ApiContext,
    ) -> None:
        """Execute the operation."""
        pass

    async def _execute_with_provider_fallback(
        self,
        providers: List[BaseProvider],
        operation_call: Callable[[BaseProvider], Any],
        operation_name: str,
        ctx: ApiContext,
    ) -> T:
        """Execute an operation with provider fallback on retryable errors.

        This is a generic fallback handler that tries providers in preference order.
        If a provider fails with a retryable error (429, 5xx), it tries the next one.

        Args:
            providers: List of providers to try in order
            operation_call: Async callable that takes a provider and returns the result
            operation_name: Name of the operation for logging
            ctx: API context for logging

        Returns:
            Result from the provider call

        Raises:
            RuntimeError: If all providers fail with retryable errors
            Exception: If a non-retryable error occurs
        """
        last_error = None
        for i, provider in enumerate(providers):
            try:
                ctx.logger.debug(
                    f"[{operation_name}] Attempting with provider {provider.__class__.__name__} "
                    f"({i + 1}/{len(providers)})"
                )
                result = await operation_call(provider)
                if i > 0:
                    ctx.logger.debug(
                        f"[{operation_name}] Succeeded with fallback provider "
                        f"{provider.__class__.__name__}"
                    )
                return result
            except Exception as e:
                last_error = e
                if BaseProvider.is_retryable_error(e) and i < len(providers) - 1:
                    ctx.logger.warning(
                        f"[{operation_name}] Provider {provider.__class__.__name__} failed "
                        f"with retryable error: {e}. Trying next provider..."
                    )
                    continue
                else:
                    # Non-retryable error or last provider - raise immediately
                    raise

        # All providers failed with retryable errors
        raise RuntimeError(
            f"All {len(providers)} providers failed for {operation_name}. Last error: {last_error}"
        )

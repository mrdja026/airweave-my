"""Answer generation operation.

Generates natural language answers from search results using LLM.
Synthesizes information from multiple results into a coherent response
with inline citations.
"""

from typing import Any, Dict, List

from airweave.api.context import ApiContext
from airweave.search.context import SearchContext
from airweave.search.prompts import GENERATE_ANSWER_SYSTEM_PROMPT
from airweave.search.providers._base import BaseProvider

from ._base import SearchOperation


class GenerateAnswer(SearchOperation):
    """Generate AI completion from search results."""

    # Conservative defaults to support smaller local models (e.g., Ollama 8k ctx)
    MAX_COMPLETION_TOKENS = 1024
    SAFETY_TOKENS = 256

    def __init__(self, providers: List[BaseProvider]) -> None:
        """Initialize with list of LLM providers in preference order.

        Args:
            providers: List of LLM providers for answer generation with fallback support
        """
        if not providers:
            raise ValueError("GenerateAnswer requires at least one provider")
        self.providers = providers

    def depends_on(self) -> List[str]:
        """Depends on Retrieval, FederatedSearch (if enabled), and Reranking to have all results."""
        return ["Retrieval", "FederatedSearch", "Reranking"]

    async def execute(
        self,
        context: SearchContext,
        state: dict[str, Any],
        ctx: ApiContext,
    ) -> None:
        """Generate natural language answer from results."""
        ctx.logger.debug("[GenerateAnswer] Generating natural language answer from results")

        results = state.get("results")

        if not results:
            state["completion"] = "No results found for your query."
            return

        if not isinstance(results, list):
            raise ValueError(f"Expected 'results' to be a list, got {type(results)}")

        # Emit completion start
        # Note: Model name not included since we don't know which provider will succeed yet
        await context.emitter.emit(
            "completion_start",
            {},
            op_name=self.__class__.__name__,
        )

        # Generate answer with provider fallback
        # Token budgeting happens per-provider since context windows differ
        async def call_provider(provider: BaseProvider) -> str:
            if not provider.model_spec.llm_model:
                raise RuntimeError("LLM model not configured for provider")

            # Budget and format results for THIS SPECIFIC provider
            formatted_context, chosen_count = self._budget_and_format_results(
                results, context.query, provider
            )
            ctx.logger.debug(
                f"[GenerateAnswer] {chosen_count} results fit in {provider.__class__.__name__} "
                f"context window"
            )

            # Build messages for LLM
            system_prompt = GENERATE_ANSWER_SYSTEM_PROMPT.format(context=formatted_context)
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": context.query},
            ]

            return await provider.generate(messages)

        completion = await self._execute_with_provider_fallback(
            providers=self.providers,
            operation_call=call_provider,
            operation_name="GenerateAnswer",
            ctx=ctx,
        )

        if not completion or not completion.strip():
            raise RuntimeError("Provider returned empty completion")

        state["completion"] = completion

        # Emit completion done
        await context.emitter.emit(
            "completion_done",
            {"text": completion},
            op_name=self.__class__.__name__,
        )

    def _budget_and_format_results(
        self, results: List[Dict], query: str, provider: BaseProvider
    ) -> tuple[str, int]:
        """Format results while respecting token budget for specific provider.

        Args:
            results: Search results to format
            query: User query
            provider: The actual provider that will be used (not a random one!)

        Returns:
            Tuple of (formatted_context, chosen_count)
        """
        tokenizer = getattr(provider, "llm_tokenizer", None)
        if not tokenizer:
            raise RuntimeError(
                "LLM tokenizer not initialized. "
                "Ensure tokenizer is configured in defaults.yml for this provider."
            )

        context_window = provider.model_spec.llm_model.context_window
        if not context_window:
            raise RuntimeError("Context window not configured for LLM model")

        static_text = GENERATE_ANSWER_SYSTEM_PROMPT.format(context="") + query
        static_tokens = provider.count_tokens(static_text, tokenizer)

        budget = context_window - static_tokens - self.MAX_COMPLETION_TOKENS - self.SAFETY_TOKENS

        if budget <= 0:
            raise RuntimeError(
                f"Insufficient token budget for answer generation. "
                f"Context window: {context_window}, static tokens: {static_tokens}"
            )

        # Fit as many results as possible within budget
        separator = "\n\n---\n\n"
        chosen_parts: List[str] = []
        chosen_count = 0
        running_tokens = 0

        for i, result in enumerate(results):
            formatted_result = self._format_single_result(i + 1, result)
            result_tokens = provider.count_tokens(formatted_result, tokenizer)
            separator_tokens = provider.count_tokens(separator, tokenizer) if i > 0 else 0

            if running_tokens + result_tokens + separator_tokens <= budget:
                if i > 0:
                    chosen_parts.append(separator)
                chosen_parts.append(formatted_result)
                running_tokens += result_tokens + separator_tokens
                chosen_count += 1
            else:
                break

        # Ensure at least one result if possible
        if not chosen_parts and results:
            first_result = self._format_single_result(1, results[0])
            first_tokens = provider.count_tokens(first_result, tokenizer)
            if first_tokens <= budget:
                return first_result, 1
            raise RuntimeError(
                f"First result ({first_tokens} tokens) exceeds token budget ({budget} tokens). "
                "Results may be too large or context window too small."
            )

        return "".join(chosen_parts), chosen_count

    def _format_single_result(self, index: int, result: Dict) -> str:
        """Format a single search result for LLM context.

        Args:
            index: Result index (1-based)
            result: Single search result

        Returns:
            Formatted string with entity ID and content
        """
        # Extract payload and score
        if isinstance(result, dict) and "payload" in result:
            payload = result["payload"]
            score = result.get("score", 0.0)
        else:
            payload = result
            score = 0.0

        # Extract entity ID
        entity_id = (
            payload.get("entity_id") or payload.get("id") or payload.get("_id") or f"result_{index}"
        )

        # Build formatted entry
        parts = [f"### Result {index} - Entity ID: [[{entity_id}]] (Score: {score:.3f})"]

        # Add optional fields
        if "source_name" in payload:
            parts.append(f"**Source:** {payload['source_name']}")

        if "title" in payload:
            parts.append(f"**Title:** {payload['title']}")

        # Add content fields
        self._add_content_to_parts(parts, payload)

        # Add metadata
        self._add_metadata_to_parts(parts, payload)

        if "created_at" in payload:
            parts.append(f"**Created:** {payload['created_at']}")

        return "\n".join(parts)

    def _add_content_to_parts(self, parts: List[str], payload: Dict) -> None:
        """Add content fields to parts list.

        Args:
            parts: List to append formatted content to
            payload: Result payload containing content fields
        """
        # Prefer embeddable_text, fallback to md_content, then others
        embeddable_text = payload.get("embeddable_text", "").strip()
        if embeddable_text:
            parts.append(f"**Content:**\n{embeddable_text}")
            return

        md_content = payload.get("md_content", "").strip()
        if md_content:
            parts.append(f"**Content:**\n{md_content}")
            return

        content = payload.get("content") or payload.get("text") or payload.get("description", "")
        if content:
            parts.append(f"**Content:**\n{content}")

    def _add_metadata_to_parts(self, parts: List[str], payload: Dict) -> None:
        """Add metadata fields to parts list.

        Args:
            parts: List to append formatted metadata to
            payload: Result payload containing metadata
        """
        if "metadata" not in payload or not isinstance(payload["metadata"], dict):
            return

        metadata_items = []
        for key, value in payload["metadata"].items():
            if key not in ["content", "text", "description"]:  # Avoid duplicates
                metadata_items.append(f"- {key}: {value}")

        if metadata_items:
            # Limit to 5 metadata items to avoid clutter
            parts.append("**Metadata:**\n" + "\n".join(metadata_items[:5]))

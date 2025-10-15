"""Federated search operation.

Executes searches against federated sources (e.g., Slack) that don't sync data
but provide search APIs. Results are retrieved at query time, scored, and merged
with vector database results using Reciprocal Rank Fusion (RRF).
"""

import asyncio
from typing import Any, Dict, List, Tuple

from pydantic import BaseModel, Field

from airweave.api.context import ApiContext
from airweave.platform.sources._base import BaseSource
from airweave.search.context import SearchContext
from airweave.search.providers._base import BaseProvider

from ._base import SearchOperation


class QueryKeywords(BaseModel):
    """Structured output schema for keyword extraction."""

    model_config = {"extra": "forbid"}

    # Enforce exactly 5 keywords using a fixed-size tuple (Cerebras prefixItems)
    keywords: Tuple[str, str, str, str, str] = Field(
        description=(
            "Return EXACTLY 5 highly relevant keywords or short phrases. Include a mix of "
            "single words and 2-3 word phrases that best represent the shared intent. "
            "These will be used directly in search API queries."
        )
    )


class FederatedSearch(SearchOperation):
    """Execute federated search and merge with vector results using RRF."""

    # RRF constant (same as used in vector hybrid search)
    RRF_K = 60

    # Deduplication multiplier - fetch extra results to compensate for duplicates
    # across query variations (1.5 = fetch 50% more to account for ~33% duplication)
    DEDUP_MULTIPLIER = 1.5

    # Rate limit delay between sequential queries (seconds)
    RATE_LIMIT_DELAY_SECONDS = 0.1

    def __init__(
        self, sources: List[BaseSource], limit: int, providers: List[BaseProvider]
    ) -> None:
        """Initialize with list of federated sources.

        Args:
            sources: List of source instances that support federated search
            limit: Maximum results to request from each source
            providers: List of LLM providers for keyword extraction with fallback support

        Raises:
            ValueError: If operation created without any sources or providers
        """
        if not sources:
            raise ValueError(
                "FederatedSearch operation requires at least one source. "
                "This operation should only be created when federated sources exist."
            )
        if not providers:
            raise ValueError(
                "FederatedSearch operation requires at least one provider for keyword extraction."
            )
        if not limit:
            raise ValueError(
                "FederatedSearch operation requires a limit for the number of results to return."
            )
        self.sources = sources
        self.limit = limit
        self.providers = providers

    def depends_on(self) -> List[str]:
        """Depends on Retrieval to have vector results for merging."""
        return ["QueryExpansion", "Retrieval"]

    async def execute(
        self,
        context: SearchContext,
        state: dict[str, Any],
        ctx: ApiContext,
    ) -> None:
        """Execute federated search and merge with vector results using RRF.

        Retrieves results from federated sources, scores them, and merges with
        vector database results using Reciprocal Rank Fusion. The merged results
        are then limited to the requested number and replace the state results.
        """
        ctx.logger.debug(f"[FederatedSearch] Searching {len(self.sources)} federated source(s)")

        vector_results = state.get("results", [])
        ctx.logger.debug(f"[FederatedSearch] Starting with {len(vector_results)} vector results")

        all_queries = [context.query] + state.get("expanded_queries", [])

        keywords_to_search = await self._extract_keywords_from_queries(all_queries, ctx)

        ctx.logger.debug(
            f"[FederatedSearch] Extracted {len(keywords_to_search)} unique keywords: "
            f"{keywords_to_search}"
        )

        # Emit federated search start
        await context.emitter.emit(
            "federated_search_start",
            {
                "num_sources": len(self.sources),
                "source_names": [s.__class__.__name__ for s in self.sources],
                "num_keywords": len(keywords_to_search),
                "keywords": keywords_to_search,
            },
            op_name=self.__class__.__name__,
        )

        all_results: List[Dict] = []

        for source in self.sources:
            source_name = source.__class__.__name__
            ctx.logger.debug(f"[FederatedSearch] Searching {source_name}")

            try:
                # Emit per-source start
                await context.emitter.emit(
                    "federated_source_start",
                    {"source": source_name, "num_keywords": len(keywords_to_search)},
                    op_name=self.__class__.__name__,
                )

                # Distribute limit across keywords with padding for deduplication
                per_keyword_limit = max(
                    1, int((self.limit * self.DEDUP_MULTIPLIER) // len(keywords_to_search))
                )

                ctx.logger.debug(
                    f"[FederatedSearch] Distributing limit: {self.limit} requested, "
                    f"{per_keyword_limit} per keyword "
                    f"({len(keywords_to_search)} keywords, {self.DEDUP_MULTIPLIER}x padding)"
                )

                # Execute searches concurrently
                keyword_results_lists = await asyncio.gather(
                    *[
                        self._search_single_keyword(
                            source,
                            keyword,
                            per_keyword_limit,
                            source_name,
                            idx,
                            len(keywords_to_search),
                            ctx,
                        )
                        for idx, keyword in enumerate(keywords_to_search)
                    ],
                    return_exceptions=True,
                )

                # Deduplicate and collect results
                source_results = self._dedup_and_convert_results(
                    keyword_results_lists=keyword_results_lists,
                    source_name=source_name,
                    keywords=keywords_to_search,
                    ctx=ctx,
                )
                entity_count = len(source_results)
                all_results.extend(source_results)

                # Emit per-source done
                await context.emitter.emit(
                    "federated_source_done",
                    {"source": source_name, "result_count": entity_count},
                    op_name=self.__class__.__name__,
                )

            except Exception as e:
                ctx.logger.error(f"[FederatedSearch] Error searching {source_name}: {e}")
                # Emit error event but continue with other sources
                await context.emitter.emit(
                    "federated_source_error",
                    {"source": source_name, "error": str(e)},
                    op_name=self.__class__.__name__,
                )
                raise ValueError(f"Error searching {source_name} at query time: {e}")

        ctx.logger.debug(f"[FederatedSearch] Retrieved {len(all_results)} federated results")

        # Check if we got any federated results
        if not all_results:
            ctx.logger.info(
                "[FederatedSearch] No results from federated sources, keeping vector results"
            )
            # Emit event for observability
            await context.emitter.emit(
                "federated_search_no_results",
                {
                    "num_sources_searched": len(self.sources),
                    "vector_count": len(vector_results),
                },
                op_name=self.__class__.__name__,
            )
            # If there were no vector results and we're in federated-only flow,
            # write an explicit empty list to indicate that this operation ran.
            if "results" not in state:
                state["results"] = []
            return

        # Merge vector and federated results using RRF
        merged_results = self._merge_with_rrf(vector_results, all_results, ctx)

        # Limit to requested number of results
        limit = context.retrieval.limit if context.retrieval else context.limit
        final_results = merged_results[:limit]

        ctx.logger.debug(
            f"[FederatedSearch] After RRF merge and limit: {len(final_results)} results "
            f"({len(vector_results)} vector + {len(all_results)} federated)"
        )

        # Replace results in state with merged results
        state["results"] = final_results

        # Emit federated search done
        await context.emitter.emit(
            "federated_search_done",
            {
                "federated_count": len(all_results),
                "vector_count": len(vector_results),
                "merged_count": len(final_results),
            },
            op_name=self.__class__.__name__,
        )

    async def _extract_keywords_from_queries(
        self, queries: List[str], ctx: ApiContext
    ) -> List[str]:
        """Extract keywords from all query variations using a single LLM call.

        Args:
            queries: List of query strings (original + expansions)
            ctx: API context for logging

        Returns:
            List of 3-5 keywords/short phrases optimized for search APIs
        """
        # Format queries for the prompt
        if len(queries) == 1:
            queries_text = f"Original query: {queries[0]}"
        else:
            original = queries[0]
            numbered_expansions = "\n".join(
                [f"{i}. {q}" for i, q in enumerate(queries[1:], start=1)]
            )
            queries_text = (
                "Original query: "
                + original
                + "\nExpanded query variants (same intent):\n"
                + numbered_expansions
            )

        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Extract 8-10 important keywords or short phrases that capture "
                        "the core search intent. Always include a mix of single-word "
                        "keywords (e.g., 'incident', 'latency') AND 2-3 word phrases "
                        "(e.g., 'deploy failure'). Optimize for search APIs: prioritize "
                        "specific, searchable terms. If multiple query phrasings are "
                        "provided, reflect the shared intent across all variations. "
                        "Return concise tokens without quotes or punctuation."
                    ),
                },
                {"role": "user", "content": queries_text},
            ]

            # Extract keywords with provider fallback
            async def call_provider(provider: BaseProvider) -> BaseModel:
                return await provider.structured_output(messages, QueryKeywords)

            result = await self._execute_with_provider_fallback(
                providers=self.providers,
                operation_call=call_provider,
                operation_name="FederatedSearch",
                ctx=ctx,
            )

            # Normalize and ensure single-word coverage
            extracted = [kw.strip() for kw in result.keywords if isinstance(kw, str)]
            return extracted

        except Exception as e:
            raise ValueError(f"Failed to extract keywords from queries: {e}")

    async def _search_single_keyword(
        self,
        source: BaseSource,
        keyword: str,
        limit: int,
        source_name: str,
        keyword_idx: int,
        total_keywords: int,
        ctx: ApiContext,
    ) -> List[Any]:
        """Search with a single keyword and return entities.

        Args:
            source: Source instance to search
            keyword: Keyword to search for
            limit: Maximum results for this keyword
            source_name: Name of the source (for logging)
            keyword_idx: Index of this keyword (for logging)
            total_keywords: Total number of keywords (for logging)
            ctx: API context for logging

        Returns:
            List of entities from the search
        """
        ctx.logger.debug(
            f"[FederatedSearch] {source_name} keyword "
            f"{keyword_idx + 1}/{total_keywords}: '{keyword}'"
        )

        # Direct await - no async iteration needed
        entities = await source.search(keyword, limit=limit)

        ctx.logger.debug(
            f"[FederatedSearch] Keyword {keyword_idx + 1} fetched {len(entities)} results"
        )

        return entities

    def _dedup_and_convert_results(
        self,
        keyword_results_lists: List[Any],
        source_name: str,
        keywords: List[str],
        ctx: ApiContext,
    ) -> List[Dict]:
        """Deduplicate entities across keyword result lists and convert to results.

        Mirrors the existing behavior in execute: raises on per-keyword errors,
        logs per-keyword unique counts, and returns converted results.

        Args:
            keyword_results_lists: List of per-keyword result lists or Exceptions
            source_name: Name of the federated source
            keywords: Keywords corresponding to result lists (for logging)
            ctx: API context for logging

        Returns:
            List of result dictionaries in vector DB format
        """
        seen_entity_ids = set()
        results: List[Dict] = []

        for idx, keyword_results in enumerate(keyword_results_lists):
            # Handle exceptions from individual keywords
            if isinstance(keyword_results, Exception):
                raise ValueError(f"Error searching {source_name} at query time: {keyword_results}")

            # Add unique results
            keyword_unique_count = 0
            for entity in keyword_results:
                if getattr(entity, "entity_id", None) in seen_entity_ids:
                    continue
                seen_entity_ids.add(entity.entity_id)

                result = self._entity_to_result(entity, source_name, len(results))
                results.append(result)
                keyword_unique_count += 1

            ctx.logger.debug(
                f"[FederatedSearch] Keyword {idx + 1} '{keywords[idx]}' "
                f"contributed {keyword_unique_count} unique results"
            )

        ctx.logger.debug(
            f"[FederatedSearch] {source_name} returned {len(results)} unique results "
            f"across {len(keywords)} keywords"
        )

        return results

    def _merge_with_rrf(
        self, vector_results: List[Dict], federated_results: List[Dict], ctx: ApiContext
    ) -> List[Dict]:
        """Merge vector and federated results using Reciprocal Rank Fusion.

        RRF formula: score(d) = Σ(1 / (k + rank(d)))
        where k = 60 (standard RRF constant)

        """
        if not federated_results:
            return vector_results

        if not vector_results:
            return federated_results

        # Calculate RRF scores
        rrf_scores: Dict[str, float] = {}
        result_map: Dict[str, Dict] = {}

        # Process vector results
        for rank, result in enumerate(vector_results):
            result_id = self._get_result_id(result)
            rrf_scores[result_id] = rrf_scores.get(result_id, 0) + (1 / (self.RRF_K + rank + 1))
            result_map[result_id] = result

        # Process federated results
        for rank, result in enumerate(federated_results):
            result_id = self._get_result_id(result)
            rrf_scores[result_id] = rrf_scores.get(result_id, 0) + (1 / (self.RRF_K + rank + 1))
            result_map[result_id] = result

        # Sort by RRF score
        sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)

        # Build merged results with RRF scores
        merged = []
        for result_id in sorted_ids:
            result = result_map[result_id]
            # Update score to RRF score
            result["score"] = rrf_scores[result_id]
            merged.append(result)

        ctx.logger.debug(
            f"[FederatedSearch] RRF merge: {len(vector_results)} vector + "
            f"{len(federated_results)} federated = {len(merged)} unique results"
        )

        return merged

    def _get_result_id(self, result: Dict) -> str:
        """Extract unique ID from result."""
        # Try different ID fields
        return (
            result.get("id")
            or result.get("payload", {}).get("entity_id")
            or result.get("payload", {}).get("id")
            or result.get("payload", {}).get("_id")
            or str(result)
        )

    def _entity_to_result(self, entity: Any, source_name: str, rank: int) -> Dict:
        """Convert entity to result dictionary matching vector DB format.

        Args:
            entity: ChunkEntity from federated source
            source_name: Name of the source
            rank: Position of this result in the source's result list (for RRF)

        Returns:
            Dictionary with result data in vector DB format
        """
        # Convert entity to storage dict (similar to what goes in vector DB)
        payload = entity.to_storage_dict()

        # Extract score if available (from entity metadata or system metadata)
        score = 0.0
        if hasattr(entity, "score") and entity.score is not None:
            score = float(entity.score)

        # Build result in same format as Qdrant results
        result = {
            "id": entity.entity_id,
            "score": score,
            "payload": payload,
            "source_type": "federated",  # Mark as federated for debugging
        }

        return result

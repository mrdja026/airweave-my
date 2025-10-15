import asyncio
import time
import uuid
from typing import Any, Dict, List

import httpx
from monke.bongos.base_bongo import BaseBongo
from monke.generation.linear import generate_linear_issue
from monke.utils.logging import get_logger

LINEAR_GQL = "https://api.linear.app/graphql"


class LinearBongo(BaseBongo):
    connector_type = "linear"

    def __init__(self, credentials: Dict[str, Any], **kwargs):
        super().__init__(credentials)
        self._credentials = credentials  # Store for token refresh
        self.access_token: str = credentials[
            "access_token"
        ]  # Personal API key or OAuth token
        self.entity_count: int = int(kwargs.get("entity_count", 3))
        self.openai_model: str = kwargs.get("openai_model", "gpt-4.1-mini")
        self.rate_limit_delay = float(kwargs.get("rate_limit_delay_ms", 500)) / 1000.0
        self.logger = get_logger("linear_bongo")
        self._issues: List[Dict[str, Any]] = []
        self._last_req = 0.0
        
        # Store Composio config for token refresh if available
        self._composio_config = kwargs.get("composio_config")

    async def create_entities(self) -> List[Dict[str, Any]]:
        self.logger.info(f"🥁 Creating {self.entity_count} Linear issues")
        async with httpx.AsyncClient(timeout=30) as client:
            team_id = await self._first_team_id(client)
            out: List[Dict[str, Any]] = []
            for _ in range(self.entity_count):
                await self._pace()
                token = str(uuid.uuid4())[:8]
                data = await generate_linear_issue(self.openai_model, token)
                q = """
                mutation IssueCreate($input: IssueCreateInput!) {
                  issueCreate(input: $input) {
                    success
                    issue { id identifier title url }
                  }
                }"""
                variables = {
                    "input": {
                        "teamId": team_id,
                        "title": data.spec.title,
                        "description": data.content.description,
                    }
                }
                resp = await self._gql(client, q, variables)
                issue = ((resp.get("data") or {}).get("issueCreate") or {}).get("issue")
                if not issue:
                    raise RuntimeError(f"Linear issueCreate failed: {resp}")
                ent = {
                    "type": "issue",
                    "id": issue["id"],
                    "name": issue["title"],
                    "token": token,
                    "expected_content": token,
                    "path": f"linear/issue/{issue['identifier']}",
                }
                out.append(ent)
                self._issues.append(ent)
                self.created_entities.append(
                    {"id": issue["id"], "name": issue["title"]}
                )

                # add 1-2 comments (best effort)
                for c in data.content.comments[:2]:
                    await self._pace()
                    qc = """
                    mutation CommentCreate($input: CommentCreateInput!) {
                      commentCreate(input: $input) { success comment { id } }
                    }"""
                    _ = await self._gql(
                        client, qc, {"input": {"issueId": issue["id"], "body": c}}
                    )
            return out

    async def update_entities(self) -> List[Dict[str, Any]]:
        if not self._issues:
            return []
        self.logger.info("🥁 Updating some Linear issues (title tweak)")
        async with httpx.AsyncClient(timeout=30) as client:
            updated = []
            for ent in self._issues[: min(3, len(self._issues))]:
                await self._pace()
                q = """
                mutation IssueUpdate($id: String!, $input: IssueUpdateInput!) {
                  issueUpdate(id: $id, input: $input) { success issue { id title } }
                }"""
                resp = await self._gql(
                    client,
                    q,
                    {"id": ent["id"], "input": {"title": ent["name"] + " [updated]"}},
                )
                updated.append({**ent, "updated": True})
            return updated

    async def delete_entities(self) -> List[str]:
        return await self.delete_specific_entities(self._issues)

    async def delete_specific_entities(
        self, entities: List[Dict[str, Any]]
    ) -> List[str]:
        self.logger.info(f"🥁 Deleting/archiving {len(entities)} Linear issues")
        deleted: List[str] = []
        async with httpx.AsyncClient(timeout=30) as client:
            for ent in entities:
                try:
                    await self._pace()
                    q = """mutation IssueArchive($id: String!) { issueArchive(id: $id) { success } }"""
                    r = await self._gql(client, q, {"id": ent["id"]})
                    deleted.append(ent["id"])
                except Exception as e:
                    self.logger.warning(f"archive failed for {ent['id']}: {e}")
        return deleted

    async def cleanup(self):
        """Comprehensive cleanup of all test Linear issues."""
        self.logger.info("🧹 Starting comprehensive Linear cleanup")

        cleanup_stats = {"issues_deleted": 0, "errors": 0}

        try:
            # First, delete current session issues
            if self._issues:
                self.logger.info(
                    f"🗑️ Cleaning up {len(self._issues)} current session issues"
                )
                deleted = await self.delete_specific_entities(self._issues)
                cleanup_stats["issues_deleted"] += len(deleted)
                self._issues.clear()

            # Search for any remaining monke test issues
            await self._cleanup_orphaned_test_issues(cleanup_stats)

            self.logger.info(
                f"🧹 Cleanup completed: {cleanup_stats['issues_deleted']} issues deleted, "
                f"{cleanup_stats['errors']} errors"
            )
        except Exception as e:
            self.logger.error(f"❌ Error during comprehensive cleanup: {e}")

    async def _cleanup_orphaned_test_issues(self, stats: Dict[str, Any]):
        """Find and delete orphaned test issues from previous runs."""
        try:
            async with httpx.AsyncClient(
                base_url="https://api.linear.app", timeout=30
            ) as client:
                # Search for issues with test patterns in title
                query = """query {
                    issues(filter: {
                        or: [
                            { title: { contains: "Test" } },
                            { title: { contains: "monke" } },
                            { title: { contains: "Demo" } }
                        ]
                    }, first: 100) {
                        nodes { id title }
                    }
                }"""

                resp = await self._gql(client, query, {})
                issues = ((resp.get("data") or {}).get("issues") or {}).get(
                    "nodes"
                ) or []

                # Filter for actual test issues
                test_issues = [
                    issue
                    for issue in issues
                    if any(
                        pattern in issue.get("title", "").lower()
                        for pattern in ["test", "monke", "demo", "sample"]
                    )
                ]

                if test_issues:
                    self.logger.info(
                        f"🔍 Found {len(test_issues)} potential test issues to clean"
                    )
                    for issue in test_issues:
                        try:
                            await self._pace()
                            mutation = "mutation($id: String!) { issueDelete(id: $id) { success } }"
                            result = await self._gql(
                                client, mutation, {"id": issue["id"]}
                            )

                            if (
                                result.get("data", {})
                                .get("issueDelete", {})
                                .get("success")
                            ):
                                stats["issues_deleted"] += 1
                                self.logger.info(
                                    f"✅ Deleted orphaned issue: {issue.get('title')}"
                                )
                            else:
                                stats["errors"] += 1
                        except Exception as e:
                            stats["errors"] += 1
                            self.logger.warning(
                                f"⚠️ Failed to delete issue {issue['id']}: {e}"
                            )
        except Exception as e:
            self.logger.warning(f"⚠️ Could not search for orphaned issues: {e}")

    async def _first_team_id(self, client: httpx.AsyncClient) -> str:
        q = "query { teams(first: 1) { nodes { id name key } } }"
        resp = await self._gql(client, q, {})
        nodes = ((resp.get("data") or {}).get("teams") or {}).get("nodes") or []
        if not nodes:
            raise RuntimeError("No Linear teams available for API key")
        return nodes[0]["id"]

    async def _refresh_token(self):
        """Refresh the access token from Composio."""
        try:
            from monke.auth.broker import ComposioBroker

            self.logger.info("🔄 Refreshing Linear access token...")
            
            if self._composio_config:
                # Use the specific Composio configuration for this connector
                broker = ComposioBroker(
                    account_id=self._composio_config["account_id"],
                    auth_config_id=self._composio_config["auth_config_id"],
                )
                fresh_creds = await broker.get_credentials("linear")
            else:
                # Fallback to generic credentials resolver
                from monke.auth.credentials_resolver import resolve_credentials
                fresh_creds = await resolve_credentials("linear", self._credentials)
            
            self.access_token = fresh_creds["access_token"]
            self.logger.info("✅ Linear access token refreshed")
        except Exception as e:
            self.logger.error(f"❌ Failed to refresh Linear token: {e}")
            raise

    async def _gql(
        self, client: httpx.AsyncClient, query: str, variables: Dict[str, Any]
    ) -> Dict[str, Any]:
        r = await client.post(
            LINEAR_GQL,
            headers={
                "Content-Type": "application/json",
                "Authorization": self.access_token,
            },
            json={"query": query, "variables": variables},
        )

        # Handle 401 authentication errors by refreshing token and retrying
        if r.status_code == 401:
            self.logger.warning("🔑 Linear token expired, refreshing...")
            await self._refresh_token()
            # Retry with fresh token
            r = await client.post(
                LINEAR_GQL,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": self.access_token,
                },
                json={"query": query, "variables": variables},
            )

        if r.status_code != 200:
            raise RuntimeError(f"Linear GraphQL error {r.status_code}: {r.text}")
        return r.json()

    async def _pace(self):
        now = time.time()
        if (delta := now - self._last_req) < self.rate_limit_delay:
            await asyncio.sleep(self.rate_limit_delay - delta)
        self._last_req = time.time()

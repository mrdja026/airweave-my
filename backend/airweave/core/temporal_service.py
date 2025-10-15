"""Service for integrating Temporal workflows."""

from typing import Optional

from temporalio.client import WorkflowHandle

from airweave import schemas
from airweave.api.context import ApiContext
from airweave.core.config import settings
from airweave.core.logging import logger
from airweave.platform.temporal.client import temporal_client
from airweave.platform.temporal.workflows import RunSourceConnectionWorkflow


class TemporalService:
    """Service for managing Temporal workflows."""

    async def run_source_connection_workflow(
        self,
        sync: schemas.Sync,
        sync_job: schemas.SyncJob,
        sync_dag: schemas.SyncDag,
        collection: schemas.Collection,
        connection: schemas.Connection,  # Connection, NOT SourceConnection
        ctx: ApiContext,
        access_token: Optional[str] = None,
        force_full_sync: bool = False,
    ) -> WorkflowHandle:
        """Start a source connection sync workflow.

        Args:
            sync: The sync configuration
            sync_job: The sync job
            sync_dag: The sync DAG
            collection: The collection
            connection: The connection (Connection schema, NOT SourceConnection)
            ctx: The API context
            access_token: Optional access token
            force_full_sync: If True, forces a full sync with orphaned entity cleanup

        Returns:
            The workflow handle
        """
        client = await temporal_client.get_client()
        task_queue = settings.TEMPORAL_TASK_QUEUE

        # Generate a unique workflow ID
        workflow_id = f"sync-{sync_job.id}"

        ctx.logger.info(f"Starting Temporal workflow {workflow_id} for sync job {sync_job.id}")
        ctx.logger.info(f"Connection: {connection.name} | Collection: {collection.name}")
        if force_full_sync:
            ctx.logger.info("🔄 Force full sync enabled - will ignore cursor data")

        # Convert Pydantic models to dicts for JSON serialization
        handle = await client.start_workflow(
            RunSourceConnectionWorkflow.run,
            args=[
                sync.model_dump(mode="json"),
                sync_job.model_dump(mode="json"),
                sync_dag.model_dump(mode="json"),
                collection.model_dump(mode="json"),
                connection.model_dump(mode="json"),
                ctx.to_serializable_dict(),  # Use serializable dict instead of model_dump
                access_token,
                force_full_sync,
            ],
            id=workflow_id,
            task_queue=task_queue,
        )

        ctx.logger.info("✅ Temporal workflow started successfully!")

        return handle

    async def cancel_sync_job_workflow(self, sync_job_id: str, ctx: ApiContext) -> dict:
        """Request cancellation of a running workflow by sync job ID.

        Semantics: This method only acknowledges that a cancellation request was
        sent to Temporal. It does not guarantee the Workflow has observed and
        completed graceful cancellation yet.

        Args:
            sync_job_id: The sync job ID to cancel
            ctx: The API context

        Returns:
            True if a cancellation request was sent, False otherwise
        """
        client = await temporal_client.get_client()
        workflow_id = f"sync-{sync_job_id}"
        try:
            handle = client.get_workflow_handle(workflow_id)
            await handle.cancel()
            ctx.logger.info(f"\n\nCancellation requested for workflow {workflow_id}\n\n")
            return True
        except Exception as e:
            # Workflow may not exist or Temporal may be unavailable
            ctx.logger.error(f"Failed to request cancellation for {workflow_id}: {e}")
            return False

    async def is_temporal_enabled(self) -> bool:
        """Check if Temporal is enabled and available.

        Returns:
            True if Temporal is enabled, False otherwise
        """
        temporal_enabled = settings.TEMPORAL_ENABLED

        if not temporal_enabled:
            return False

        try:
            _ = await temporal_client.get_client()
            return True
        except Exception as e:
            logger.warning(f"Temporal not available: {e}")
            return False


temporal_service = TemporalService()

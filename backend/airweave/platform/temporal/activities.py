"""Temporal activities for Airweave."""

import asyncio
from contextlib import suppress
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from temporalio import activity

from airweave.core.exceptions import NotFoundException


async def _run_sync_task(
    sync,
    sync_job,
    sync_dag,
    collection,
    connection,
    ctx,
    access_token,
    force_full_sync=False,
):
    """Run the actual sync service."""
    from airweave.core.exceptions import NotFoundException
    from airweave.core.sync_service import sync_service

    try:
        return await sync_service.run(
            sync=sync,
            sync_job=sync_job,
            dag=sync_dag,
            collection=collection,
            source_connection=connection,  # sync_service expects this parameter name
            ctx=ctx,
            access_token=access_token,
            force_full_sync=force_full_sync,
        )
    except NotFoundException as e:
        # Check if this is the specific "Source connection record not found" error
        if "Source connection record not found" in str(e) or "Connection not found" in str(e):
            ctx.logger.info(
                f"🧹 Source connection for sync {sync.id} not found. "
                f"Resource was likely deleted during workflow execution."
            )
            # Re-raise. Custom exception types don't serialize cleanly, so we use a string marker.
            raise Exception("ORPHANED_SYNC: Source connection record not found") from e
        # Other NotFoundException errors should be re-raised as-is
        raise


# Import inside the activity to avoid issues with Temporal's sandboxing
@activity.defn
async def run_sync_activity(
    sync_dict: Dict[str, Any],
    sync_job_dict: Dict[str, Any],
    sync_dag_dict: Dict[str, Any],
    collection_dict: Dict[str, Any],
    connection_dict: Dict[str, Any],
    ctx_dict: Dict[str, Any],
    access_token: Optional[str] = None,
    force_full_sync: bool = False,
) -> None:
    """Activity to run a sync job.

    This activity wraps the existing sync_service.run method.

    Args:
        sync_dict: The sync configuration as dict
        sync_job_dict: The sync job as dict
        sync_dag_dict: The sync DAG as dict
        collection_dict: The collection as dict
        connection_dict: The connection as dict (Connection schema, NOT SourceConnection)
        ctx_dict: The API context as dict
        access_token: Optional access token
        force_full_sync: If True, forces a full sync with orphaned entity deletion
    """
    # Import here to avoid Temporal sandboxing issues
    from airweave import schemas
    from airweave.api.context import ApiContext
    from airweave.core.logging import LoggerConfigurator

    # Convert dicts back to Pydantic models
    sync = schemas.Sync(**sync_dict)
    sync_job = schemas.SyncJob(**sync_job_dict)
    sync_dag = schemas.SyncDag(**sync_dag_dict)
    collection = schemas.Collection(**collection_dict)
    connection = schemas.Connection(**connection_dict)

    # Reconstruct user if present
    user = schemas.User(**ctx_dict["user"]) if ctx_dict.get("user") else None

    # Reconstruct organization from the dictionary
    organization = schemas.Organization(**ctx_dict["organization"])

    ctx = ApiContext(
        request_id=ctx_dict["request_id"],
        organization=organization,
        user=user,
        auth_method=ctx_dict["auth_method"],
        auth_metadata=ctx_dict.get("auth_metadata"),
        logger=LoggerConfigurator.configure_logger(
            "airweave.temporal.activity",
            dimensions={
                "sync_job_id": str(sync_job.id),
                "organization_id": str(organization.id),
                "organization_name": organization.name,
            },
        ),
    )

    ctx.logger.debug(f"\n\nStarting sync activity for job {sync_job.id}\n\n")
    # Start the sync task
    sync_task = asyncio.create_task(
        _run_sync_task(
            sync,
            sync_job,
            sync_dag,
            collection,
            connection,
            ctx,
            access_token,
            force_full_sync,
        )
    )

    try:
        while True:
            done, _ = await asyncio.wait({sync_task}, timeout=1)
            if sync_task in done:
                # Propagate result/exception (including CancelledError from inner task)
                await sync_task
                break
            ctx.logger.debug("HEARTBEAT: Sync in progress")
            activity.heartbeat("Sync in progress")

        ctx.logger.info(f"\n\nCompleted sync activity for job {sync_job.id}\n\n")

    except asyncio.CancelledError:
        ctx.logger.info(f"\n\n[ACTIVITY] Sync activity cancelled for job {sync_job.id}\n\n")
        # 1) Flip job status to CANCELLED immediately so UI reflects truth
        try:
            # Import inside to avoid sandbox issues
            from airweave.core.datetime_utils import utc_now_naive
            from airweave.core.shared_models import SyncJobStatus
            from airweave.core.sync_job_service import sync_job_service

            await sync_job_service.update_status(
                sync_job_id=sync_job.id,
                status=SyncJobStatus.CANCELLED,
                ctx=ctx,
                error="Workflow was cancelled",
                failed_at=utc_now_naive(),
            )
            ctx.logger.debug(f"\n\n[ACTIVITY] Updated job {sync_job.id} to CANCELLED\n\n")
        except Exception as status_err:
            ctx.logger.error(f"Failed to update job {sync_job.id} to CANCELLED: {status_err}")

        # 2) Ensure the internal sync task is cancelled and awaited while heartbeating
        sync_task.cancel()
        while not sync_task.done():
            try:
                await asyncio.wait_for(sync_task, timeout=1)
            except asyncio.TimeoutError:
                activity.heartbeat("Cancelling sync...")
        with suppress(asyncio.CancelledError):
            await sync_task

        # 3) Re-raise so Temporal records the activity as CANCELED
        raise
    except Exception as e:
        ctx.logger.error(f"Failed sync activity for job {sync_job.id}: {e}")
        raise


@activity.defn
async def mark_sync_job_cancelled_activity(
    sync_job_id: str,
    ctx_dict: Dict[str, Any],
    reason: Optional[str] = None,
    when_iso: Optional[str] = None,
) -> None:
    """Mark a sync job as CANCELLED (used when workflow cancels before activity starts).

    Args:
        sync_job_id: The sync job ID (str UUID)
        ctx_dict: Serialized ApiContext dict
        reason: Optional cancellation reason
        when_iso: Optional ISO timestamp for failed_at
    """
    from airweave import schemas
    from airweave.api.context import ApiContext
    from airweave.core.logging import LoggerConfigurator
    from airweave.core.shared_models import SyncJobStatus
    from airweave.core.sync_job_service import sync_job_service

    # Reconstruct context
    organization = schemas.Organization(**ctx_dict["organization"])
    user = schemas.User(**ctx_dict["user"]) if ctx_dict.get("user") else None

    ctx = ApiContext(
        request_id=ctx_dict["request_id"],
        organization=organization,
        user=user,
        auth_method=ctx_dict["auth_method"],
        auth_metadata=ctx_dict.get("auth_metadata"),
        logger=LoggerConfigurator.configure_logger(
            "airweave.temporal.activity.cancel_pre_activity",
            dimensions={
                "sync_job_id": sync_job_id,
                "organization_id": str(organization.id),
                "organization_name": organization.name,
            },
        ),
    )

    failed_at = None
    if when_iso:
        try:
            failed_at = datetime.fromisoformat(when_iso)
        except Exception:
            failed_at = None

    ctx.logger.debug(
        f"[WORKFLOW] Marking sync job {sync_job_id} as CANCELLED (pre-activity): {reason or ''}"
    )

    try:
        await sync_job_service.update_status(
            sync_job_id=UUID(sync_job_id),
            status=SyncJobStatus.CANCELLED,
            ctx=ctx,
            error=reason,
            failed_at=failed_at,
        )
        ctx.logger.debug(f"[WORKFLOW] Updated job {sync_job_id} to CANCELLED")
    except Exception as e:
        ctx.logger.error(f"Failed to update job {sync_job_id} to CANCELLED: {e}")
        raise


@activity.defn
async def create_sync_job_activity(
    sync_id: str,
    ctx_dict: Dict[str, Any],
    force_full_sync: bool = False,
) -> Dict[str, Any]:
    """Create a new sync job for the given sync.

    This activity creates a new sync job in the database, checking first
    if there's already a running job for this sync.

    Args:
        sync_id: The sync ID to create a job for
        ctx_dict: The API context as dict
        force_full_sync: If True (daily cleanup), wait for running jobs to complete

    Returns:
        The created sync job as a dict

    Raises:
        Exception: If a sync job is already running and force_full_sync is False
    """
    from airweave import crud, schemas
    from airweave.api.context import ApiContext
    from airweave.core.logging import LoggerConfigurator
    from airweave.db.session import get_db_context

    # Reconstruct organization and user from the dictionary
    organization = schemas.Organization(**ctx_dict["organization"])
    user = schemas.User(**ctx_dict["user"]) if ctx_dict.get("user") else None

    ctx = ApiContext(
        request_id=ctx_dict["request_id"],
        organization=organization,
        user=user,
        auth_method=ctx_dict["auth_method"],
        auth_metadata=ctx_dict.get("auth_metadata"),
        logger=LoggerConfigurator.configure_logger(
            "airweave.temporal.activity.create_sync_job",
            dimensions={
                "sync_id": sync_id,
                "organization_id": str(organization.id),
                "organization_name": organization.name,
            },
        ),
    )

    ctx.logger.info(f"Creating sync job for sync {sync_id} (force_full_sync={force_full_sync})")

    async with get_db_context() as db:
        # First, check if the sync still exists (defensive check for orphaned workflows)
        try:
            _ = await crud.sync.get(db=db, id=UUID(sync_id), ctx=ctx, with_connections=False)
        except NotFoundException as e:
            ctx.logger.info(
                f"🧹 Could not verify sync {sync_id} exists: {e}. "
                f"Marking as orphaned to trigger cleanup."
            )
            return {"_orphaned": True, "sync_id": sync_id, "reason": f"Sync lookup error: {e}"}

        # Check if there's already a running/cancellable sync job for this sync
        from airweave.core.shared_models import SyncJobStatus

        running_jobs = await crud.sync_job.get_all_by_sync_id(
            db=db,
            sync_id=UUID(sync_id),
            # Database now stores lowercase string statuses
            status=[
                SyncJobStatus.PENDING.value,
                SyncJobStatus.RUNNING.value,
                SyncJobStatus.CANCELLING.value,
            ],
        )

        if running_jobs:
            if force_full_sync:
                # For daily cleanup, wait for running jobs to complete
                ctx.logger.info(
                    f"🔄 Daily cleanup sync for {sync_id}: "
                    f"Found {len(running_jobs)} running job(s). "
                    f"Waiting for them to complete before starting cleanup..."
                )

                # Wait for running jobs to complete (check every 30 seconds)
                import asyncio

                max_wait_time = 60 * 60  # 1 hour max wait
                wait_interval = 30  # Check every 30 seconds
                total_waited = 0

                while total_waited < max_wait_time:
                    # Send heartbeat to prevent timeout
                    activity.heartbeat(f"Waiting for running jobs to complete ({total_waited}s)")

                    # Wait before checking again
                    await asyncio.sleep(wait_interval)
                    total_waited += wait_interval

                    # Check if jobs are still running
                    async with get_db_context() as check_db:
                        still_running = await crud.sync_job.get_all_by_sync_id(
                            db=check_db,
                            sync_id=UUID(sync_id),
                            status=[
                                SyncJobStatus.PENDING.value,
                                SyncJobStatus.RUNNING.value,
                                SyncJobStatus.CANCELLING.value,
                            ],
                        )

                        if not still_running:
                            ctx.logger.info(
                                f"✅ Running jobs completed. "
                                f"Proceeding with cleanup sync for {sync_id}"
                            )
                            break
                else:
                    # Timeout reached
                    ctx.logger.error(
                        f"❌ Timeout waiting for running jobs to complete for sync {sync_id}. "
                        f"Skipping cleanup sync."
                    )
                    raise Exception(
                        f"Timeout waiting for running jobs to complete after {max_wait_time}s"
                    )
            else:
                # For regular incremental syncs, skip if job is running
                ctx.logger.warning(
                    f"Sync {sync_id} already has {len(running_jobs)} running jobs. "
                    f"Skipping new job creation."
                )
                raise Exception(
                    f"Sync {sync_id} already has a running job. "
                    f"Skipping this scheduled run to avoid conflicts."
                )

        # Create the new sync job
        sync_job_in = schemas.SyncJobCreate(sync_id=UUID(sync_id))
        sync_job = await crud.sync_job.create(db=db, obj_in=sync_job_in, ctx=ctx)

        # Access the ID before commit to avoid lazy loading issues
        sync_job_id = sync_job.id

        await db.commit()

        # Refresh the object to ensure all attributes are loaded
        await db.refresh(sync_job)

        ctx.logger.info(f"Created sync job {sync_job_id} for sync {sync_id}")

        # Convert to dict for return
        sync_job_schema = schemas.SyncJob.model_validate(sync_job)
        return sync_job_schema.model_dump(mode="json")


@activity.defn
async def cleanup_stuck_sync_jobs_activity() -> None:
    """Activity to clean up sync jobs stuck in transitional states.

    Detects and cancels:
    - CANCELLING/PENDING jobs stuck for > 3 minutes
    - RUNNING jobs stuck for > 10 minutes with no entity updates

    For each stuck job:
    1. Attempts graceful cancellation via Temporal workflow
    2. Falls back to force-cancelling in the database if workflow doesn't exist
    """
    from datetime import timedelta

    from airweave.api.context import ApiContext
    from airweave.core.datetime_utils import utc_now_naive
    from airweave.core.logging import LoggerConfigurator
    from airweave.core.shared_models import SyncJobStatus
    from airweave.core.sync_job_service import sync_job_service
    from airweave.core.temporal_service import temporal_service
    from airweave.db.session import get_db_context

    # Configure logger for cleanup activity
    logger = LoggerConfigurator.configure_logger(
        "airweave.temporal.cleanup",
        dimensions={"activity": "cleanup_stuck_sync_jobs"},
    )

    logger.info("Starting cleanup of stuck sync jobs...")

    # Calculate cutoff times
    now = utc_now_naive()
    cancelling_pending_cutoff = now - timedelta(minutes=3)
    running_cutoff = now - timedelta(minutes=10)

    stuck_job_count = 0
    cancelled_count = 0
    failed_count = 0

    try:
        async with get_db_context() as db:
            # Import CRUD layer inside to avoid sandbox issues
            from airweave import crud

            # Query 1: Find CANCELLING/PENDING jobs stuck for > 3 minutes
            cancelling_pending_jobs = await crud.sync_job.get_stuck_jobs_by_status(
                db=db,
                status=[SyncJobStatus.CANCELLING.value, SyncJobStatus.PENDING.value],
                modified_before=cancelling_pending_cutoff,
            )

            logger.info(
                f"Found {len(cancelling_pending_jobs)} CANCELLING/PENDING jobs "
                f"stuck for > 3 minutes"
            )

            # Query 2: Find RUNNING jobs > 10 minutes old
            running_jobs = await crud.sync_job.get_stuck_jobs_by_status(
                db=db,
                status=[SyncJobStatus.RUNNING.value],
                started_before=running_cutoff,
            )

            logger.info(f"Found {len(running_jobs)} RUNNING jobs that started > 10 minutes ago")

            # Check which RUNNING jobs have no recent entity updates
            stuck_running_jobs = []
            for job in running_jobs:
                # Get the most recent entity created_at for this job using CRUD
                latest_entity_time = await crud.entity.get_latest_entity_time_for_job(
                    db=db,
                    sync_job_id=job.id,
                )

                # Consider stuck if no entities or latest entity is > 10 minutes old
                if latest_entity_time is None or latest_entity_time < running_cutoff:
                    stuck_running_jobs.append(job)
                    logger.info(
                        f"Job {job.id} has no entity updates since "
                        f"{latest_entity_time or 'job start'} - marking as stuck"
                    )

            logger.info(
                f"Found {len(stuck_running_jobs)} RUNNING jobs with no entity "
                f"updates in last 10 minutes"
            )

            # Combine all stuck jobs
            all_stuck_jobs = cancelling_pending_jobs + stuck_running_jobs
            stuck_job_count = len(all_stuck_jobs)

            if stuck_job_count == 0:
                logger.info("No stuck jobs found. Cleanup complete.")
                return

            logger.info(f"Processing {stuck_job_count} stuck sync jobs...")

            # Process each stuck job
            for job in all_stuck_jobs:
                job_id = str(job.id)
                sync_id = str(job.sync_id)
                org_id = str(job.organization_id)

                logger.info(
                    f"Attempting to cancel stuck job {job_id} "
                    f"(status: {job.status}, sync: {sync_id}, org: {org_id})"
                )

                # Create a system-level API context for this organization
                # Fetch the organization using CRUD layer
                try:
                    # Create a temporary context to fetch the organization
                    # (skip_access_validation=True since this is a system operation)
                    organization = await crud.organization.get(
                        db=db,
                        id=job.organization_id,
                        skip_access_validation=True,
                    )
                except Exception as e:
                    logger.error(f"Failed to fetch organization {org_id} for job {job_id}: {e}")
                    failed_count += 1
                    continue

                # Create a system-level context (no user)
                from airweave import schemas

                ctx = ApiContext(
                    request_id=f"cleanup-{job_id}",
                    organization=schemas.Organization.model_validate(organization),
                    user=None,
                    auth_method="system",
                    auth_metadata={"source": "cleanup_activity"},
                    logger=logger,
                )

                try:
                    # Step 1: Try to cancel via Temporal (graceful)
                    cancel_success = await temporal_service.cancel_sync_job_workflow(job_id, ctx)

                    if cancel_success:
                        logger.info(
                            f"Successfully requested Temporal cancellation for job {job_id}"
                        )
                        # Give Temporal a moment to process the cancellation
                        await asyncio.sleep(2)

                    # Step 2: Force update status to CANCELLED in database
                    # (Either the workflow doesn't exist or we're ensuring the state is correct)
                    await sync_job_service.update_status(
                        sync_job_id=UUID(job_id),
                        status=SyncJobStatus.CANCELLED,
                        ctx=ctx,
                        error="Cancelled by cleanup job (stuck in transitional state)",
                        failed_at=now,
                    )

                    logger.info(f"Successfully cancelled stuck job {job_id}")
                    cancelled_count += 1

                except Exception as e:
                    logger.error(f"Failed to cancel stuck job {job_id}: {e}", exc_info=True)
                    failed_count += 1

        # Log summary
        logger.info(
            f"Cleanup complete. Processed {stuck_job_count} stuck jobs: "
            f"{cancelled_count} cancelled, {failed_count} failed"
        )

    except Exception as e:
        logger.error(f"Error during cleanup activity: {e}", exc_info=True)
        raise

"""Outlook Mail source implementation.

Simplified version that retrieves:
  - All mail folders (hierarchical discovery)
  - Messages from all folders
  - Attachments

Follows the same structure as the Gmail connector implementation.
"""

import base64
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from airweave.core.logging import logger
from airweave.platform.decorators import source
from airweave.platform.entities._base import Breadcrumb, ChunkEntity
from airweave.platform.entities.outlook_mail import (
    OutlookAttachmentEntity,
    OutlookMailFolderDeletionEntity,
    OutlookMailFolderEntity,
    OutlookMessageDeletionEntity,
    OutlookMessageEntity,
)
from airweave.platform.sources._base import BaseSource
from airweave.schemas.source_connection import AuthenticationMethod, OAuthType


def _should_retry_outlook_request(exception: Exception) -> bool:
    """Custom retry condition that excludes 404 errors from retrying."""
    if isinstance(exception, httpx.HTTPStatusError):
        # Don't retry 404s - let them pass through to call-site handlers
        if exception.response.status_code == 404:
            return False
        # Retry other HTTP errors
        return True
    # Retry other exceptions (timeouts, etc.)
    return True


@source(
    name="Outlook Mail",
    short_name="outlook_mail",
    auth_methods=[
        AuthenticationMethod.OAUTH_BROWSER,
        AuthenticationMethod.OAUTH_TOKEN,
        AuthenticationMethod.AUTH_PROVIDER,
    ],
    oauth_type=OAuthType.WITH_REFRESH,
    auth_config_class=None,
    config_class="OutlookMailConfig",
    labels=["Communication", "Email"],
    supports_continuous=True,
)
class OutlookMailSource(BaseSource):
    """Outlook Mail source connector integrates with the Microsoft Graph API to extract email data.

    Synchronizes data from Outlook mailboxes.

    It provides comprehensive access to mail folders, messages, and
    attachments with hierarchical folder organization and content processing capabilities.
    """

    GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

    def get_default_cursor_field(self) -> Optional[str]:
        """Get the default cursor field for Outlook Mail source.

        Outlook Mail uses 'deltaToken' to track changes since last sync.

        Returns:
            The default cursor field name
        """
        return "deltaToken"

    def validate_cursor_field(self, cursor_field: str) -> None:
        """Validate if the given cursor field is valid for Outlook Mail.

        Args:
            cursor_field: The cursor field to validate

        Raises:
            ValueError: If the cursor field is invalid
        """
        # Outlook Mail only supports its specific cursor field
        valid_field = self.get_default_cursor_field()

        if cursor_field != valid_field:
            error_msg = (
                f"Invalid cursor field '{cursor_field}' for Outlook Mail source. "
                f"Outlook Mail requires '{valid_field}' as the cursor field. "
                f"Outlook Mail tracks changes using delta tokens, not entity fields. "
                f"Please use the default cursor field or omit it entirely."
            )
            self.logger.error(error_msg)
            raise ValueError(error_msg)

    def _get_cursor_data(self) -> Dict[str, Any]:
        """Get cursor data from cursor.

        Returns:
            Cursor data dictionary, empty dict if no cursor exists
        """
        if hasattr(self, "cursor") and self.cursor:
            return getattr(self.cursor, "cursor_data", {})
        return {}

    def _update_cursor_data(self, delta_token: str, folder_id: str, folder_name: str):
        """Update cursor data with delta token and folder information.

        Args:
            delta_token: Delta token for next sync
            folder_id: Folder ID being synced
            folder_name: Folder name being synced
        """
        # Check if cursor exists before updating
        if not hasattr(self, "cursor") or self.cursor is None:
            self.logger.debug("No cursor available, skipping cursor update")
            return

        # Ensure cursor field is set to our default
        cursor_field = self._ensure_cursor_field_set()

        # Maintain legacy single-token fields for backward compatibility
        self.cursor.cursor_data.update(
            {
                cursor_field: delta_token,
                "folder_id": folder_id,
                "folder_name": folder_name,
                "last_sync": datetime.utcnow().isoformat(),
            }
        )

        # Preferred: store per-folder delta links and names
        folder_links = self.cursor.cursor_data.setdefault("folder_delta_links", {})
        folder_names = self.cursor.cursor_data.setdefault("folder_names", {})
        per_folder_last_sync = self.cursor.cursor_data.setdefault("folder_last_sync", {})

        folder_links[folder_id] = delta_token
        folder_names[folder_id] = folder_name
        per_folder_last_sync[folder_id] = datetime.utcnow().isoformat()
        self.logger.debug(
            f"Updated cursor data with field '{cursor_field}': {self.cursor.cursor_data}"
        )

    def _ensure_cursor_field_set(self) -> str:
        """Ensure the cursor field is set to our default value.

        This method ensures that if we have a cursor but no cursor_field set,
        we set it to our default value.

        Returns:
            The cursor field name to use
        """
        cursor_field = self.get_default_cursor_field()

        # Debug logging to understand cursor state
        if hasattr(self, "cursor") and self.cursor:
            current_cursor_field = getattr(self.cursor, "cursor_field", None)
            self.logger.debug(
                f"Cursor exists: cursor_field={current_cursor_field}, "
                f"default={cursor_field}, cursor_data={getattr(self.cursor, 'cursor_data', {})}"
            )

            # If we have a cursor but no cursor_field set, set it to our default
            if not current_cursor_field:
                self.logger.info(f"Setting cursor field to default: {cursor_field}")
                self.cursor.cursor_field = cursor_field
        else:
            self.logger.debug("No cursor available yet")

        return cursor_field

    def _prepare_sync_context(self) -> tuple[str, Optional[str]]:
        """Prepare sync context and return cursor field and delta token.

        Returns:
            Tuple of (cursor_field, delta_token)
        """
        # Ensure cursor field is set to our default
        cursor_field = self._ensure_cursor_field_set()

        # Get cursor data for incremental sync
        cursor_data = self._get_cursor_data()

        # Validate the cursor field - will raise ValueError if invalid
        if cursor_field != self.get_default_cursor_field():
            self.validate_cursor_field(cursor_field)

        # IMPORTANT: This determines incremental vs full sync
        # - If cursor_data[cursor_field] is None/missing: FULL SYNC (first time)
        # - If cursor_field has a value: INCREMENTAL SYNC (subsequent syncs)
        delta_token = cursor_data.get(cursor_field)

        if delta_token:
            self.logger.info(
                f"Found cursor data for field '{cursor_field}': {delta_token[:100]}... "
                f"Will perform INCREMENTAL sync."
            )
        else:
            self.logger.info(
                f"No cursor data found for field '{cursor_field}'. "
                f"Will perform FULL sync (first sync or cursor reset)."
            )

        return cursor_field, delta_token

    @classmethod
    async def create(
        cls, access_token: str, config: Optional[Dict[str, Any]] = None
    ) -> "OutlookMailSource":
        """Create a new Outlook Mail source instance with the provided OAuth access token."""
        logger.info("Creating new OutlookMailSource instance")
        instance = cls()
        instance.access_token = access_token

        # Filter configuration
        config = config or {}
        instance.after_date = config.get("after_date")
        instance.included_folders = config.get("included_folders", ["inbox", "sentitems"])
        instance.excluded_folders = config.get("excluded_folders", ["junkemail", "deleteditems"])

        logger.info(f"OutlookMailSource instance created with config: {config}")
        return instance

    def _should_process_folder(self, folder_data: Dict[str, Any]) -> bool:
        """Check if folder should be processed based on configured filters."""
        well_known_name = folder_data.get("wellKnownName", "").lower()
        display_name = folder_data.get("displayName", "").lower()

        # If no well-known name, can't filter reliably - include by default
        if not well_known_name:
            return True

        included_folders = getattr(self, "included_folders", [])
        excluded_folders = getattr(self, "excluded_folders", [])

        # Check excluded folders first
        if excluded_folders and well_known_name in [f.lower() for f in excluded_folders]:
            self.logger.debug(f"Skipping folder {display_name} - matches excluded folders")
            return False

        # Check included folders
        if included_folders:
            if well_known_name not in [f.lower() for f in included_folders]:
                self.logger.debug(
                    f"Skipping folder {display_name} - doesn't match included folders"
                )
                return False

        return True

    def _message_matches_date_filter(self, message_data: Dict[str, Any]) -> bool:
        """Check if message matches after_date filter."""
        after_date = getattr(self, "after_date", None)
        if not after_date:
            return True

        received_date_str = message_data.get("receivedDateTime")
        if not received_date_str:
            return True

        try:
            received_date = datetime.fromisoformat(received_date_str.replace("Z", "+00:00"))
            after_dt = datetime.strptime(after_date, "%Y/%m/%d")
            # Make after_dt timezone-aware (UTC)
            from datetime import timezone

            after_dt = after_dt.replace(tzinfo=timezone.utc)

            if received_date < after_dt:
                self.logger.debug(f"Message {message_data.get('id')} skipped: before after_date")
                return False
        except (ValueError, TypeError) as e:
            self.logger.warning(f"Failed to parse date for message {message_data.get('id')}: {e}")

        return True

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
        retry=retry_if_exception(_should_retry_outlook_request),
    )
    async def _get_with_auth(
        self, client: httpx.AsyncClient, url: str, params: Optional[dict] = None
    ) -> dict:
        """Make an authenticated GET request to Microsoft Graph API."""
        self.logger.debug(f"Making authenticated GET request to: {url} with params: {params}")

        # Get fresh token (will refresh if needed)
        access_token = await self.get_access_token()
        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            response = await client.get(url, headers=headers, params=params)

            # Handle 401 errors by refreshing token and retrying
            if response.status_code == 401:
                self.logger.warning(
                    f"Got 401 Unauthorized from Microsoft Graph API at {url}, refreshing token..."
                )
                await self.refresh_on_unauthorized()

                # Get new token and retry
                access_token = await self.get_access_token()
                headers = {"Authorization": f"Bearer {access_token}"}
                response = await client.get(url, headers=headers, params=params)

            response.raise_for_status()
            data = response.json()
            self.logger.debug(f"Received response from {url} - Status: {response.status_code}")
            return data
        except Exception as e:
            self.logger.error(f"Error in API request to {url}: {str(e)}")
            raise

    async def _process_folder_messages(
        self,
        client: httpx.AsyncClient,
        folder_entity: OutlookMailFolderEntity,
        folder_breadcrumb: Breadcrumb,
    ) -> AsyncGenerator[ChunkEntity, None]:
        """Process messages in a folder and handle errors gracefully."""
        self.logger.info(f"Processing messages in folder: {folder_entity.display_name}")
        try:
            async for entity in self._generate_message_entities(
                client, folder_entity, folder_breadcrumb
            ):
                yield entity
        except Exception as e:
            self.logger.error(
                f"Error processing messages in folder {folder_entity.display_name}: {str(e)}"
            )
            # Continue with other folders even if one fails

    async def _process_child_folders(
        self,
        client: httpx.AsyncClient,
        folder_entity: OutlookMailFolderEntity,
        parent_breadcrumbs: List[Breadcrumb],
        folder_breadcrumb: Breadcrumb,
    ) -> AsyncGenerator[OutlookMailFolderEntity, None]:
        """Process child folders recursively and handle errors gracefully."""
        if folder_entity.child_folder_count > 0:
            self.logger.info(
                f"Folder {folder_entity.display_name} has "
                f"{folder_entity.child_folder_count} child folders, recursively processing"
            )
            try:
                async for child_entity in self._generate_folder_entities(
                    client,
                    folder_entity.entity_id,
                    parent_breadcrumbs + [folder_breadcrumb],
                ):
                    yield child_entity
            except Exception as e:
                self.logger.error(
                    f"Error processing child folders of {folder_entity.display_name}: {str(e)}"
                )
                # Continue with other folders even if one fails

    async def _init_and_store_message_delta_for_folder(
        self, client: httpx.AsyncClient, folder_entity: OutlookMailFolderEntity
    ) -> None:
        """Initialize the per-folder message delta link and store it in the cursor."""
        try:
            delta_url = (
                f"{self.GRAPH_BASE_URL}/me/mailFolders/{folder_entity.entity_id}/messages/delta"
            )
            self.logger.debug(f"Calling delta endpoint: {delta_url}")
            delta_data = await self._get_with_auth(client, delta_url)

            attempts = 0
            max_attempts = 1000
            while attempts < max_attempts:
                attempts += 1
                if isinstance(delta_data, dict) and "@odata.deltaLink" in delta_data:
                    delta_link = delta_data["@odata.deltaLink"]
                    self.logger.info(f"Storing delta link for folder: {folder_entity.display_name}")
                    self._update_cursor_data(
                        delta_link, folder_entity.entity_id, folder_entity.display_name
                    )
                    break

                next_link = (
                    delta_data.get("@odata.nextLink") if isinstance(delta_data, dict) else None
                )
                if next_link:
                    self.logger.debug(
                        f"Following delta pagination nextLink for folder "
                        f"{folder_entity.display_name}"
                    )
                    delta_data = await self._get_with_auth(client, next_link)
                else:
                    self.logger.warning(
                        f"No deltaLink or nextLink received for folder "
                        f"{folder_entity.display_name} while initializing delta."
                    )
                    break
        except Exception as e:
            self.logger.warning(
                f"Failed to get delta token for folder {folder_entity.display_name}: {str(e)}"
            )

    async def _process_single_folder_tree(
        self,
        client: httpx.AsyncClient,
        folder: Dict[str, Any],
        parent_breadcrumbs: List[Breadcrumb],
    ) -> AsyncGenerator[ChunkEntity, None]:
        """Yield the folder entity, its messages, initialize delta, then recurse children."""
        # Check if folder should be processed based on filters
        if not self._should_process_folder(folder):
            self.logger.debug(f"Skipping folder {folder.get('displayName')} due to folder filters")
            return

        folder_entity = OutlookMailFolderEntity(
            entity_id=folder["id"],
            breadcrumbs=parent_breadcrumbs,
            display_name=folder["displayName"],
            parent_folder_id=folder.get("parentFolderId"),
            child_folder_count=folder.get("childFolderCount", 0),
            total_item_count=folder.get("totalItemCount", 0),
            unread_item_count=folder.get("unreadItemCount", 0),
            well_known_name=folder.get("wellKnownName"),
        )

        self.logger.info(
            f"Processing folder: {folder_entity.display_name} "
            f"(ID: {folder_entity.entity_id}, Items: {folder_entity.total_item_count})"
        )
        yield folder_entity

        folder_breadcrumb = Breadcrumb(
            entity_id=folder_entity.entity_id,
            name=folder_entity.display_name,
            type="folder",
        )

        # Process messages in this folder
        async for entity in self._process_folder_messages(client, folder_entity, folder_breadcrumb):
            yield entity

        # Initialize message delta link for this folder regardless of item count
        await self._init_and_store_message_delta_for_folder(client, folder_entity)

        # Recurse into child folders
        async for child_entity in self._process_child_folders(
            client, folder_entity, parent_breadcrumbs, folder_breadcrumb
        ):
            yield child_entity

    async def _generate_folder_entities(
        self,
        client: httpx.AsyncClient,
        folder_id: Optional[str] = None,
        parent_breadcrumbs: Optional[List[Breadcrumb]] = None,
    ) -> AsyncGenerator[OutlookMailFolderEntity, None]:
        """Recursively generate OutlookMailFolderEntity objects.

        Traverses the mail folder hierarchy via Microsoft Graph.
        """
        if parent_breadcrumbs is None:
            parent_breadcrumbs = []

        # Decide the endpoint: top-level vs. child folders
        if folder_id:
            url = f"{self.GRAPH_BASE_URL}/me/mailFolders/{folder_id}/childFolders"
            self.logger.info(f"Fetching child folders for folder ID: {folder_id}")
        else:
            # top-level mail folders
            url = f"{self.GRAPH_BASE_URL}/me/mailFolders"
            self.logger.info("Fetching top-level mail folders")

        try:
            while url:
                self.logger.debug(f"Making request to: {url}")
                data = await self._get_with_auth(client, url)
                folders = data.get("value", [])
                self.logger.info(f"Retrieved {len(folders)} folders")

                for folder in folders:
                    async for entity in self._process_single_folder_tree(
                        client, folder, parent_breadcrumbs
                    ):
                        yield entity

                # Handle pagination
                next_link = data.get("@odata.nextLink")
                if next_link:
                    self.logger.debug(f"Following pagination link: {next_link}")
                url = next_link if next_link else None

        except Exception as e:
            self.logger.error(f"Error fetching folders: {str(e)}")
            raise

    async def _generate_message_entities(  # noqa: C901
        self,
        client: httpx.AsyncClient,
        folder_entity: OutlookMailFolderEntity,
        folder_breadcrumb: Breadcrumb,
    ) -> AsyncGenerator[ChunkEntity, None]:
        """Generate OutlookMessageEntity objects and their attachments for a given folder."""
        # Skip folders with no messages
        if folder_entity.total_item_count == 0:
            self.logger.debug(f"Skipping folder {folder_entity.display_name} - no messages")
            return

        self.logger.info(
            f"Starting message generation for folder: {folder_entity.display_name} "
            f"({folder_entity.total_item_count} items)"
        )

        url = f"{self.GRAPH_BASE_URL}/me/mailFolders/{folder_entity.entity_id}/messages"
        params = {"$top": 50}  # Fetch 50 messages at a time

        page_count = 0
        message_count = 0

        try:
            while url:
                page_count += 1
                self.logger.info(
                    f"Fetching message list page #{page_count} for folder "
                    f"{folder_entity.display_name}"
                )
                data = await self._get_with_auth(client, url, params=params)
                messages = data.get("value", [])
                self.logger.info(
                    f"Found {len(messages)} messages on page {page_count} in folder "
                    f"{folder_entity.display_name}"
                )

                for msg_idx, message_data in enumerate(messages):
                    message_count += 1
                    message_id = message_data.get("id", "unknown")
                    self.logger.debug(
                        f"Processing message #{msg_idx + 1}/{len(messages)} (ID: {message_id}) "
                        f"in folder {folder_entity.display_name}"
                    )

                    # Apply date filter
                    if not self._message_matches_date_filter(message_data):
                        self.logger.debug(
                            f"Skipping message {message_id} - doesn't match date filter"
                        )
                        continue

                    # If message doesn't have full data, fetch it
                    if "body" not in message_data:
                        self.logger.debug(f"Fetching full message details for {message_id}")
                        message_url = f"{self.GRAPH_BASE_URL}/me/messages/{message_id}"
                        try:
                            message_data = await self._get_with_auth(client, message_url)
                        except httpx.HTTPStatusError as e:
                            if e.response.status_code == 404:
                                self.logger.warning(
                                    f"Message {message_id} not found (404) - skipping"
                                )
                                continue
                            raise

                    # Process the message
                    try:
                        async for entity in self._process_message(
                            client, message_data, folder_entity.display_name, folder_breadcrumb
                        ):
                            yield entity
                    except Exception as e:
                        self.logger.error(f"Error processing message {message_id}: {str(e)}")
                        # Continue with other messages even if one fails

                # Handle pagination
                url = data.get("@odata.nextLink")
                if url:
                    self.logger.debug("Following pagination to next page")
                    params = None  # params are included in the nextLink
                else:
                    self.logger.info(
                        f"Completed folder {folder_entity.display_name}. "
                        f"Processed {message_count} messages in {page_count} pages."
                    )
                    break

        except Exception as e:
            self.logger.error(
                f"Error processing messages in folder {folder_entity.display_name}: {str(e)}"
            )
            raise

    async def _process_message(
        self,
        client: httpx.AsyncClient,
        message_data: Dict,
        folder_name: str,
        folder_breadcrumb: Breadcrumb,
    ) -> AsyncGenerator[ChunkEntity, None]:
        """Process a message and its attachments."""
        message_id = message_data["id"]
        self.logger.debug(f"Processing message ID: {message_id} in folder: {folder_name}")

        # Extract message fields
        subject = message_data.get("subject")
        sender = (
            message_data.get("from", {}).get("emailAddress", {}).get("address")
            if message_data.get("from")
            else None
        )
        to_recipients = [
            r.get("emailAddress", {}).get("address")
            for r in message_data.get("toRecipients", [])
            if r.get("emailAddress")
        ]
        cc_recipients = [
            r.get("emailAddress", {}).get("address")
            for r in message_data.get("ccRecipients", [])
            if r.get("emailAddress")
        ]

        # Parse dates
        sent_date = None
        received_date = None
        try:
            if message_data.get("sentDateTime"):
                sent_date = datetime.fromisoformat(
                    message_data["sentDateTime"].replace("Z", "+00:00")
                )
            if message_data.get("receivedDateTime"):
                received_date = datetime.fromisoformat(
                    message_data["receivedDateTime"].replace("Z", "+00:00")
                )
        except (ValueError, TypeError) as e:
            self.logger.warning(f"Error parsing dates for message {message_id}: {str(e)}")

        # Extract body content
        body_content = ""
        body_preview = message_data.get("bodyPreview", "")
        if message_data.get("body"):
            body_content = message_data["body"].get("content", "")

        self.logger.debug(f"Creating message entity for message {message_id}")

        # Create message entity
        message_entity = OutlookMessageEntity(
            entity_id=message_id,
            breadcrumbs=[folder_breadcrumb],
            folder_name=folder_name,
            subject=subject,
            sender=sender,
            to_recipients=to_recipients,
            cc_recipients=cc_recipients,
            sent_date=sent_date,
            received_date=received_date,
            body_preview=body_preview,
            body_content=body_content,
            is_read=message_data.get("isRead", False),
            is_draft=message_data.get("isDraft", False),
            importance=message_data.get("importance"),
            has_attachments=message_data.get("hasAttachments", False),
            internet_message_id=message_data.get("internetMessageId"),
        )

        yield message_entity
        self.logger.debug(f"Message entity yielded for {message_id}")

        # Create message breadcrumb for attachments
        message_breadcrumb = Breadcrumb(
            entity_id=message_id,
            name=subject or f"Message {message_id}",
            type="message",
        )

        # Process attachments if the message has any
        if message_entity.has_attachments:
            self.logger.debug(f"Message {message_id} has attachments, processing them")
            attachment_count = 0
            try:
                async for attachment_entity in self._process_attachments(
                    client, message_id, [folder_breadcrumb, message_breadcrumb]
                ):
                    attachment_count += 1
                    self.logger.debug(
                        f"Yielding attachment #{attachment_count} from message {message_id}"
                    )
                    yield attachment_entity
                self.logger.debug(
                    f"Processed {attachment_count} attachments for message {message_id}"
                )
            except Exception as e:
                self.logger.error(
                    f"Error processing attachments for message {message_id}: {str(e)}"
                )
                # Continue with message processing even if attachments fail

    async def _create_content_stream(self, binary_data: bytes):
        """Create an async generator for binary content."""
        yield binary_data

    async def _fetch_attachment_content(
        self, client: httpx.AsyncClient, message_id: str, attachment_id: str
    ) -> Optional[str]:
        """Fetch attachment content from Microsoft Graph API."""
        self.logger.debug(f"Fetching content for attachment {attachment_id}")
        attachment_url = (
            f"{self.GRAPH_BASE_URL}/me/messages/{message_id}/attachments/{attachment_id}"
        )
        attachment_data = await self._get_with_auth(client, attachment_url)
        return attachment_data.get("contentBytes")

    async def _process_single_attachment(
        self,
        client: httpx.AsyncClient,
        attachment: Dict,
        message_id: str,
        breadcrumbs: List[Breadcrumb],
        att_idx: int,
        total_attachments: int,
    ) -> Optional[OutlookAttachmentEntity]:
        """Process a single attachment and return the processed entity."""
        attachment_id = attachment["id"]
        attachment_type = attachment.get("@odata.type", "")
        attachment_name = attachment.get("name", "unknown")

        self.logger.debug(
            f"Processing attachment #{att_idx + 1}/{total_attachments} "
            f"(ID: {attachment_id}, Name: {attachment_name}, Type: {attachment_type})"
        )

        # Only process file attachments
        if "#microsoft.graph.fileAttachment" not in attachment_type:
            self.logger.debug(
                f"Skipping non-file attachment: {attachment_name} (type: {attachment_type})"
            )
            return None

        try:
            # Get attachment content if not already included
            content_bytes = attachment.get("contentBytes")
            if not content_bytes:
                try:
                    content_bytes = await self._fetch_attachment_content(
                        client, message_id, attachment_id
                    )
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 404:
                        self.logger.warning(
                            f"Attachment {attachment_id} not found (404) - skipping"
                        )
                        return None
                    raise

                if not content_bytes:
                    self.logger.warning(f"No content found for attachment {attachment_name}")
                    return None

            # Create file entity
            file_entity = OutlookAttachmentEntity(
                entity_id=f"{message_id}_attachment_{attachment_id}",
                breadcrumbs=breadcrumbs,
                file_id=attachment_id,
                name=attachment_name,
                mime_type=attachment.get("contentType"),
                size=attachment.get("size", 0),
                download_url=f"outlook://attachment/{message_id}/{attachment_id}",
                message_id=message_id,
                attachment_id=attachment_id,
                content_type=attachment.get("contentType"),
                is_inline=attachment.get("isInline", False),
                content_id=attachment.get("contentId"),
                metadata={
                    "source": "outlook_mail",
                    "message_id": message_id,
                    "attachment_id": attachment_id,
                },
            )

            # Decode the base64 data
            try:
                binary_data = base64.b64decode(content_bytes)
            except Exception as e:
                self.logger.error(f"Error decoding attachment content: {str(e)}")
                return None

            # Process using the BaseSource method
            self.logger.debug(
                f"Processing file entity for {attachment_name} with direct content stream"
            )
            processed_entity = await self.process_file_entity_with_content(
                file_entity=file_entity,
                content_stream=self._create_content_stream(binary_data),
                metadata={"source": "outlook_mail", "message_id": message_id},
            )

            if processed_entity:
                self.logger.debug(f"Successfully processed attachment: {attachment_name}")
                return processed_entity
            else:
                self.logger.warning(f"Processing failed for attachment: {attachment_name}")
                return None

        except Exception as e:
            self.logger.error(f"Error processing attachment {attachment_id}: {str(e)}")
            return None

    async def _process_attachments(
        self,
        client: httpx.AsyncClient,
        message_id: str,
        breadcrumbs: List[Breadcrumb],
    ) -> AsyncGenerator[OutlookAttachmentEntity, None]:
        """Process message attachments using the standard file processing pipeline."""
        self.logger.debug(f"Processing attachments for message {message_id}")

        url = f"{self.GRAPH_BASE_URL}/me/messages/{message_id}/attachments"

        try:
            while url:
                self.logger.debug(f"Making request to: {url}")
                data = await self._get_with_auth(client, url)
                attachments = data.get("value", [])
                self.logger.debug(
                    f"Retrieved {len(attachments)} attachments for message {message_id}"
                )

                for att_idx, attachment in enumerate(attachments):
                    processed_entity = await self._process_single_attachment(
                        client, attachment, message_id, breadcrumbs, att_idx, len(attachments)
                    )
                    if processed_entity:
                        yield processed_entity

                # Handle pagination
                url = data.get("@odata.nextLink")
                if url:
                    self.logger.debug("Following pagination link")

        except Exception as e:
            self.logger.error(f"Error processing attachments for message {message_id}: {str(e)}")
            # Don't re-raise - continue with other messages even if attachments fail

    async def _process_delta_changes(
        self,
        client: httpx.AsyncClient,
        delta_token: str,
        folder_id: str,
        folder_name: str,
    ) -> AsyncGenerator[ChunkEntity, None]:
        """Process delta changes for a specific folder using Microsoft Graph delta API.

        Args:
            client: HTTP client for API requests
            delta_token: Delta token for fetching changes
            folder_id: ID of the folder being synced
            folder_name: Name of the folder being synced

        Yields:
            ChunkEntity objects for changed messages and attachments
        """
        self.logger.info(f"Processing delta changes for folder: {folder_name}")

        try:
            # Construct the delta URL using the token (pass via params to ensure proper encoding)
            url = f"{self.GRAPH_BASE_URL}/me/mailFolders/{folder_id}/messages/delta"
            params = {"$deltatoken": delta_token}
            while url:
                self.logger.debug(f"Fetching delta changes from: {url}")
                data = await self._get_with_auth(client, url, params=params)
                # Clear params after the first call; nextLink is a fully-formed URL
                params = None

                # Process changes
                changes = data.get("value", [])
                self.logger.info(f"Found {len(changes)} changes in delta response")

                for change in changes:
                    # Apply date filter to delta changes
                    if not self._message_matches_date_filter(change):
                        self.logger.debug(
                            f"Skipping delta change {change.get('id')} - doesn't match date filter"
                        )
                        continue

                    async for entity in self._yield_message_change_entities(
                        client=client,
                        change=change,
                        folder_id=folder_id,
                        folder_name=folder_name,
                    ):
                        yield entity

                # Update cursor with new delta token for next sync
                new_delta_token = data.get("@odata.deltaLink")
                if new_delta_token:
                    self.logger.debug("Updating cursor with new delta token")
                    self._update_cursor_data(new_delta_token, folder_id, folder_name)
                else:
                    self.logger.warning("No new delta token received - this may indicate an issue")

                # Handle pagination for delta responses
                url = data.get("@odata.nextLink")
                if url:
                    self.logger.debug("Following delta pagination")

        except Exception as e:
            self.logger.error(f"Error processing delta changes for folder {folder_name}: {str(e)}")
            raise

    async def _yield_message_change_entities(
        self,
        client: httpx.AsyncClient,
        change: Dict[str, Any],
        folder_id: str,
        folder_name: str,
    ) -> AsyncGenerator[ChunkEntity, None]:
        """Yield entities for a single message change item from Graph delta."""
        change_type = change.get("@odata.type", "")

        # Deletion indicated via @removed
        if "@removed" in change:
            message_id = change.get("id")
            if message_id:
                deletion_entity = OutlookMessageDeletionEntity(
                    entity_id=message_id,
                    message_id=message_id,
                    deletion_status="removed",
                )
                yield deletion_entity
            return

        if "#microsoft.graph.message" in change_type or change.get("id"):
            folder_breadcrumb = Breadcrumb(
                entity_id=folder_id,
                name=folder_name,
                type="folder",
            )
            async for entity in self._process_message(
                client, change, folder_name, folder_breadcrumb
            ):
                yield entity

    async def _initialize_folders_delta_link(self, client: httpx.AsyncClient) -> None:
        """Initialize and store the delta link for the mailFolders collection."""
        try:
            init_url = f"{self.GRAPH_BASE_URL}/me/mailFolders/delta"
            self.logger.debug(f"Initializing folders delta link via: {init_url}")
            data = await self._get_with_auth(client, init_url)

            safety_counter = 0
            while isinstance(data, dict) and safety_counter < 1000:
                safety_counter += 1
                delta_link = data.get("@odata.deltaLink")
                if delta_link:
                    if hasattr(self, "cursor") and self.cursor:
                        self.cursor.cursor_data["folders_delta_link"] = delta_link
                    self.logger.info("Stored folders_delta_link for future incremental syncs")
                    break

                next_link = data.get("@odata.nextLink")
                if next_link:
                    self.logger.debug("Following folders delta nextLink")
                    data = await self._get_with_auth(client, next_link)
                else:
                    self.logger.warning("No deltaLink or nextLink while initializing folders delta")
                    break
        except Exception as e:
            self.logger.warning(f"Failed to initialize folders delta link: {e}")

    async def _process_folders_delta_changes(
        self, client: httpx.AsyncClient
    ) -> AsyncGenerator[ChunkEntity, None]:
        """Process changes in mail folders using the stored folders_delta_link.

        Yields folder entities for additions/updates and deletion entities for removals.
        Also ensures per-folder message delta links are initialized for new folders
        and removes stored links for deleted folders.
        """
        cursor_data = self._get_cursor_data()
        delta_url = cursor_data.get("folders_delta_link")
        if not delta_url:
            self.logger.debug("No folders_delta_link stored; skipping folders delta processing")
            return

        try:
            async for data in self._iterate_delta_pages(client, delta_url):
                changes = data.get("value", [])
                self.logger.info(f"Found {len(changes)} folder changes in delta response")

                async for entity in self._yield_folder_changes(client, changes):
                    yield entity

                new_delta_link = data.get("@odata.deltaLink")
                if new_delta_link and hasattr(self, "cursor") and self.cursor:
                    self.cursor.cursor_data["folders_delta_link"] = new_delta_link
                    self.logger.debug("Updated folders_delta_link for next incremental run")

        except Exception as e:
            self.logger.error(f"Error processing folders delta changes: {e}")

    async def _iterate_delta_pages(
        self, client: httpx.AsyncClient, start_url: str
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Iterate delta/next pages starting from a delta or nextLink URL."""
        url = start_url
        while url:
            self.logger.debug(f"Fetching folders delta changes from: {url}")
            data = await self._get_with_auth(client, url)
            yield data
            url = data.get("@odata.nextLink")

    async def _yield_folder_changes(
        self, client: httpx.AsyncClient, changes: List[Dict[str, Any]]
    ) -> AsyncGenerator[ChunkEntity, None]:
        """Yield entities for a batch of folder changes from Graph delta."""
        for folder in changes:
            folder_id = folder.get("id")
            if not folder_id:
                continue

            if "@removed" in folder:
                async for e in self._emit_folder_removal(folder_id):
                    yield e
                continue

            async for e in self._emit_folder_add_or_update(client, folder):
                yield e

    async def _emit_folder_removal(self, folder_id: str) -> AsyncGenerator[ChunkEntity, None]:
        """Emit a folder deletion entity and clean up stored links/names."""
        self.logger.info(f"Folder removed: {folder_id}")
        deletion_entity = OutlookMailFolderDeletionEntity(
            entity_id=folder_id, folder_id=folder_id, deletion_status="removed"
        )
        if hasattr(self, "cursor") and self.cursor:
            folder_links = self.cursor.cursor_data.get("folder_delta_links", {})
            folder_names = self.cursor.cursor_data.get("folder_names", {})
            folder_links.pop(folder_id, None)
            folder_names.pop(folder_id, None)
            self.cursor.cursor_data["folder_delta_links"] = folder_links
            self.cursor.cursor_data["folder_names"] = folder_names
        yield deletion_entity

    async def _emit_folder_add_or_update(  # noqa: C901
        self, client: httpx.AsyncClient, folder: Dict[str, Any]
    ) -> AsyncGenerator[ChunkEntity, None]:
        """Emit folder entity and ensure per-folder message delta is initialized."""
        # Check if folder should be processed
        if not self._should_process_folder(folder):
            self.logger.debug(
                f"Skipping folder {folder.get('displayName')} in delta - "
                f"doesn't match folder filters"
            )
            return

        folder_id = folder.get("id")
        display_name = folder.get("displayName", "")
        parent_folder_id = folder.get("parentFolderId")
        child_folder_count = folder.get("childFolderCount", 0)
        total_item_count = folder.get("totalItemCount", 0)
        unread_item_count = folder.get("unreadItemCount", 0)
        well_known_name = folder.get("wellKnownName")

        folder_entity = OutlookMailFolderEntity(
            entity_id=folder_id,
            breadcrumbs=[],
            display_name=display_name,
            parent_folder_id=parent_folder_id,
            child_folder_count=child_folder_count,
            total_item_count=total_item_count,
            unread_item_count=unread_item_count,
            well_known_name=well_known_name,
        )
        yield folder_entity

        # Ensure per-folder message delta link is initialized
        try:
            msg_delta_url = f"{self.GRAPH_BASE_URL}/me/mailFolders/{folder_id}/messages/delta"
            msg_delta_data = await self._get_with_auth(client, msg_delta_url)

            safety_counter = 0
            while isinstance(msg_delta_data, dict) and safety_counter < 1000:
                safety_counter += 1

                messages = msg_delta_data.get("value", [])
                folder_breadcrumb = Breadcrumb(
                    entity_id=folder_id,
                    name=display_name or folder_id,
                    type="folder",
                )
                for change in messages:
                    if "@removed" in change:
                        message_id = change.get("id")
                        if message_id:
                            deletion_entity = OutlookMessageDeletionEntity(
                                entity_id=message_id,
                                message_id=message_id,
                                deletion_status="removed",
                            )
                            yield deletion_entity
                        continue

                    # Apply date filter
                    if not self._message_matches_date_filter(change):
                        self.logger.debug(
                            f"Skipping message {change.get('id')} in folder init - "
                            f"doesn't match date filter"
                        )
                        continue

                    async for entity in self._process_message(
                        client, change, display_name or folder_id, folder_breadcrumb
                    ):
                        yield entity

                delta_link = msg_delta_data.get("@odata.deltaLink")
                if delta_link:
                    if hasattr(self, "cursor") and self.cursor:
                        folder_links = self.cursor.cursor_data.setdefault("folder_delta_links", {})
                        folder_names = self.cursor.cursor_data.setdefault("folder_names", {})
                        folder_links[folder_id] = delta_link
                        folder_names[folder_id] = display_name or folder_id
                    break

                next_link = msg_delta_data.get("@odata.nextLink")
                if next_link:
                    msg_delta_data = await self._get_with_auth(client, next_link)
                else:
                    break
        except Exception as e:
            self.logger.warning(f"Failed to initialize message delta for folder {folder_id}: {e}")

    async def _process_delta_changes_url(  # noqa: C901
        self,
        client: httpx.AsyncClient,
        delta_url: str,
        folder_id: str,
        folder_name: str,
    ) -> AsyncGenerator[ChunkEntity, None]:
        """Process delta changes starting from a delta or nextLink URL (opaque state).

        Reuses the URL returned by Microsoft Graph and follows @odata.nextLink until
        an @odata.deltaLink is returned, which is then stored for the next round.
        """
        self.logger.info(f"Processing delta changes (URL) for folder: {folder_name}")

        try:
            url = delta_url
            while url:
                self.logger.debug(f"Fetching delta changes from: {url}")
                data = await self._get_with_auth(client, url)

                changes = data.get("value", [])
                self.logger.info(f"Found {len(changes)} changes in delta response")

                for change in changes:
                    change_type = change.get("@odata.type", "")

                    # Deletions can be indicated via @removed in Graph delta
                    if "@removed" in change:
                        message_id = change.get("id")
                        if message_id:
                            deletion_entity = OutlookMessageDeletionEntity(
                                entity_id=message_id,
                                message_id=message_id,
                                deletion_status="removed",
                            )
                            yield deletion_entity
                        continue

                    # Apply date filter to delta changes
                    if not self._message_matches_date_filter(change):
                        self.logger.debug(
                            f"Skipping delta change {change.get('id')} - doesn't match date filter"
                        )
                        continue

                    if "#microsoft.graph.message" in change_type or change.get("id"):
                        folder_breadcrumb = Breadcrumb(
                            entity_id=folder_id,
                            name=folder_name,
                            type="folder",
                        )
                        async for entity in self._process_message(
                            client, change, folder_name, folder_breadcrumb
                        ):
                            yield entity

                next_link = data.get("@odata.nextLink")
                if next_link:
                    self.logger.debug("Following delta pagination nextLink")
                    url = next_link
                    continue

                delta_link = data.get("@odata.deltaLink")
                if delta_link:
                    self.logger.debug("Updating cursor with new delta link")
                    self._update_cursor_data(delta_link, folder_id, folder_name)
                else:
                    self.logger.warning(
                        "No nextLink or deltaLink in delta response; ending this delta cycle"
                    )
                break

        except Exception as e:
            self.logger.error(
                f"Error processing delta changes (URL) for folder {folder_name}: {str(e)}"
            )
            raise

    async def _generate_folder_entities_incremental(
        self,
        client: httpx.AsyncClient,
        delta_token: str,
    ) -> AsyncGenerator[ChunkEntity, None]:
        """Generate entities for incremental sync using delta token.

        Args:
            client: HTTP client for API requests
            delta_token: Delta token for fetching changes

        Yields:
            ChunkEntity objects for changed messages and attachments
        """
        self.logger.info("Starting incremental sync")

        # Prefer per-folder delta links (opaque URLs) if available
        cursor_data = self._get_cursor_data()
        folder_links = cursor_data.get("folder_delta_links", {}) or {}
        folder_names = cursor_data.get("folder_names", {}) or {}

        if folder_links:
            for folder_id, delta_link in folder_links.items():
                folder_name = folder_names.get(folder_id, folder_id)
                async for entity in self._process_delta_changes_url(
                    client, delta_link, folder_id, folder_name
                ):
                    yield entity
            return

        # Legacy fallback: use single token + folder_id/name if present
        folder_id = cursor_data.get("folder_id")
        folder_name = cursor_data.get("folder_name", "Unknown Folder")
        if not folder_id:
            self.logger.warning("No folder_id in cursor data for legacy delta token; skipping")
            return
        async for entity in self._process_delta_changes(
            client, delta_token, folder_id, folder_name
        ):
            yield entity

    async def generate_entities(self) -> AsyncGenerator[ChunkEntity, None]:
        """Generate all Outlook mail entities: Folders, Messages and Attachments.

        Supports both full sync (first run) and incremental sync (subsequent runs)
        using Microsoft Graph delta API.
        """
        self.logger.info("===== STARTING OUTLOOK MAIL ENTITY GENERATION =====")
        entity_count = 0

        try:
            # Determine sync type and get delta token if available
            cursor_field, delta_token = self._prepare_sync_context()

            async with self.http_client() as client:
                self.logger.info("HTTP client created, starting entity generation")

                cursor_data = self._get_cursor_data()
                has_folder_links = bool(cursor_data.get("folder_delta_links"))

                if has_folder_links or delta_token:
                    # INCREMENTAL SYNC: Prefer per-folder delta links; fall back to legacy token
                    self.logger.info("Performing INCREMENTAL sync")
                    async for entity in self._generate_folder_entities_incremental(
                        client, delta_token
                    ):
                        entity_count += 1
                        entity_type = type(entity).__name__
                        self.logger.info(
                            (
                                f"Yielding delta entity #{entity_count}: {entity_type} "
                                f"with ID {entity.entity_id}"
                            )
                        )
                        yield entity
                else:
                    # FULL SYNC: Process all folders and messages
                    self.logger.info("Performing FULL sync (first sync or cursor reset)")
                    # Initialize folders delta link up front for next incremental run
                    await self._initialize_folders_delta_link(client)

                    async for entity in self._generate_folder_entities(client):
                        entity_count += 1
                        entity_type = type(entity).__name__
                        self.logger.info(
                            (
                                f"Yielding full sync entity #{entity_count}: {entity_type} "
                                f"with ID {entity.entity_id}"
                            )
                        )
                        yield entity

        except Exception as e:
            self.logger.error(f"Error in entity generation: {str(e)}", exc_info=True)
            raise
        finally:
            self.logger.info(
                f"===== OUTLOOK MAIL ENTITY GENERATION COMPLETE: {entity_count} entities ====="
            )

    async def validate(self) -> bool:
        """Verify Outlook Mail OAuth2 token by pinging the mailFolders endpoint."""
        return await self._validate_oauth2(
            ping_url=f"{self.GRAPH_BASE_URL}/me/mailFolders?$top=1",
            headers={"Accept": "application/json"},
            timeout=10.0,
        )

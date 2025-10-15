"""Configuration classes for platform components."""

from typing import Optional

from pydantic import Field, field_validator, validator

from airweave.platform.configs._base import BaseConfig, RequiredTemplateConfig


class SourceConfig(BaseConfig):
    """Source config schema."""

    pass


class AirtableConfig(SourceConfig):
    """Airtable configuration schema."""

    pass


class AsanaConfig(SourceConfig):
    """Asana configuration schema."""

    pass


class AttioConfig(SourceConfig):
    """Attio configuration schema."""

    pass


class BitbucketConfig(SourceConfig):
    """Bitbucket configuration schema."""

    branch: str = Field(
        default="",
        title="Branch name",
        description=(
            "Specific branch to sync (e.g., 'main', 'develop'). If empty, uses the default branch."
        ),
    )
    file_extensions: list[str] = Field(
        default=[],
        title="File Extensions",
        description=(
            "List of file extensions to include (e.g., '.py', '.js', '.md'). "
            "If empty, includes all text files."
        ),
    )

    @validator("file_extensions", pre=True)
    def parse_file_extensions(cls, value):
        """Convert string input to list if needed."""
        if isinstance(value, str):
            if not value.strip():
                return []
            # Split by commas and strip whitespace
            return [ext.strip() for ext in value.split(",") if ext.strip()]
        return value


class BoxConfig(SourceConfig):
    """Box configuration schema."""

    folder_id: str = Field(
        default="0",
        title="Folder ID",
        description=(
            "Specific Box folder ID to sync. Default is '0' (root folder, syncs all files). "
            "To sync a specific folder, enter its folder ID. "
            "You can find folder IDs in the Box URL when viewing a folder."
        ),
    )


class ClickUpConfig(SourceConfig):
    """ClickUp configuration schema."""

    pass


class ConfluenceConfig(SourceConfig):
    """Confluence configuration schema."""

    pass


class DropboxConfig(SourceConfig):
    """Dropbox configuration schema."""


class ElasticsearchConfig(SourceConfig):
    """Elasticsearch configuration schema."""

    pass


class GitHubConfig(SourceConfig):
    """Github configuration schema."""

    repo_name: str = Field(
        title="Repository Name",
        description="Repository to sync in owner/repo format (e.g., 'airweave-ai/airweave')",
        min_length=3,
        pattern=r"^[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+$",
    )
    branch: str = Field(
        default="",
        title="Branch name",
        description=(
            "Specific branch to sync (e.g., 'main', 'development'). "
            "If empty, uses the default branch."
        ),
    )

    @field_validator("repo_name")
    @classmethod
    def validate_repo_name(cls, v: str) -> str:
        """Validate repository name is in owner/repo format."""
        if not v or not v.strip():
            raise ValueError("Repository name is required")
        v = v.strip()
        if "/" not in v:
            raise ValueError(
                "Repository must be in 'owner/repo' format (e.g., 'airweave-ai/airweave')"
            )
        parts = v.split("/")
        if len(parts) != 2:
            raise ValueError(
                "Repository must be in 'owner/repo' format (e.g., 'airweave-ai/airweave')"
            )
        owner, repo = parts
        if not owner or not repo:
            raise ValueError("Both owner and repository name must be non-empty")
        return v


class GitLabConfig(SourceConfig):
    """GitLab configuration schema."""

    project_id: str = Field(
        default="",
        title="Project ID",
        description=(
            "Specific project ID to sync (e.g., '12345'). If empty, syncs all accessible projects."
        ),
    )
    branch: str = Field(
        default="",
        title="Branch name",
        description=(
            "Specific branch to sync (e.g., 'main', 'master'). If empty, uses the default branch."
        ),
    )


class GmailConfig(SourceConfig):
    """Gmail configuration schema."""

    after_date: Optional[str] = Field(
        None,
        title="After Date",
        description="Sync emails after this date (format: YYYY/MM/DD or YYYY-MM-DD).",
    )

    included_labels: list[str] = Field(
        default=["inbox", "sent"],
        title="Included Labels",
        description=(
            "Labels to include (e.g., 'inbox', 'sent', 'important'). Defaults to inbox and sent."
        ),
    )

    excluded_labels: list[str] = Field(
        default=[
            "spam",
            "trash",
        ],
        title="Excluded Labels",
        description=(
            "Labels to exclude (e.g., 'spam', 'trash', 'promotions', 'social'). "
            "Defaults to spam and trash."
        ),
    )

    excluded_categories: list[str] = Field(
        default=["promotions", "social"],
        title="Excluded Categories",
        description=(
            "Gmail categories to exclude (e.g., 'promotions', 'social', 'updates', 'forums')."
        ),
    )

    gmail_query: Optional[str] = Field(
        None,
        title="Custom Gmail Query",
        description=(
            "Advanced. Custom Gmail query string (overrides all other filters if provided)."
        ),
    )

    @validator("included_labels", "excluded_labels", "excluded_categories", pre=True)
    def parse_list_fields(cls, value):
        """Convert comma-separated string to list if needed."""
        if isinstance(value, str):
            if not value.strip():
                return []
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @validator("after_date")
    def validate_date_format(cls, value):
        """Validate date format and convert to YYYY/MM/DD."""
        if not value:
            return value
        # Accept both YYYY/MM/DD and YYYY-MM-DD formats
        return value.replace("-", "/")


class GoogleCalendarConfig(SourceConfig):
    """Google Calendar configuration schema."""

    pass


class GoogleDriveConfig(SourceConfig):
    """Google Drive configuration schema."""

    include_patterns: list[str] = Field(
        default=[],
        title="Include Patterns",
        description=(
            "List of file/folder paths to include in synchronization. "
            "Examples: 'my_folder/*', 'my_folder/my_file.pdf'. "
            "Separate multiple patterns with commas. If empty, all files are included."
        ),
    )

    @validator("include_patterns", pre=True)
    def _parse_include_patterns(cls, value):
        if isinstance(value, str):
            return [p.strip() for p in value.split(",") if p.strip()]
        return value


class HubspotConfig(SourceConfig):
    """Hubspot configuration schema."""

    pass


class IntercomConfig(SourceConfig):
    """Intercom configuration schema."""

    pass


class JiraConfig(SourceConfig):
    """Jira configuration schema."""

    pass


class LinearConfig(SourceConfig):
    """Linear configuration schema."""

    pass


class MondayConfig(SourceConfig):
    """Monday configuration schema."""

    pass


class MySQLConfig(SourceConfig):
    """MySQL configuration schema."""

    pass


class NotionConfig(SourceConfig):
    """Notion configuration schema."""

    pass


class OneDriveConfig(SourceConfig):
    """OneDrive configuration schema."""

    pass


class OracleConfig(SourceConfig):
    """Oracle configuration schema."""

    pass


class OutlookCalendarConfig(SourceConfig):
    """Outlook Calendar configuration schema."""

    pass


class OutlookMailConfig(SourceConfig):
    """Outlook Mail configuration schema."""

    after_date: Optional[str] = Field(
        None,
        title="After Date",
        description="Sync emails after this date (format: YYYY/MM/DD or YYYY-MM-DD).",
    )

    included_folders: list[str] = Field(
        default=["inbox", "sentitems"],
        title="Included Folders",
        description=(
            "Well-known folder names to include (e.g., 'inbox', 'sentitems', 'drafts'). "
            "Defaults to inbox and sent items."
        ),
    )

    excluded_folders: list[str] = Field(
        default=["junkemail", "deleteditems"],
        title="Excluded Folders",
        description=(
            "Well-known folder names to exclude (e.g., 'junkemail', 'deleteditems'). "
            "Defaults to junk email and deleted items."
        ),
    )

    @validator("included_folders", "excluded_folders", pre=True)
    def parse_list_fields(cls, value):
        """Convert comma-separated string to list if needed."""
        if isinstance(value, str):
            if not value.strip():
                return []
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @validator("after_date")
    def validate_date_format(cls, value):
        """Validate date format and convert to YYYY/MM/DD."""
        if not value:
            return value
        # Accept both YYYY/MM/DD and YYYY-MM-DD formats
        return value.replace("-", "/")


class CTTIConfig(SourceConfig):
    """CTTI AACT configuration schema."""

    limit: int = Field(
        default=10000,
        title="Study Limit",
        description="Maximum number of clinical trial studies to fetch from AACT database",
    )

    skip: int = Field(
        default=0,
        title="Skip Studies",
        description=(
            "Number of clinical trial studies to skip (for pagination). "
            "Use with limit to fetch different batches."
        ),
    )

    @validator("limit", pre=True)
    def parse_limit(cls, value):
        """Convert string input to integer if needed."""
        if isinstance(value, str):
            if not value.strip():
                return 10000
            try:
                return int(value.strip())
            except ValueError as e:
                raise ValueError("Limit must be a valid integer") from e
        return value

    @validator("skip", pre=True)
    def parse_skip(cls, value):
        """Convert string input to integer if needed."""
        if isinstance(value, str):
            if not value.strip():
                return 0
            try:
                skip_val = int(value.strip())
                if skip_val < 0:
                    raise ValueError("Skip must be non-negative")
                return skip_val
            except ValueError as e:
                if "non-negative" in str(e):
                    raise e
                raise ValueError("Skip must be a valid integer") from e
        if isinstance(value, (int, float)):
            if value < 0:
                raise ValueError("Skip must be non-negative")
            return int(value)
        return value


class PostgreSQLConfig(SourceConfig):
    """Postgres configuration schema."""

    pass


class SharePointConfig(SourceConfig):
    """SharePoint configuration schema."""

    pass


class SlackConfig(SourceConfig):
    """Slack configuration schema."""

    pass


class SQLServerConfig(SourceConfig):
    """SQL Server configuration schema."""

    pass


class SQliteConfig(SourceConfig):
    """SQlite configuration schema."""

    pass


class StripeConfig(SourceConfig):
    """Stripe configuration schema."""

    pass


class SalesforceConfig(SourceConfig):
    """Salesforce configuration schema."""

    instance_url: str = RequiredTemplateConfig(
        title="Salesforce Instance URL",
        description="Your Salesforce instance domain only (e.g. 'mycompany.my.salesforce.com')",
        json_schema_extra={"required_for_auth": True},
    )

    @field_validator("instance_url", mode="before")
    @classmethod
    def strip_https_prefix(cls, value):
        """Remove https:// or http:// prefix if present."""
        if isinstance(value, str):
            if value.startswith("https://"):
                return value.replace("https://", "", 1)
            elif value.startswith("http://"):
                return value.replace("http://", "", 1)
        return value


class TodoistConfig(SourceConfig):
    """Todoist configuration schema."""

    pass


class TrelloConfig(SourceConfig):
    """Trello configuration schema."""

    pass


class TeamsConfig(SourceConfig):
    """Microsoft Teams configuration schema."""

    pass


class ZendeskConfig(SourceConfig):
    """Zendesk configuration schema."""

    subdomain: str = RequiredTemplateConfig(
        title="Zendesk Subdomain",
        description="Your Zendesk subdomain only (e.g., 'mycompany' NOT 'mycompany.zendesk.com')",
        json_schema_extra={"required_for_auth": True},
    )
    exclude_closed_tickets: Optional[bool] = Field(
        default=False,
        title="Exclude Closed Tickets",
        description="Skip closed tickets during sync (recommended for faster syncing)",
    )


# AUTH PROVIDER CONFIGURATION CLASSES
# These are for configuring auth provider behavior


class AuthProviderConfig(BaseConfig):
    """Base auth provider configuration schema."""

    pass


class ComposioConfig(AuthProviderConfig):
    """Composio Auth Provider configuration schema."""

    auth_config_id: str = Field(
        title="Auth Config ID",
        description="Auth Config ID for the Composio connection",
    )
    account_id: str = Field(
        title="Account ID",
        description="Account ID for the Composio connection",
    )


class PipedreamConfig(AuthProviderConfig):
    """Pipedream Auth Provider configuration schema."""

    project_id: str = Field(
        title="Project ID",
        description="Pipedream project ID (e.g., proj_JPsD74a)",
    )
    account_id: str = Field(
        title="Account ID",
        description="Pipedream account ID (e.g., apn_gyha5Ky)",
    )
    external_user_id: str = Field(
        title="External User ID",
        description="External user ID associated with the account",
    )
    environment: str = Field(
        default="production",
        title="Environment",
        description="Pipedream environment (production or development)",
    )

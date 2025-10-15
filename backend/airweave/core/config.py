"""Configuration settings for the Airweave backend.

Wraps environment variables and provides defaults.
"""

from typing import Optional

from pydantic import PostgresDsn, ValidationInfo, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Pydantic settings class.

    Attributes:
    ----------
        PROJECT_NAME (str): The name of the project.
        LOCAL_DEVELOPMENT (bool): Whether the application is running locally.
        LOCAL_CURSOR_DEVELOPMENT (bool): Whether cursor development features are enabled.
        ENVIRONMENT (str): The deployment environment (local, dev, test, prod).
        FRONTEND_LOCAL_DEVELOPMENT_PORT (int): Port for local frontend development.
        FIRST_SUPERUSER (str): The email address of the first superuser.
        FIRST_SUPERUSER_PASSWORD (str): The password of the first superuser.
        ENCRYPTION_KEY (str): The encryption key.
        STATE_SECRET (str): The HMAC secret for OAuth state token signing.
        CODE_SUMMARIZER_ENABLED (bool): Whether the code summarizer is enabled.
        DEBUG (bool): Whether debug mode is enabled.
        LOG_LEVEL (str): The logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        POSTGRES_HOST (str): The PostgreSQL server hostname.
        POSTGRES_DB (str): The PostgreSQL database name.
        POSTGRES_USER (str): The PostgreSQL username.
        POSTGRES_PASSWORD (str): The PostgreSQL password.
        SQLALCHEMY_ASYNC_DATABASE_URI (Optional[PostgresDsn]): The SQLAlchemy async database URI.
        LOCAL_NGROK_SERVER (Optional[str]): The local ngrok server URL.
        RUN_ALEMBIC_MIGRATIONS (bool): Whether to run the alembic migrations.
        RUN_DB_SYNC (bool): Whether to run the system sync to process sources,
            destinations, and entity types.
        REDIS_HOST (str): The Redis server hostname.
        REDIS_PORT (int): The Redis server port.
        REDIS_PASSWORD (Optional[str]): The Redis password (if authentication is enabled).
        REDIS_DB (int): The Redis database number.
        QDRANT_HOST (str): The Qdrant host.
        QDRANT_PORT (int): The Qdrant port.
        TEXT2VEC_INFERENCE_URL (str): The URL for text2vec-transformers inference service.
        OPENAI_API_KEY (Optional[str]): The OpenAI API key.
        MISTRAL_API_KEY (Optional[str]): The Mistral AI API key.
        FIRECRAWL_API_KEY (Optional[str]): The FireCrawl API key.
        TEMPORAL_HOST (str): The host of the Temporal server.
        TEMPORAL_PORT (int): The Temporal server port.
        TEMPORAL_NAMESPACE (str): The namespace of the Temporal server.
        TEMPORAL_TASK_QUEUE (str): The task queue for the Temporal server.
        TEMPORAL_ENABLED (bool): Whether Temporal is enabled.
        SYNC_MAX_WORKERS (int): The maximum number of workers for sync tasks.
        SYNC_THREAD_POOL_SIZE (int): The size of the thread pool for sync tasks.
        WEB_FETCHER_MAX_CONCURRENT (int): Max concurrent web scraping requests
        OPENAI_MAX_CONCURRENT (int): Max concurrent OpenAI API requests
        CTTI_MAX_CONCURRENT (int): Max concurrent CTTI (ClinicalTrials.gov) requests
        STRIPE_DEVELOPER_MONTHLY: str = ""
        STRIPE_PRO_MONTHLY: str = ""
        STRIPE_TEAM_MONTHLY: str = ""
        STRIPE_ENTERPRISE_MONTHLY: str = ""

        # Custom deployment URLs
        API_FULL_URL (Optional[str]): The full URL for the API.
        QDRANT_FULL_URL (Optional[str]): The full URL for the Qdrant.
        ADDITIONAL_CORS_ORIGINS (Optional[list[str]]): Additional CORS origins separated by commas.
    """

    PROJECT_NAME: str = "Airweave"
    LOCAL_DEVELOPMENT: bool = False
    LOCAL_CURSOR_DEVELOPMENT: bool = False
    ENVIRONMENT: str = "local"
    FRONTEND_LOCAL_DEVELOPMENT_PORT: int = 8080

    FIRST_SUPERUSER: str
    FIRST_SUPERUSER_PASSWORD: str

    AUTH_ENABLED: Optional[bool] = False
    AUTH0_DOMAIN: Optional[str] = None
    AUTH0_AUDIENCE: Optional[str] = None
    AUTH0_RULE_NAMESPACE: Optional[str] = None
    AUTH0_CLIENT_ID: Optional[str] = None  # SPA Client ID
    AUTH0_M2M_CLIENT_ID: Optional[str] = None  # Machine-to-Machine Client ID for Management API
    AUTH0_M2M_CLIENT_SECRET: Optional[str] = None  # Machine-to-Machine Client Secret

    ENCRYPTION_KEY: str

    # OAuth state HMAC secret for CSRF protection
    # Must be a strong, random secret in production
    STATE_SECRET: str

    CODE_SUMMARIZER_ENABLED: bool = False

    # Debug configuration
    DEBUG: bool = False

    # Logging configuration
    LOG_LEVEL: str = "INFO"

    POSTGRES_HOST: str
    POSTGRES_DB: str = "airweave"
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    SQLALCHEMY_ASYNC_DATABASE_URI: Optional[PostgresDsn] = None

    LOCAL_NGROK_SERVER: Optional[str] = None

    RUN_ALEMBIC_MIGRATIONS: bool = True
    RUN_DB_SYNC: bool = True

    # Redis configuration
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: Optional[str] = None
    REDIS_DB: int = 0

    QDRANT_HOST: Optional[str] = None
    QDRANT_PORT: Optional[int] = None
    TEXT2VEC_INFERENCE_URL: str = "http://localhost:9878"

    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    MISTRAL_API_KEY: Optional[str] = None
    FIRECRAWL_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    COHERE_API_KEY: Optional[str] = None
    CEREBRAS_API_KEY: Optional[str] = None
    AZURE_KEYVAULT_NAME: Optional[str] = None

    # Temporal configuration
    TEMPORAL_HOST: str = "localhost"
    TEMPORAL_PORT: int = 7233
    TEMPORAL_NAMESPACE: str = "default"
    TEMPORAL_TASK_QUEUE: str = "airweave-sync-queue"
    TEMPORAL_ENABLED: bool = False
    TEMPORAL_DISABLE_SANDBOX: bool = False

    # Stripe billing settings
    STRIPE_ENABLED: bool = False
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    STRIPE_DEVELOPER_MONTHLY: str = ""
    STRIPE_PRO_MONTHLY: str = ""
    STRIPE_PRO_YEARLY: str = ""
    STRIPE_TEAM_MONTHLY: str = ""
    STRIPE_TEAM_YEARLY: str = ""
    STRIPE_ENTERPRISE_MONTHLY: str = ""
    STRIPE_YEARLY_DISCOUNT_COUPON_ID: str = ""

    # Email settings - only for production Airweave instance
    RESEND_API_KEY: Optional[str] = None
    RESEND_FROM_EMAIL: Optional[str] = None

    # Donke integration (internal automation service)
    DONKE_URL: Optional[str] = None
    DONKE_API_KEY: Optional[str] = None

    # PostHog Analytics Configuration
    # Public API key for open source and hosted platform
    POSTHOG_API_KEY: str = "phc_Ytp26UB3WwGCdjHTpDBI9HQg2ZA38ITMDKI6fE6EPGS"
    POSTHOG_HOST: str = "https://eu.i.posthog.com"
    # Analytics enabled by default unless in local environment
    ANALYTICS_ENABLED: bool = True

    # Sync configuration
    SYNC_MAX_WORKERS: int = 100
    SYNC_THREAD_POOL_SIZE: int = 100
    WEB_FETCHER_MAX_CONCURRENT: int = 10  # Max concurrent web scraping requests
    OPENAI_MAX_CONCURRENT: int = 20  # Max concurrent OpenAI API requests
    CTTI_MAX_CONCURRENT: int = 3  # Max concurrent CTTI (ClinicalTrials.gov) requests

    # Custom deployment URLs - these are used to override the default URLs to allow
    # for custom domains in custom deployments
    API_FULL_URL: Optional[str] = None
    APP_FULL_URL: Optional[str] = None
    QDRANT_FULL_URL: Optional[str] = None
    ADDITIONAL_CORS_ORIGINS: Optional[str] = None  # Separated by commas or semicolons

    @field_validator("AZURE_KEYVAULT_NAME", mode="before")
    def validate_azure_keyvault_name(cls, v: Optional[str], info: ValidationInfo) -> Optional[str]:
        """Create a keyvault name based on the environment.

        Like: "airweave-core-dev-kv" or "airweave-core-prd-kv"

        Args:
            v: The Azure KeyVault name.
            info: Validation context containing all field values.
        """
        environment = info.data.get("ENVIRONMENT", "local")
        if environment in ["dev", "prd"] and not v:
            return f"airweave-core-{environment}-kv"
        return v

    @field_validator("ADDITIONAL_CORS_ORIGINS", mode="before")
    def parse_cors_origins(cls, v: Optional[str]) -> Optional[list[str]]:
        """Parse CORS origins from string to list, supporting both comma and semicolon separators.

        Args:
            v: The CORS origins string or list.

        Returns:
            Optional[list[str]]: The parsed list of CORS origins or None.
        """
        if isinstance(v, list) or v is None:
            return v

        if ";" in v:
            return [origin.strip() for origin in v.split(";") if origin.strip()]

        # Default Pydantic behavior will handle comma separation
        return v

    @field_validator(
        "AUTH0_DOMAIN",
        "AUTH0_AUDIENCE",
        "AUTH0_RULE_NAMESPACE",
        "AUTH0_CLIENT_ID",
        "AUTH0_M2M_CLIENT_ID",
        "AUTH0_M2M_CLIENT_SECRET",
        mode="before",
    )
    def validate_auth0_settings(cls, v: str, info: ValidationInfo) -> str:
        """Validate Auth0 settings when AUTH_ENABLED is True.

        Args:

        ----
            v (str): The value of the Auth0 setting.
            info (ValidationInfo): The validation context containing all field values.

        Returns:
        -------
            str: The validated Auth0 setting.

        Raises:
        ------
            ValueError: If AUTH_ENABLED is True and the Auth0 setting is empty.
        """
        auth_enabled = info.data.get("AUTH_ENABLED", False)
        if auth_enabled and not v:
            field_name = info.field_name
            raise ValueError(f"{field_name} must be set when AUTH_ENABLED is True")
        return v

    @field_validator(
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "STRIPE_DEVELOPER_MONTHLY",
        "STRIPE_PRO_MONTHLY",
        "STRIPE_TEAM_MONTHLY",
        mode="before",
    )
    def validate_stripe_settings(cls, v: str, info: ValidationInfo) -> str:
        """Validate Stripe settings when STRIPE_ENABLED is True.

        Raises a ValueError if any required Stripe setting is missing while
        billing is enabled, to ensure misconfigurations fail fast at startup.
        """
        stripe_enabled = info.data.get("STRIPE_ENABLED", False)
        if stripe_enabled and not v:
            field_name = info.field_name
            raise ValueError(f"{field_name} must be set when STRIPE_ENABLED is True")
        return v

    @field_validator("RESEND_FROM_EMAIL", mode="before")
    def validate_resend_email_settings(
        cls, v: Optional[str], info: ValidationInfo
    ) -> Optional[str]:
        """Validate Resend email settings when RESEND_API_KEY is configured.

        Ensures that RESEND_FROM_EMAIL is set when email functionality is enabled,
        preventing accidental use of default values in production.
        """
        resend_api_key = info.data.get("RESEND_API_KEY")
        if resend_api_key and not v:
            raise ValueError("RESEND_FROM_EMAIL must be set when RESEND_API_KEY is configured")
        return v

    @field_validator("STATE_SECRET", mode="before")
    def validate_state_secret(cls, v: str, info: ValidationInfo) -> str:
        """Validate the STATE_SECRET has minimum required length.

        Args:
            v: The STATE_SECRET value.
            info: Validation context containing all field values.

        Returns:
            str: The validated STATE_SECRET.

        Raises:
            ValueError: If STATE_SECRET is not set or too short.
        """
        if not v or len(v) < 32:
            raise ValueError(
                "STATE_SECRET must be at least 32 characters long. "
                "Generate a strong secret using: "
                "python -c 'import secrets; print(secrets.token_urlsafe(32))'"
            )
        return v

    @field_validator("SQLALCHEMY_ASYNC_DATABASE_URI", mode="before")
    def assemble_db_connection(cls, v: Optional[str], info: ValidationInfo) -> PostgresDsn:
        """Build the SQLAlchemy database URI.

        Args:
        ----
            v (Optional[str]): The value of the SQLALCHEMY_DATABASE_URI setting.
            info (ValidationInfo): The validation context containing all field values.

        Returns:
        -------
            PostgresDsn: The assembled SQLAlchemy async database URI.

        """
        if isinstance(v, str):
            return v

        # Connect to local PostgreSQL server during local development
        # This allows developers to debug without Docker
        host = info.data.get("POSTGRES_HOST", "localhost")

        return PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=info.data.get("POSTGRES_USER"),
            password=info.data.get("POSTGRES_PASSWORD"),
            host=host,
            path=f"{info.data.get('POSTGRES_DB') or ''}",
        )

    @property
    def qdrant_url(self) -> str:
        """The Qdrant URL.

        Returns:
            str: The Qdrant URL.
        """
        if self.QDRANT_FULL_URL:
            return self.QDRANT_FULL_URL

        if not self.QDRANT_HOST or not self.QDRANT_PORT:
            raise ValueError("QDRANT_HOST with QDRANT_PORT or QDRANT_FULL_URL must be set")

        return f"http://{self.QDRANT_HOST}:{self.QDRANT_PORT}"

    @property
    def api_url(self) -> str:
        """The server URL.

        Returns:
            str: The server URL.
        """
        if self.API_FULL_URL:
            return self.API_FULL_URL

        if self.ENVIRONMENT == "local":
            return self.LOCAL_NGROK_SERVER or "http://localhost:8001"
        if self.ENVIRONMENT == "prd":
            return "https://api.airweave.ai"
        return f"https://api.{self.ENVIRONMENT}-airweave.com"

    @property
    def app_url(self) -> str:
        """The app URL.

        Returns:
            str: The app URL.
        """
        if self.APP_FULL_URL:
            return self.APP_FULL_URL

        if self.ENVIRONMENT == "local":
            return f"http://localhost:{self.FRONTEND_LOCAL_DEVELOPMENT_PORT}"
        if self.ENVIRONMENT == "prd":
            return "https://app.airweave.ai"
        return f"https://app.{self.ENVIRONMENT}-airweave.com"

    @property
    def docs_url(self) -> str:
        """The docs URL.

        Returns:
            str: The docs URL.
        """
        if self.ENVIRONMENT == "local":
            return f"http://localhost:{self.FRONTEND_LOCAL_DEVELOPMENT_PORT}"
        if self.ENVIRONMENT == "prd":
            return "https://docs.airweave.ai"
        return f"https://docs.{self.ENVIRONMENT}-airweave.com"

    @property
    def temporal_address(self) -> str:
        """The Temporal server address.

        Returns:
            str: The Temporal server address in host:port format.
        """
        return f"{self.TEMPORAL_HOST}:{self.TEMPORAL_PORT}"


settings = Settings()

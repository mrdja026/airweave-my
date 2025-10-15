"""Service initialization for test execution."""

import os

from monke.core.config import TestConfig
from monke.core.context import TestContext
from monke.utils.logging import get_logger

logger = get_logger("services")


async def initialize_services(config: TestConfig, context: TestContext) -> None:
    """Initialize all required services for test execution.

    Args:
        config: Test configuration
        context: Test context to populate with services
    """
    # Initialize Airweave client
    context.airweave_client = _create_airweave_client()
    logger.info("✅ Initialized Airweave client")

    # Initialize Bongo
    context.bongo = await _create_bongo(config)
    logger.info(f"✅ Initialized {config.connector.type} bongo")


def _create_airweave_client():
    """Create a simple HTTP client configuration for Airweave API.

    Returns:
        Dictionary with API configuration
    """
    return {
        "base_url": os.getenv("AIRWEAVE_API_URL", "http://localhost:8001"),
        "api_key": os.getenv("AIRWEAVE_API_KEY"),
    }


async def _create_bongo(config: TestConfig):
    """Create a bongo instance for the connector.

    Args:
        config: Test configuration with connector details

    Returns:
        Initialized bongo instance
    """
    from monke.bongos.registry import BongoRegistry
    from monke.auth.broker import ComposioBroker
    from monke.auth.credentials_resolver import resolve_credentials

    # Resolve credentials based on auth mode
    if config.connector.auth_mode == "composio":
        broker = ComposioBroker(
            account_id=config.connector.composio_config.account_id,
            auth_config_id=config.connector.composio_config.auth_config_id,
        )
        resolved_creds = await broker.get_credentials(config.connector.type)
        
        # Pass Composio config to bongo for token refresh
        composio_config = {
            "account_id": config.connector.composio_config.account_id,
            "auth_config_id": config.connector.composio_config.auth_config_id,
        }
    else:
        # Direct auth mode
        if config.connector.auth_fields:
            resolved_creds = config.connector.resolve_auth_fields()
        else:
            # Let resolve_credentials handle it
            resolved_creds = await resolve_credentials(config.connector.type, None)
        composio_config = None

    # Create bongo with resolved credentials and Composio config
    return BongoRegistry.create(
        config.connector.type,
        resolved_creds,
        entity_count=config.entity_count,
        composio_config=composio_config,
        **config.connector.config_fields,
    )

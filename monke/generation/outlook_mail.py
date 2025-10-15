"""Outlook Mail-specific generation adapter: email generator."""

from typing import Tuple

from monke.client.llm import LLMClient
from monke.generation.schemas.outlook_mail import OutlookMessage


async def generate_outlook_message(
    model: str, token: str, is_update: bool = False
) -> Tuple[str, str]:
    """
    Returns (subject, body). The literal token must appear in the body.
    Uses structured generation with JSON mode under the hood.
    """
    llm = LLMClient(model_override=model)

    if is_update:
        instruction = (
            "Create a concise follow-up email about a (synthetic) tech product update. "
            f"Include the EXACT literal token '{token}' somewhere in the body text. "
            "Return JSON with fields: subject (string), body (string)."
        )
    else:
        instruction = (
            "Create a concise (synthetic) email announcing a new tech product. "
            f"Include the EXACT literal token '{token}' somewhere in the body text. "
            "Return JSON with fields: subject (string), body (string)."
        )

    message = await llm.generate_structured(OutlookMessage, instruction)

    # Ensure token is in body
    body = message.body
    if token not in body:
        body += f"\n\nReference: {token}"

    return message.subject, body

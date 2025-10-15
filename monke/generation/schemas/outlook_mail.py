"""Outlook Mail-specific generation schema."""

from pydantic import BaseModel, Field


class OutlookMessage(BaseModel):
    """Schema for Outlook email generation."""

    subject: str = Field(description="Email subject line")
    body: str = Field(description="Email body content")

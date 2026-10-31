import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class FollowUpRead(BaseModel):
    id: uuid.UUID
    sent_at: datetime
    status: str
    recipient: str | None = None
    subject: str
    content: str
    error: str | None
    decided_at: datetime | None = None

    model_config = {"from_attributes": True}


class FollowUpResolve(BaseModel):
    """Whether an interrupted send actually reached the recipient (checked in Sent mail)."""
    sent: bool


class FollowUpApprove(BaseModel):
    """Optional edits the user makes to the draft before sending it."""
    subject: str | None = Field(None, min_length=1, max_length=300)
    content: str | None = Field(None, min_length=1, max_length=5000)

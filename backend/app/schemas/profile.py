from pydantic import BaseModel, Field
from app.schemas.discovery import Preferences


class ProfileRead(BaseModel):
    preferences: Preferences = Preferences()
    portfolio_data: dict = {}
    country: str | None
    city: str | None
    search_keywords: str | None
    crawl_enabled: bool
    followup_enabled: bool
    followup_first_days: int
    followup_interval_days: int
    followup_max_count: int

    model_config = {"from_attributes": True}


class ProfileUpdate(BaseModel):
    preferences: Preferences | None = None
    country: str | None = None
    city: str | None = None
    search_keywords: str | None = None
    crawl_enabled: bool | None = None
    followup_enabled: bool | None = None
    followup_first_days: int | None = Field(None, ge=2, le=60)
    followup_interval_days: int | None = Field(None, ge=3, le=60)
    followup_max_count: int | None = Field(None, ge=0, le=3)

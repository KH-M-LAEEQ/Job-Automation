import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class EmailAccountCreate(BaseModel):
    smtp_host: str = Field(min_length=1, max_length=255)
    smtp_port: int = 587
    smtp_username: str = Field(min_length=1, max_length=255)
    smtp_password: str = Field(min_length=1, max_length=1024)
    from_name: str | None = Field(None, max_length=255)
    from_email: EmailStr
    use_tls: bool = True


class EmailAccountRead(BaseModel):
    id: uuid.UUID
    smtp_host: str
    smtp_port: int
    smtp_username: str
    from_name: str | None
    from_email: str
    use_tls: bool
    last_tested_at: datetime | None
    last_test_ok: bool | None

    model_config = {"from_attributes": True}


class EmailTestResult(BaseModel):
    ok: bool
    error: str | None = None

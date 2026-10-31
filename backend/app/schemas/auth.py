import uuid

from pydantic import BaseModel, EmailStr, Field, field_validator


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(None, max_length=255)

    @field_validator("password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 bytes")
        if value.isdigit() or value.isalpha() or len(set(value)) < 4:
            raise ValueError("Use a mix of letters and numbers or symbols")
        return value


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class AccountDelete(BaseModel):
    password: str = Field(max_length=128)


class UserRead(BaseModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str | None

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

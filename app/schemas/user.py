from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.schemas.common import UtcDatetime


class SignupRequest(BaseModel):
    email: EmailStr
    # bcrypt only considers the first 72 bytes of a password.
    password: str = Field(min_length=8, max_length=72, examples=["Str0ngPass!23"])
    full_name: str = Field(min_length=1, max_length=120, examples=["Riya Sharma"])

    @field_validator("full_name")
    @classmethod
    def not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("full_name must not be blank")
        return stripped


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    role: str
    created_at: UtcDatetime

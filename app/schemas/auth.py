from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    """JSON login body. The endpoint also accepts the OAuth2 form format
    (``username``/``password`` urlencoded) so Swagger UI's Authorize button
    works out of the box."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int

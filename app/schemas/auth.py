# Field names are camelCase on purpose: they are the wire contract, hand-mirrored
# by the frontend zod schemas (the same convention the Prisma schema uses).
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str | None = Field(default=None, max_length=120)


class LoginRequest(BaseModel):
    # Deliberately plain str (not EmailStr): a malformed email at login must
    # produce the same generic invalid_credentials as a wrong one, never a
    # validation hint.
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class UserOut(BaseModel):
    id: str
    email: str
    name: str | None
    createdAt: datetime


class AuthResponse(BaseModel):
    accessToken: str
    user: UserOut


class TokenResponse(BaseModel):
    accessToken: str

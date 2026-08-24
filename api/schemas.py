from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    display_name: str = Field(min_length=1, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    display_name: str
    gemini_configured: bool = False


class SessionView(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserView


class GeminiKeyRequest(BaseModel):
    api_key: str = Field(min_length=20, max_length=500)
    verify_key: bool = Field(default=True, alias="validate")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    client_kind: Literal["web", "ios"] = "web"


class PhoneActionView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    kind: str
    label: str
    message: str
    url: str | None = None
    recipient: str | None = None
    contact: str | None = None
    message_copy: str | None = Field(default=None, alias="copy")


class ChatMessageView(BaseModel):
    id: str
    role: str
    content: str
    created_at: str


class ChatResponse(BaseModel):
    response: str
    handoff: PhoneActionView | None = None

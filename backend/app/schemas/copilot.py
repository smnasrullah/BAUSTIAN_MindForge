from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.params import DbId
from app.llm.copilot.intents import Route
from app.llm.copilot.tools import ToolCall
from app.models.enums import Lang
from app.schemas.llm import LlmText


class CopilotChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)  # sanitized and cut to 500 chars
    lang: Lang | None = None  # default: user's language
    # Agents: own account (omit, or their own id). Distributors / admins: required.
    agent_id: DbId | None = None
    # Own conversation to continue; omitted -> a new conversation is started.
    conversation_id: DbId | None = None


class CopilotConversationIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class CopilotConversationOut(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime


class CopilotMessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class CopilotMessageOut(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class CopilotSuggestions(BaseModel):
    """Suggested questions; the only ones with recorded replay wording (exact-text match)."""

    lang: Lang
    items: list[str]


class CopilotSource(BaseModel):
    """Liquidity Playbook passage the answer is grounded in (cited by title)."""

    slug: str
    title: str
    score: float


class CopilotMeta(BaseModel):
    agent_id: int
    route: Route
    tool: ToolCall | None  # allow-listed read-only tool the backend ran
    sources: list[CopilotSource]


class CopilotReply(CopilotMeta):
    """SSE `done` event. `answer.text` is verified against the evidence pack."""

    answer: LlmText
    conversation_id: int | None = None  # where this turn was saved


class CopilotDraft(BaseModel):
    """SSE `template` / `delta` event."""

    text: str


class CopilotError(BaseModel):
    """SSE `error` event."""

    detail: str

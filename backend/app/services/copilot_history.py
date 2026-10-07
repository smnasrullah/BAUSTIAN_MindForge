"""Persistent copilot conversations, scoped to their owner. Text is redacted before saving."""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.copilot.support import redact
from app.models import CopilotConversation, CopilotConvMessage

LLM_HISTORY = 10  # messages sent to the LLM as context
TITLE_CHARS = 60


def list_for(session: Session, user_id: uuid.UUID, limit: int = 50) -> list[CopilotConversation]:
    stmt = (select(CopilotConversation).where(CopilotConversation.user_id == user_id)
            .order_by(CopilotConversation.updated_at.desc(), CopilotConversation.id.desc())
            .limit(limit))
    return list(session.scalars(stmt))


def create(session: Session, user_id: uuid.UUID, title: str | None = None
           ) -> CopilotConversation:
    conv = CopilotConversation(user_id=user_id, title=redact(title or "")[:TITLE_CHARS],
                               state_json={})
    session.add(conv)
    session.flush()
    return conv


def get_owned(session: Session, user_id: uuid.UUID, conversation_id: int
              ) -> CopilotConversation:
    """404 (not 403) for someone else's conversation: no existence leak."""
    conv = session.get(CopilotConversation, conversation_id)
    if conv is None or conv.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="conversation_not_found")
    return conv


def messages(session: Session, conv: CopilotConversation, limit: int | None = None
             ) -> list[CopilotConvMessage]:
    """Oldest first; with `limit`, only the most recent `limit` messages."""
    stmt = (select(CopilotConvMessage).where(CopilotConvMessage.conversation_id == conv.id)
            .order_by(CopilotConvMessage.id.desc()))
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(reversed(list(session.scalars(stmt))))


def append(session: Session, conv: CopilotConversation, role: str, content: str
           ) -> CopilotConvMessage:
    clean = redact(content)
    msg = CopilotConvMessage(conversation_id=conv.id, role=role, content=clean)
    if not conv.title and role == "user":
        conv.title = clean[:TITLE_CHARS]
    conv.updated_at = datetime.now(UTC)
    session.add(msg)
    session.flush()
    return msg


def set_state(conv: CopilotConversation, state: dict[str, Any]) -> None:
    conv.state_json = dict(state)  # new object so the JSON column is marked dirty


def llm_history(session: Session, conv: CopilotConversation) -> str | None:
    """Last LLM_HISTORY messages as plain lines (already redacted), or None when empty."""
    rows = messages(session, conv, LLM_HISTORY)
    return "\n".join(f"{m.role}: {m.content}" for m in rows) or None

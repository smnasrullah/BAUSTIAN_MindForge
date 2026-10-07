"""LLM layer persistence: call log, response cache, copilot chat, RAG knowledge docs."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BigIntPK, JsonDoc, TsTz, created_at_col, db_enum
from app.models.enums import ChatRole, GeneratedBy, GuardResult, Lang, LlmIntent


class LlmCallLog(Base):
    __tablename__ = "llm_call_log"
    __table_args__ = (
        Index("ix_llm_call_log_created_at", "created_at"),
        Index("ix_llm_call_log_intent_generated_by", "intent", "generated_by"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    intent: Mapped[LlmIntent] = mapped_column(db_enum(LlmIntent))
    provider: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    lang: Mapped[Lang] = mapped_column(db_enum(Lang))
    evidence_hash: Mapped[str] = mapped_column(Text)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    generated_by: Mapped[GeneratedBy] = mapped_column(db_enum(GeneratedBy))
    guard_result: Mapped[GuardResult] = mapped_column(db_enum(GuardResult))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()


class LlmCache(Base):
    __tablename__ = "llm_cache"
    __table_args__ = (Index("ix_llm_cache_expires_at", "expires_at"),)

    # sha256(evidence pack + intent + lang)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    intent: Mapped[LlmIntent] = mapped_column(db_enum(LlmIntent))
    response: Mapped[dict[str, Any]] = mapped_column(JsonDoc)
    provider: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
    expires_at: Mapped[datetime | None] = mapped_column(TsTz)


class CopilotMessage(Base):
    __tablename__ = "copilot_messages"
    __table_args__ = (Index("ix_copilot_messages_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    role: Mapped[ChatRole] = mapped_column(db_enum(ChatRole))
    text: Mapped[str] = mapped_column(Text)
    lang: Mapped[Lang] = mapped_column(db_enum(Lang))
    generated_by: Mapped[GeneratedBy | None] = mapped_column(db_enum(GeneratedBy))
    llm_call_id: Mapped[int | None] = mapped_column(ForeignKey("llm_call_log.id"))
    created_at: Mapped[datetime] = created_at_col()


class CopilotConversation(Base):
    """Per-user chat thread; state_json holds clarify-then-answer details (redacted)."""

    __tablename__ = "copilot_conversation"
    __table_args__ = (Index("ix_copilot_conversation_user_updated", "user_id", "updated_at"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = created_at_col()
    state_json: Mapped[dict[str, Any]] = mapped_column(JsonDoc, default=dict)


class CopilotConvMessage(Base):
    __tablename__ = "copilot_message"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_copilot_message_role"),
        Index("ix_copilot_message_conversation", "conversation_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("copilot_conversation.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(Text)  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()


class KnowledgeDoc(Base):
    """Chunk of the synthetic Liquidity Playbook used for TF-IDF RAG."""

    __tablename__ = "knowledge_docs"
    __table_args__ = (
        UniqueConstraint("slug", "lang", "chunk_idx", name="uq_knowledge_docs_slug_lang_chunk"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    lang: Mapped[Lang] = mapped_column(db_enum(Lang))
    chunk_idx: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)
    source_path: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = created_at_col()

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.core.config import LlmProvider
from app.core.params import DbId
from app.models.enums import FloatType, GeneratedBy, GuardResult, Lang, LlmIntent
from app.schemas.system import LlmMode

# Why the template was served instead of LLM wording (None = LLM / replay wording, or template
# mode by configuration).
FallbackReason = Literal["rate_limited", "daily_cap", "timeout", "error", "numbers_fail",
                         "schema_fail", "injection", "replay_miss", "not_configured"]


class LlmText(BaseModel):
    """Generated wording. Numbers inside `text` are verified against the evidence pack."""

    intent: LlmIntent
    text: str
    lang: Lang
    cited_factors: list[str]
    generated_by: GeneratedBy  # llm | replay = AI-generated wording; template = deterministic
    provider: str
    model: str | None
    guard_result: GuardResult
    fallback_reason: FallbackReason | None
    template_text: str  # deterministic text; the UI can show it first
    cached: bool
    # Template served because no API key is set: the UI says "Template wording (no API key)".
    no_api_key: bool = False
    evidence_hash: str
    model_version: str | None  # of the predictions the evidence came from
    generated_at: datetime
    advisory: Literal[True] = True


class NarrateIn(BaseModel):
    agent_id: DbId
    target: FloatType = FloatType.cash
    lang: Lang | None = None  # default: user's language


class LlmStatus(BaseModel):
    configured: LlmProvider
    mode: LlmMode
    live: bool
    model: str | None
    key_configured: bool
    replay_entries: int
    # "live_clock": a recorded-wording file exists but is skipped, its scenario needs the fixed
    # clock (CLOCK_MODE=fixed). None: replay is not being skipped.
    replay_skipped: Literal["live_clock"] | None = None
    no_api_key: bool = False  # template wording is served because no key is set
    calls_today: int
    daily_cap: int
    user_calls_per_min: int
    last_error: str | None
    last_error_at: datetime | None
    generated_at: datetime

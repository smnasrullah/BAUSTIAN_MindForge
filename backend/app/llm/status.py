from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.llm import store
from app.llm.mode import LIVE, no_api_key, replay_skipped, resolve_mode
from app.schemas.llm import LlmStatus


def llm_status(session: Session, settings: Settings) -> LlmStatus:
    mode = resolve_mode(settings)
    err = store.last_error(session)
    return LlmStatus(
        configured=settings.llm_provider, mode=mode, live=mode in LIVE,
        model=settings.llm_model if mode in LIVE else None,
        key_configured=bool(settings.llm_api_key.get_secret_value()),
        replay_entries=len(store.replay_entries(settings.llm_replay_file)),
        replay_skipped="live_clock" if replay_skipped(settings) else None,
        no_api_key=no_api_key(settings),
        calls_today=store.live_calls_today(session), daily_cap=settings.llm_daily_call_cap,
        user_calls_per_min=settings.llm_user_calls_per_min,
        last_error=err[0] if err else None, last_error_at=err[1] if err else None,
        generated_at=datetime.now(UTC))

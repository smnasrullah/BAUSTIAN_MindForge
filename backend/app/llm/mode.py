from app.core.config import Settings
from app.schemas.system import LlmMode

LIVE: frozenset[LlmMode] = frozenset({"anthropic", "openai_compatible"})


def has_key(settings: Settings) -> bool:
    return bool(settings.llm_api_key.get_secret_value())


def replay_allowed(settings: Settings) -> bool:
    """Recorded wording is keyed to the scripted scenario, which only exists on the fixed clock.
    On the live clock the evidence changes every hour, so replay is skipped by design (an
    explicit LLM_PROVIDER=replay is still honoured)."""
    return settings.llm_provider == "replay" or settings.clock_mode == "fixed"


def replay_skipped(settings: Settings) -> bool:
    """True when replay would be used but for the live clock (reported by /llm/status)."""
    return not replay_allowed(settings) and settings.llm_replay_file.is_file()


def no_api_key(settings: Settings) -> bool:
    """Template wording is served because no key is set (not by choice of LLM_PROVIDER=template)."""
    return settings.llm_provider != "template" and not has_key(settings)


def resolve_mode(settings: Settings) -> LlmMode:
    """auto: key -> live provider; no key -> replay (fixed clock, if recorded); else template."""
    if settings.llm_provider != "auto":
        return settings.llm_provider
    if has_key(settings):
        return "openai_compatible" if settings.llm_base_url else "anthropic"
    recorded = replay_allowed(settings) and settings.llm_replay_file.is_file()
    return "replay" if recorded else "template"

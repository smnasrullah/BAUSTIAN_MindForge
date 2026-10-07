"""Per-user sliding-window rate limit on live LLM calls (shared by all workers; the daily cap
is counted from llm_call_log)."""

from app.core.shared_limit import SharedRateLimiter

user_limiter = SharedRateLimiter("llm_user")

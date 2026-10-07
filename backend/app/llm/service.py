"""One wording request: template draft -> cache -> live provider (guarded, one retry) -> replay
-> template. Never raises for an LLM problem; the deterministic template is always the floor."""

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.llm import guard, numbers, prompts, providers, store, templates
from app.llm.guard import GuardFailure, LlmOutput
from app.llm.limits import user_limiter
from app.llm.mode import LIVE, no_api_key, replay_allowed, resolve_mode
from app.llm.packs import Pack
from app.models import User
from app.models.enums import GeneratedBy, GuardResult, Lang
from app.schemas.llm import FallbackReason, LlmText
from app.schemas.system import LlmMode

ATTEMPTS = 2  # first call + one retry / regeneration, then fall back
_GUARD: dict[str, GuardResult] = {g.value: g for g in GuardResult}
_REASON: dict[GuardResult, FallbackReason] = {
    GuardResult.timeout: "timeout", GuardResult.error: "error",
    GuardResult.numbers_fail: "numbers_fail", GuardResult.schema_fail: "schema_fail",
    GuardResult.injection: "injection"}


@dataclass
class _Ctx:
    session: Session
    settings: Settings
    user: User
    pack: Pack
    lang: Lang
    key: str
    draft: templates.Draft
    allowed: numbers.Allowed
    codes: frozenset[str]  # agent codes the output may name (those in the pack)
    question: str | None = None
    history: str | None = None  # earlier turns (redacted), untrusted context
    extra_system: str = ""  # route-specific system rules (copilot service problems)

    def verify(self, out: LlmOutput) -> None:
        # Leaks and injected behaviour first: they are reported as injection, not numbers_fail.
        guard.check_agents(out.text, self.codes)
        guard.check_actions(out.text)
        guard.check_echo(out.text, prompts.system(self.lang))
        guard.check_numbers(out.text, self.allowed)

    def record(self, provider: str, model: str | None, generated_by: GeneratedBy,
               guard_result: GuardResult = GuardResult.passed, error: str | None = None
               ) -> store.CallRecord:
        return store.CallRecord(user_id=self.user.id, intent=self.pack.intent, lang=self.lang,
                                evidence_hash=self.key, provider=provider, model=model,
                                generated_by=generated_by, guard_result=guard_result,
                                error=error)


def _with_notice(ctx: _Ctx, text: str) -> str:
    """When the draft carries the human-approval notice, the answer ends with it."""
    notice = templates.NOTICE[ctx.lang]
    if notice not in ctx.draft.text:
        return text
    return f"{text.replace(notice, ' ').strip()} {notice}"


def _result(ctx: _Ctx, out: LlmOutput | None, by: GeneratedBy, provider: str,
            model: str | None, cached: bool = False, reason: FallbackReason | None = None,
            guard_result: GuardResult = GuardResult.passed, no_key: bool = False) -> LlmText:
    text = ctx.draft.text if out is None else _with_notice(ctx, out.text)
    factors = ctx.draft.cited_factors if out is None else out.cited_factors
    return LlmText(intent=ctx.pack.intent, text=text, lang=ctx.lang, cited_factors=factors,
                   generated_by=by, provider=provider, model=model, guard_result=guard_result,
                   fallback_reason=reason, template_text=ctx.draft.text, cached=cached,
                   no_api_key=no_key, evidence_hash=ctx.key, model_version=ctx.pack.model_version,
                   generated_at=datetime.now(UTC))


def _cached(ctx: _Ctx) -> LlmText | None:
    row = store.cache_get(ctx.session, ctx.key)
    if row is None:
        return None
    try:
        out = LlmOutput.model_validate(row.response)
        ctx.verify(out)
    except (ValidationError, GuardFailure):
        return None
    store.log_call(ctx.session, ctx.record(provider="cache", model=None,
                                           generated_by=GeneratedBy.llm,
                                           guard_result=GuardResult.passed))
    return _result(ctx, out, GeneratedBy.llm, row.provider, None, cached=True)


def _attempt(ctx: _Ctx, provider: providers.Provider) -> tuple[LlmOutput | None,
                                                                 store.CallRecord]:
    rec = ctx.record(provider=provider.name, model=provider.model, generated_by=GeneratedBy.llm,
                     guard_result=GuardResult.passed)
    t0 = time.perf_counter()
    out: LlmOutput | None = None
    try:
        comp = provider.complete(prompts.system(ctx.lang, ctx.extra_system),
                                 prompts.user(ctx.pack, ctx.draft.text, ctx.question,
                                              ctx.history),
                                 prompts.MAX_TOKENS[ctx.pack.intent])
        rec.prompt_tokens, rec.completion_tokens = comp.prompt_tokens, comp.completion_tokens
        out = guard.parse(comp.text, ctx.lang, ctx.pack.factors)
        ctx.verify(out)
    except providers.ProviderTimeout as exc:
        out, rec.guard_result, rec.error = None, GuardResult.timeout, str(exc)
    except providers.ProviderError as exc:
        out, rec.guard_result, rec.error = None, GuardResult.error, str(exc)
    except GuardFailure as exc:
        out, rec.guard_result, rec.error = None, exc.result, exc.detail
    except Exception as exc:  # a provider bug must not break the page
        out, rec.guard_result, rec.error = None, GuardResult.error, type(exc).__name__
    rec.latency_ms = round((time.perf_counter() - t0) * 1000)
    store.log_call(ctx.session, rec)
    return out, rec


def _live(ctx: _Ctx, mode: LlmMode) -> tuple[LlmText | None, FallbackReason | None]:
    s = ctx.settings
    if store.live_calls_today(ctx.session) >= s.llm_daily_call_cap:
        return None, "daily_cap"
    if not user_limiter.allow(ctx.user.id, s.llm_user_calls_per_min):
        return None, "rate_limited"
    provider = providers.build(mode, s)
    reason: FallbackReason = "error"
    for attempt in range(ATTEMPTS):
        if attempt and store.live_calls_today(ctx.session) >= s.llm_daily_call_cap:
            return None, "daily_cap"
        out, rec = _attempt(ctx, provider)
        if out is not None:
            store.cache_put(ctx.session, ctx.key, ctx.pack.intent, out.model_dump(mode="json"),
                            provider.name, s.llm_cache_ttl_h)
            return _result(ctx, out, GeneratedBy.llm, provider.name, provider.model), None
        reason = _REASON.get(rec.guard_result, "error")
    return None, reason


def _replay(ctx: _Ctx) -> LlmText | None:
    entry = store.replay_entries(ctx.settings.llm_replay_file).get(ctx.key)
    if entry is None:
        return None
    try:
        out = guard.parse(json.dumps(entry, ensure_ascii=False), ctx.lang, ctx.pack.factors)
        ctx.verify(out)
    except GuardFailure:
        return None
    model = entry.get("model")
    store.log_call(ctx.session, ctx.record(provider="replay", model=model,
                                           generated_by=GeneratedBy.replay,
                                           guard_result=GuardResult.passed))
    return _result(ctx, out, GeneratedBy.replay, "replay", model)


def _template(ctx: _Ctx, reason: FallbackReason | None, no_key: bool = False) -> LlmText:
    result = _GUARD.get(reason or "", GuardResult.passed)
    store.log_call(ctx.session, ctx.record(provider="template", model=None,
                                           generated_by=GeneratedBy.template,
                                           guard_result=result, error=reason))
    return _result(ctx, None, GeneratedBy.template, "template", None, reason=reason,
                   guard_result=result, no_key=no_key)


def _context(session: Session, settings: Settings, user: User, pack: Pack, lang: Lang,
             question: str | None, draft: templates.Draft | None) -> _Ctx:
    pack = Pack(pack.intent, guard.scrub(pack.data), pack.model_version)
    question = None if question is None else guard.sanitize(question)
    draft = draft or templates.render(pack, lang)
    evidence = json.dumps(pack.data, ensure_ascii=False)
    return _Ctx(session, settings, user, pack, lang,
                store.evidence_key(pack.intent, lang, pack.data, question), draft,
                numbers.allowed_from(pack.data, [draft.text]),
                frozenset(guard.agent_codes(evidence)), question)


def fixed(session: Session, settings: Settings, user: User, pack: Pack, lang: Lang,
          draft: templates.Draft, blocked: bool = False) -> LlmText:
    """Deterministic answer with no LLM call (copilot refusals), logged like any other output;
    `blocked` marks a refused injection / out-of-scope request."""
    ctx = _context(session, settings, user, pack, lang, None, draft)
    return _template(ctx, "injection" if blocked else None)


def generate(session: Session, settings: Settings, user: User, pack: Pack, lang: Lang,
             question: str | None = None, draft: templates.Draft | None = None,
             history: str | None = None, extra_system: str = "") -> LlmText:
    """`question`: the copilot user's text (untrusted; part of the cache / replay key).
    `draft`: deterministic text when the pack's intent has no renderer in templates.py.
    `history`: earlier copilot turns (untrusted; part of the cache key when present)."""
    ctx = _context(session, settings, user, pack, lang, question, draft)
    if history or extra_system:
        keyed = f"{ctx.question or ''}\n{history or ''}\n{extra_system}"
        ctx.key = store.evidence_key(pack.intent, lang, ctx.pack.data, keyed)
        ctx.history, ctx.extra_system = history, extra_system
    mode = resolve_mode(settings)
    reason: FallbackReason | None = None
    if mode in LIVE:
        if (hit := _cached(ctx)) is not None:
            return hit
        out, reason = _live(ctx, mode)
        if out is not None:
            return out
    if mode == "replay" or (mode in LIVE and settings.llm_provider == "auto"
                            and replay_allowed(settings)):
        if (out := _replay(ctx)) is not None:
            return out
        reason = reason or "replay_miss"
    return _template(ctx, reason, no_key=no_api_key(settings))

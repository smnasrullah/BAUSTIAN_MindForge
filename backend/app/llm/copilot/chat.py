"""One Agent Copilot turn: route -> evidence pack (the scoped agent only) -> deterministic draft
-> guarded LLM wording, or a fixed refusal with no LLM call -> chat history.

The LLM sees only this pack, the draft and the user's question (as untrusted data); every
number in its answer is checked against the pack, and agent codes outside it are rejected.
"""

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.llm import guard, packs, service, templates
from app.llm.copilot import answers, support, tools
from app.llm.copilot.intents import Route, Routed, route
from app.llm.numbers import BDT
from app.llm.packs import Pack
from app.llm.templates import Draft
from app.models import Agent, CopilotConversation, CopilotMessage, User
from app.models.enums import ChatRole, Lang, LlmIntent
from app.schemas.copilot import CopilotMeta, CopilotReply, CopilotSource
from app.schemas.llm import LlmText
from app.services import copilot_history as history
from app.services.forecast import sim_now

PACK_VERSION = 1
CHUNK_WORDS = 4
_REFUSED = (Route.blocked, Route.off_topic)


@dataclass(frozen=True)
class Turn:
    routed: Routed
    pack: Pack
    draft: Draft
    state: dict[str, Any] | None = None  # new conversation state (service problems)
    problem: bool = False  # clarify-then-answer service problem


def _support(agent: Agent, message: str, lang: Lang, state: dict[str, Any]) -> Turn | None:
    """Unsafe requests -> polite refusal; service problems -> clarify, then numbered steps."""
    intent = support.classify(message)
    base = {"v": PACK_VERSION, "agent": {"id": agent.id, "code": agent.code,
                                         "district": agent.district}, "factors": []}
    if intent is support.Intent.unsafe:
        return Turn(Routed(Route.blocked), Pack(LlmIntent.copilot, {**base, "route": "unsafe"},
                                                None), support.refusal_draft(lang))
    if intent is not support.Intent.service_problem and not support.open_problem(state):
        return None
    new = support.merge(state, support.redact(message))
    details = new["details"]
    if support.enough(details) or support.open_problem(state):
        draft, new["stage"] = support.steps_draft(lang), "answered"
    else:
        draft, new["stage"] = support.ask_draft(details, lang), "asked"
    data = {**base, "route": support.Intent.service_problem.value, "details": details}
    return Turn(Routed(Route.howto), Pack(LlmIntent.copilot, data, None), draft, new, True)


def plan(session: Session, settings: Settings, user: User, agent: Agent, message: str,
         lang: Lang, state: dict[str, Any] | None = None) -> Turn:
    """Route the question and build its evidence (tools run here, read-only, scoped)."""
    routed = route(message, lang, agent.code, 24 - sim_now(session).astimezone(BDT).hour)
    if routed.route is not Route.blocked and (
            turn := _support(agent, message, lang, state or {})) is not None:
        return turn
    if routed.route is Route.status and (brief := packs.agent_briefing(session, agent)):
        data = {**brief.data, "route": Route.status.value}
        return Turn(routed, Pack(LlmIntent.copilot, data, brief.model_version),
                    templates.render(brief, lang))
    data = {"v": PACK_VERSION, "route": routed.route.value,
            "agent": {"id": agent.id, "code": agent.code, "district": agent.district},
            "factors": []}
    model_version: str | None = None
    if routed.tool is not None:
        result = tools.execute(session, settings, user, agent, routed.tool)
        data |= {"tool": routed.tool.model_dump(mode="json"), "result": result}
        model_version = result.get("model_version")
    if routed.hits:
        data["playbook"] = [{"slug": h.passage.slug, "title": h.passage.title,
                             "text": h.passage.text} for h in routed.hits]
    return Turn(routed, Pack(LlmIntent.copilot, data, model_version), answers.render(data, lang))


def meta(turn: Turn, agent: Agent) -> CopilotMeta:
    return CopilotMeta(agent_id=agent.id, route=turn.routed.route, tool=turn.routed.tool,
                       sources=[CopilotSource(slug=h.passage.slug, title=h.passage.title,
                                              score=h.score) for h in turn.routed.hits])


def _cited(text: LlmText, turn: Turn, lang: Lang) -> LlmText:
    """Playbook answers name their source even when the LLM dropped the title."""
    titles = list(dict.fromkeys(h.passage.title for h in turn.routed.hits))
    if not titles or any(t in text.text for t in titles):
        return text
    notice = templates.NOTICE[lang]
    cite = f"Source: {'; '.join(titles)}." if lang is Lang.en else f"সূত্র: {'; '.join(titles)}।"
    body = text.text.replace(notice, " ").strip()
    return text.model_copy(update={"text": f"{body} {cite} {notice}"})


def _save(session: Session, user: User, agent: Agent, message: str, answer: LlmText) -> None:
    session.add_all([
        CopilotMessage(user_id=user.id, agent_id=agent.id, role=ChatRole.user,
                       text=guard.sanitize(message), lang=answer.lang),
        CopilotMessage(user_id=user.id, agent_id=agent.id, role=ChatRole.assistant,
                       text=answer.text, lang=answer.lang, generated_by=answer.generated_by)])
    session.flush()


def answer(session: Session, settings: Settings, user: User, agent: Agent, message: str,
           lang: Lang, turn: Turn, conv: CopilotConversation | None = None) -> CopilotReply:
    if turn.routed.route in _REFUSED:
        text = service.fixed(session, settings, user, turn.pack, lang, turn.draft,
                             blocked=turn.routed.route is Route.blocked)
    else:
        past = history.llm_history(session, conv) if conv is not None else None
        extra = support.SYSTEM_EXTRA if turn.problem else ""
        text = service.generate(session, settings, user, turn.pack, lang, question=message,
                                draft=turn.draft, history=past, extra_system=extra)
        if turn.routed.route is Route.howto:
            text = _cited(text, turn, lang)
    _save(session, user, agent, message, text)
    if conv is not None:
        history.append(session, conv, "user", message)
        history.append(session, conv, "assistant", text.text)
        if turn.problem or conv.state_json:
            history.set_state(conv, turn.state or {})
    return CopilotReply(**dict(meta(turn, agent)), answer=text,
                        conversation_id=conv.id if conv is not None else None)


def ask(session: Session, settings: Settings, user: User, agent: Agent, message: str,
        lang: Lang, conv: CopilotConversation | None = None) -> CopilotReply:
    """Whole turn without streaming (scripts, tests)."""
    state = conv.state_json if conv is not None else None
    return answer(session, settings, user, agent, message, lang,
                  plan(session, settings, user, agent, message, lang, state), conv)


def chunks(text: str, words: int = CHUNK_WORDS) -> list[str]:
    parts = re.findall(r"\S+\s*", text)
    return ["".join(parts[i:i + words]) for i in range(0, len(parts), words)]

"""Deterministic intent routing for the Agent Copilot (bn/en). Runs before any LLM call.

Order: blocked (injection or another agent) -> what-if -> how-to (playbook) -> swap status ->
risk status -> forecast window -> any other liquidity question (playbook, else status) ->
off-topic. The LLM never picks a route or a tool; tool requests are built here as validated
ToolCall objects and executed by the backend (tools.py).
"""

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from app.llm import guard, numbers, rag
from app.llm.copilot.tools import ForecastWindowCall, SwapStatusCall, ToolCall, WhatIfCall
from app.models.enums import FloatType, Lang
from ml.features.build import MAX_HORIZON_H

DEFAULT_WINDOW_H = 24


class Route(StrEnum):
    blocked = "blocked"  # prompt injection or another agent's data: refused, no LLM call
    off_topic = "off_topic"  # not about liquidity: refused, no LLM call
    status = "status"
    whatif = "whatif"
    swap_status = "swap_status"
    forecast_window = "forecast_window"
    howto = "howto"


@dataclass(frozen=True)
class Routed:
    route: Route
    tool: ToolCall | None = None
    hits: tuple[rag.Hit, ...] = ()


def _rx(*parts: str) -> re.Pattern[str]:
    return re.compile("|".join(unicodedata.normalize("NFC", p) for p in parts), re.IGNORECASE)


_INJECTION = _rx(
    r"\b(ignore|disregard|forget|override|bypass|skip)\b.{0,40}\b(rules?|instructions?|prompts?|"
    r"guidelines?|polic(y|ies)|restrictions?)\b",
    r"\bsystem prompt\b", r"\bdeveloper mode\b", r"\bjailbreak", r"\byou are now\b",
    r"\bpretend\b", r"\bact as\b", r"\beveryone'?s\b",
    # Asking for other agents' data (asking to swap with another agent is fine).
    r"\b(show|tell|list|give|share|reveal|display|compare)\b.{0,40}\b(other|another|all|every)"
    r"\s+agents?\b",
    r"\b(other|another|all|every)\s+agents?'?s?\b.{0,40}\b(data|balances?|details?|info\w*|"
    r"numbers?|cash|floats?|risks?|names?|list|phones?)\b",
    r"(নিয়ম|নির্দেশ|নির্দেশনা).{0,20}(উপেক্ষা|ভুলে|বাদ|মানবে না|মানার দরকার নেই)",
    r"(উপেক্ষা|ভুলে).{0,20}(নিয়ম|নির্দেশ)", r"সিস্টেম প্রম্পট",
    r"(অন্য|অন্যান্য|সব|সকল|প্রত্যেক)\s*এজেন্ট\S*.{0,30}(তথ্য|ব্যালেন্স|দেখা|বল|তালিকা|নাম|"
    r"ঝুঁকি|টাকা|নগদ|ক্যাশ|ফোন)",
    r"(সবার|অন্যদের)\s*(তথ্য|ব্যালেন্স|টাকা|নগদ|ক্যাশ|ঝুঁকি)")
_DOMAIN = _rx(
    r"\b(cash|float|e-?money|e money|balance|swaps?|van|risk|alert|red|amber|green|stockout|"
    r"run(s|ning)? out|runway|forecast|demand|eid|salary|hat-?bazar|market day|rain|deposit|"
    r"withdraw\w*|cash-?(out|in)|top-?up|refill|distributor|agent|liquidity|money|taka|bdt|"
    r"safe(ty)?|robbery|pin|otp|approv\w*|request|playbook|confidence|customers?|bank|"
    r"remittance)\b",
    r"নগদ|টাকা|ক্যাশ|ফ্লোট|ই-?মানি|ব্যালেন্স|অদল-?বদল|সোয়াপ|ভ্যান|ঝুঁকি|সতর্ক|লাল|হলুদ|সবুজ|"
    r"শেষ হ|রানওয়ে|পূর্বাভাস|চাহিদা|ঈদ|বেতন|হাট|বৃষ্টি|জমা|তোল|তুল|টপ-?আপ|রিফিল|"
    r"ডিস্ট্রিবিউটর|এজেন্ট|তারল্য|লিকুইডিটি|নিরাপ|পিন|ওটিপি|অনুমোদন|অনুরোধ|প্লেবুক|আস্থা|"
    r"গ্রাহক|ব্যাংক|রেমিট্যান্স")
_WHATIF = _rx(r"\bwhat if\b", r"\bwhat (happens|would happen) if\b", r"\bsuppose\b",
              r"\bif i (add|put|deposit|get|take|remove|withdraw|move)\b", r"যদি", r"ধরুন", r"ধরি")
_HOWTO = _rx(r"\bhow (do|to|can|should|does)\b", r"\bwhat (does|is a|is an)\b", r"\bmean(s|ing)?\b",
             r"\bpolicy\b", r"\betiquette\b", r"\bshould i\b", r"\bsafe(ty|ly)?\b", r"\bprepare\b",
             r"\btips?\b", r"\bexplain\b", r"কীভাবে|কিভাবে|কেমনে|মানে|অর্থ কী|কী বোঝায়|নিয়ম|নীতি|"
             r"নিরাপ|প্রস্তুতি|উচিত|কী করব|শিষ্টাচার")
_SWAP = _rx(r"\bswap(s|ping)?\b", r"\bexchange\b", r"অদল-?বদল|সোয়াপ|বিনিময়")
_STATUS = _rx(r"\brisk", r"\brun(s|ning)? out\b", r"\brunway\b", r"\bstockout", r"\bbalance\b",
              r"\balert\b", r"\blevel\b", r"\bred\b", r"\bamber\b", r"\benough\b", r"\bhow long\b",
              r"\bstatus\b", r"\bbriefing\b",
              r"ঝুঁকি|শেষ হ|ব্যালেন্স|সতর্ক|লাল|হলুদ|যথেষ্ট|কতক্ষণ|অবস্থা")
_FORECAST = _rx(r"\bforecast", r"\bexpect", r"\bdemand\b", r"\bpredict", r"\btomorrow\b",
                r"\btonight\b", r"\btoday\b", r"\bthis evening\b", r"\b\d+\s*(h|hrs?|hours?)\b",
                r"পূর্বাভাস|চাহিদা|আগামীকাল|আজ|ঘণ্টা|ঘন্টা")
_TOMORROW = _rx(r"\btomorrow\b", r"আগামীকাল")
_TODAY = _rx(r"\btoday\b", r"\btonight\b", r"\bthis evening\b", r"আজ")
_HOURS = _rx(r"(\d+)\s*(?:h\b|hrs?\b|hours?\b|ঘণ্টা|ঘন্টা)")
_AMOUNT = re.compile(r"(\d+(?:\.\d+)?)\s*(k\b|thousand\b|হাজার|lakh\b|lac\b|লাখ|লক্ষ)?",
                     re.IGNORECASE)
_SCALE = {"k": 1_000, "thousand": 1_000, "হাজার": 1_000, "lakh": 100_000, "lac": 100_000,
          "লাখ": 100_000, "লক্ষ": 100_000}
_MINUS = _rx(r"\b(remove|withdraw|take out|take away|less|reduce|minus|lower)\b",
             r"কমা|কমি|সরা|বাদ দি|তুলে নি")
_EMONEY = _rx(r"\be-?money\b", r"\be money\b", r"\bdigital\b", r"ই-?মানি|ডিজিটাল")


def normalise(message: str) -> str:
    # NFKC folds full-width look-alikes; zero-width / bidi characters cannot split a keyword.
    return numbers.normalise(unicodedata.normalize("NFKC", guard.strip_control(message)))


def is_blocked(text: str, own_code: str) -> bool:
    return bool(guard.agent_codes(text) - {own_code}) or bool(_INJECTION.search(text))


def amount(text: str) -> float | None:
    """First money amount in the text (agent codes and hour counts ignored), with k/lakh."""
    text = _HOURS.sub(" ", guard.AGENT_CODE.sub(" ", text))
    m = _AMOUNT.search(text)
    if m is None:
        return None
    value = float(m.group(1)) * _SCALE.get((m.group(2) or "").lower(), 1)
    return -value if _MINUS.search(text) else value


def window(text: str, hours_to_midnight: int) -> tuple[int, int]:
    """(from_h, to_h) after the forecast's as-of hour; today ends at local midnight."""
    midnight = min(max(hours_to_midnight, 1), MAX_HORIZON_H)
    if _TOMORROW.search(text):
        return midnight, min(midnight + 24, MAX_HORIZON_H)
    if m := _HOURS.search(text):
        return 0, min(max(int(m.group(1)), 1), MAX_HORIZON_H)
    if _TODAY.search(text):
        return 0, midnight
    return 0, DEFAULT_WINDOW_H


def route(message: str, lang: Lang, own_code: str, hours_to_midnight: int) -> Routed:
    text = normalise(message)
    if is_blocked(text, own_code):
        return Routed(Route.blocked)
    if not _DOMAIN.search(text) and not _WHATIF.search(text):
        return Routed(Route.off_topic)
    howto = bool(_HOWTO.search(text))
    if _WHATIF.search(text) and ((delta := amount(text)) is not None or not howto):
        ft = FloatType.emoney if _EMONEY.search(text) else FloatType.cash
        tool = None if delta is None or delta == 0 else WhatIfCall(
            tool="get_whatif", float_type=ft, delta_amount=delta)
        return Routed(Route.whatif, tool)
    hits = tuple(rag.search(message, lang))
    if howto and hits:
        return Routed(Route.howto, hits=hits)
    if _SWAP.search(text):
        return Routed(Route.swap_status, SwapStatusCall(tool="get_swap_status"))
    if _STATUS.search(text):
        return Routed(Route.status)
    if _FORECAST.search(text):
        lo, hi = window(text, hours_to_midnight)
        return Routed(Route.forecast_window,
                      ForecastWindowCall(tool="get_forecast_window", from_h=lo, to_h=hi))
    return Routed(Route.howto, hits=hits) if hits else Routed(Route.status)

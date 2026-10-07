"""Copilot clarify-then-answer for service problems, plus redaction and a coarse intent check
(keyword rules, bn/en). Deterministic: the LLM only rewords the draft built here.

The copilot never asks for a PIN or OTP, never moves money and never states upay fees, limits
or time windows; steps below are generic and point to the distributor or upay support.
"""

import re
import unicodedata
from enum import StrEnum
from typing import Any

from app.llm import guard, numbers
from app.llm.templates import NOTICE, Draft
from app.models.enums import Lang

MAX_FOLLOWUPS = 2  # questions in the single clarifying turn
_D = "[0-9০-৯]"


class Intent(StrEnum):
    liquidity_data = "liquidity_data"
    service_problem = "service_problem"
    unsafe = "unsafe"
    other = "other"


def _rx(*parts: str) -> re.Pattern[str]:
    return re.compile("|".join(unicodedata.normalize("NFC", p) for p in parts), re.IGNORECASE)


# --- redaction -----------------------------------------------------------------------------
_PHONE = re.compile(rf"(?:\+?(?:88|৮৮)[-\s]?)?(?:0|০)[-\s]?(?:1|১){_D}(?:[-\s]?{_D}){{8}}")
_SECRET = _rx(rf"((?:\bpin\b|\botp\b|\bpassword\b|\bcode\b|পিন|ওটিপি|কোড|পাসওয়ার্ড)\D{{0,20}}?)"
              rf"{_D}(?:[-\s]?{_D}){{3,7}}")
_LONG_DIGITS = re.compile(rf"{_D}(?:[-\s]?{_D}){{9,}}")


def redact(text: str) -> str:
    """Phone numbers, anything next to PIN / OTP / code, and long digit runs (account ids)."""
    text = _PHONE.sub("[phone]", text)
    text = _SECRET.sub(lambda m: f"{m.group(1)}[redacted]", text)
    return _LONG_DIGITS.sub("[number]", text)


# --- intent --------------------------------------------------------------------------------
_UNSAFE = _rx(
    r"\b(tell|give|share|send|need|want|ask)\b.{0,25}\b(pin|otp|password)\b",
    r"\b(my|the|customer'?s?)\s+(pin|otp|password)\s+(is|=|:)",
    r"\b(transfer|send|move|pay|cash ?out)\b.{0,30}\b(for me|on my behalf|right now|yourself)\b",
    r"\b(hack|bypass|fake|forge|steal|launder|scam)\w*",
    r"(পিন|ওটিপি|পাসওয়ার্ড).{0,20}(দিন|দাও|দিচ্ছি|বলুন|বলো|পাঠা|শেয়ার|নিন)",
    r"(টাকা|ক্যাশ).{0,20}(পাঠিয়ে দাও|পাঠিয়ে দিন|ট্রান্সফার করে দাও|ট্রান্সফার করে দিন)",
    r"হ্যাক|জাল|প্রতারণা")
_PROBLEM = _rx(
    r"\b(fail(ed|s|ure)?|stuck|pending|not (received|reached|showing|credited)|didn'?t (get|"
    r"receive|reach)|deducted|error|problem|issue|wrong number|reversed?|declined|not working)\b",
    r"ব্যর্থ|আটকে|আসেনি|আসে নাই|পাইনি|পায়নি|কেটে|কাটা|কেটেছে|সমস্যা|ভুল নম্বর|এরর|ত্রুটি|"
    r"হচ্ছে না|হয়নি|যায়নি")
_LIQUIDITY = _rx(
    r"\b(cash|float|e-?money|balance|swap|van|risk|stockout|run(s|ning)? out|forecast|demand|"
    r"refill|liquidity|what if)\b",
    r"নগদ|ক্যাশ|ফ্লোট|ই-?মানি|ব্যালেন্স|সোয়াপ|ভ্যান|ঝুঁকি|পূর্বাভাস|চাহিদা|তারল্য|যদি")


def classify(message: str) -> Intent:
    text = unicodedata.normalize("NFKC", guard.strip_control(message))
    if _UNSAFE.search(text):
        return Intent.unsafe
    if _PROBLEM.search(text):
        return Intent.service_problem
    if _LIQUIDITY.search(text):
        return Intent.liquidity_data
    return Intent.other


# --- details -------------------------------------------------------------------------------
_CASH_IN = _rx(r"\bcash[\s-]?in\b", r"\bdeposit", r"ক্যাশ\s?ইন|জমা")
_CASH_OUT = _rx(r"\bcash[\s-]?out\b", r"\bwithdraw", r"ক্যাশ\s?আউট|উত্তোলন|তোল|তুল")
_TIME = _rx(r"\b\d{1,2}(:\d{2})?\s*(am|pm)\b", r"\b(today|yesterday|morning|afternoon|evening|"
            r"night|ago|minutes?|hours?)\b", r"আজ|গতকাল|সকাল|দুপুর|বিকাল|বিকেল|সন্ধ্যা|রাত|মিনিট|ঘণ্টা")
_SCREEN = _rx(r"\b(sms|message|screen|showed|shows|says|said|error)\b",
              r"মেসেজ|এসএমএস|বার্তা|স্ক্রিন|দেখা(চ্ছে|লো|য়)|লেখা")
_DEDUCTED = _rx(r"\b(deducted|cut|taken|debited)\b", r"কেটে|কাটা|কেটেছে|কাটছে")
_NOT_DEDUCTED = _rx(r"\b(not|no|wasn'?t|didn'?t|never)\b.{0,15}\b(deducted|cut|taken|debited)\b",
                    r"কাটেনি|কাটে নাই|কাটা হয়নি|কাটেনাই")
_AMOUNT = re.compile(r"(?<![\w.])(\d{2,7})(?![\w.])")
_FIELDS = ("kind", "deducted", "amount", "time", "screen")


def extract(message: str) -> dict[str, Any]:
    """Details found in one (already redacted) user message."""
    text = numbers.normalise(unicodedata.normalize("NFKC", message))
    found: dict[str, Any] = {}
    if _CASH_OUT.search(text):
        found["kind"] = "cash_out"
    elif _CASH_IN.search(text):
        found["kind"] = "cash_in"
    if _NOT_DEDUCTED.search(text):
        found["deducted"] = False
    elif _DEDUCTED.search(text):
        found["deducted"] = True
    if m := _AMOUNT.search(text.replace(",", "")):
        found["amount"] = int(m.group(1))
    if m := _TIME.search(text):
        found["time"] = m.group(0)
    if _SCREEN.search(text):
        found["screen"] = guard.sanitize(message, limit=120)
    return found


def merge(state: dict[str, Any], message: str) -> dict[str, Any]:
    details = {**state.get("details", {}), **extract(message)}
    return {**state, "intent": Intent.service_problem.value, "details": details}


def enough(details: dict[str, Any]) -> bool:
    return "kind" in details and sum(f in details for f in _FIELDS[1:]) >= 2


def missing(details: dict[str, Any]) -> list[str]:
    return [f for f in _FIELDS if f not in details][:MAX_FOLLOWUPS]


def open_problem(state: dict[str, Any]) -> bool:
    """A clarifying question is waiting for the agent's answer."""
    return state.get("intent") == Intent.service_problem.value and state.get("stage") == "asked"


# --- wording -------------------------------------------------------------------------------
_ASK = {
    Lang.en: {"kind": "Was it a cash-in or a cash-out?",
              "deducted": "Was money deducted from the account?",
              "amount": "What was the amount?",
              "time": "About what time did it happen?",
              "screen": "What did the screen or SMS say?"},
    Lang.bn: {"kind": "এটা কি ক্যাশ-ইন নাকি ক্যাশ-আউট ছিল?",
              "deducted": "অ্যাকাউন্ট থেকে কি টাকা কেটেছে?",
              "amount": "টাকার পরিমাণ কত ছিল?",
              "time": "প্রায় কখন হয়েছিল?",
              "screen": "স্ক্রিন বা এসএমএস-এ কী লেখা ছিল?"},
}
_ASK_LEAD = {Lang.en: "To help, I need a little more detail:",
             Lang.bn: "সাহায্য করতে আরেকটু তথ্য লাগবে:"}
_STEPS = {
    Lang.en: ["Do not repeat the transaction until you see its status in the app history or "
              "the SMS.",
              "Note the transaction ID, the time and what the screen or SMS said.",
              "If money was deducted but did not reach the other side, contact upay support "
              "through the official helpline in the app with the transaction ID.",
              "If you are short of cash or e-money to serve customers, contact your distributor."],
    Lang.bn: ["অ্যাপের হিস্টোরি বা এসএমএস-এ অবস্থা না দেখা পর্যন্ত লেনদেনটি আবার করবেন না।",
              "লেনদেন আইডি, সময় আর স্ক্রিন বা এসএমএস-এ কী লেখা ছিল তা লিখে রাখুন।",
              "টাকা কেটে গেলেও অন্য পক্ষ না পেলে, লেনদেন আইডি নিয়ে অ্যাপের অফিসিয়াল হেল্পলাইনে upay "
              "সাপোর্টে যোগাযোগ করুন।",
              "গ্রাহককে সেবা দিতে নগদ বা ই-মানি কম পড়লে আপনার ডিস্ট্রিবিউটরের সাথে যোগাযোগ করুন।"],
}
_UNSURE = {Lang.en: "I cannot confirm official upay rules, fees or time limits; upay support can. "
                    "Never share your PIN or OTP with anyone.",
           Lang.bn: "upay-এর অফিসিয়াল নিয়ম, ফি বা সময়সীমা আমি নিশ্চিত করতে পারি না; upay সাপোর্ট "
                    "পারবে। কাউকে আপনার পিন বা ওটিপি দেবেন না।"}
_REFUSE = {Lang.en: "Sorry, I can't help with that. I never ask for or use a PIN or OTP, and I "
                    "cannot move money. Please keep your PIN and OTP private.",
           Lang.bn: "দুঃখিত, এতে সাহায্য করতে পারব না। আমি কখনো পিন বা ওটিপি চাই না বা ব্যবহার করি "
                    "না, আর টাকা পাঠাতে পারি না। পিন ও ওটিপি গোপন রাখুন।"}

SYSTEM_EXTRA = (
    "Service problem mode: if the agent only states a problem, ask at most 2 short follow-up "
    "questions (cash-in or cash-out, amount, time, what the screen or SMS said, whether money "
    "was deducted). Once enough details exist, give short numbered steps and say when to contact "
    "the distributor or upay support. If unsure, say so. Never guess official upay rules, fees, "
    "limits or time windows. Never ask for a PIN or OTP. Keep the draft's questions or steps.")


def ask_draft(details: dict[str, Any], lang: Lang) -> Draft:
    qs = " ".join(_ASK[lang][f] for f in missing(details))
    return Draft(text=f"{_ASK_LEAD[lang]} {qs}", cited_factors=[])


def steps_draft(lang: Lang) -> Draft:
    steps = " ".join(f"{i}. {s}" for i, s in enumerate(_STEPS[lang], start=1))
    return Draft(text=f"{steps} {_UNSURE[lang]} {NOTICE[lang]}", cited_factors=[])


def refusal_draft(lang: Lang) -> Draft:
    return Draft(text=_REFUSE[lang], cited_factors=[])

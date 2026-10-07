"""Deterministic bn/en copilot answers, built only from the copilot evidence pack. They are the
fallback, the draft the LLM rewords, and a source of allowed numbers. Actionable answers end
with the human-approval notice; refusals and plain information do not."""

from typing import Any

from app.llm.copilot.intents import Route
from app.llm.templates import DAY, FLOAT, LEVEL, NOTICE, Draft
from app.models.enums import Lang
from ml.explain.templates import DEMAND, amount, bn_digits

EN, BN = Lang.en, Lang.bn
REFUSE = {
    Route.blocked: {
        EN: "I can only use this account's own data, and my safety rules cannot be changed, so I "
            "cannot share other agents' information. Ask me about this account's cash, e-money, "
            "risk or swaps.",
        BN: "আমি শুধু এই অ্যাকাউন্টের নিজের তথ্য ব্যবহার করতে পারি, আর আমার নিরাপত্তার নিয়ম "
            "বদলানো যায় না, তাই অন্য এজেন্টের তথ্য দিতে পারব না। এই অ্যাকাউন্টের ক্যাশ, ই-মানি, "
            "ঝুঁকি বা অদল-বদল নিয়ে জিজ্ঞাসা করুন।"},
    Route.off_topic: {
        EN: "Sorry, I can only help with cash and e-money liquidity: balances, risk alerts, "
            "swaps, the cash van and the Liquidity Playbook. Please ask about one of those.",
        BN: "দুঃখিত, আমি শুধু ক্যাশ ও ই-মানির তারল্য নিয়ে সাহায্য করতে পারি: ব্যালেন্স, ঝুঁকির "
            "সতর্কতা, অদল-বদল, ক্যাশ ভ্যান ও লিকুইডিটি প্লেবুক। অনুগ্রহ করে এগুলোর কোনো একটি "
            "নিয়ে জিজ্ঞাসা করুন।"},
}
NOT_READY = {EN: "The forecasts for this account are not ready yet. Please try again in a "
                 "minute.",
             BN: "এই অ্যাকাউন্টের পূর্বাভাস এখনো তৈরি হয়নি। এক মিনিট পরে আবার চেষ্টা করুন।"}
ASK_AMOUNT = {EN: "Tell me the amount and the float, for example: what if I add 20,000 cash?",
              BN: "পরিমাণ ও ফ্লোট বলুন, যেমন: যদি ২০,০০০ টাকা ক্যাশ যোগ করি?"}
STATUS = {"pending": {EN: "waiting for approval", BN: "অনুমোদনের অপেক্ষায়"},
          "approved": {EN: "approved", BN: "অনুমোদিত"},
          "rejected": {EN: "rejected", BN: "বাতিল"}}
RESPONSE = {None: {EN: "not given yet", BN: "এখনো দেননি"},
            "accepted": {EN: "accepted", BN: "গ্রহণ করেছেন"},
            "declined": {EN: "declined", BN: "প্রত্যাখ্যান করেছেন"}}


def _n(x: float | int | str, lang: Lang) -> str:
    text = f"{x:g}" if isinstance(x, float) else str(x)
    return bn_digits(text) if lang is BN else text


def _end(parts: list[str], lang: Lang, actionable: bool) -> str:
    return " ".join(parts + ([NOTICE[lang]] if actionable else []))


def _scenario(s: dict[str, Any], lang: Lang) -> str:
    level = LEVEL[lang][s["level_24h"]]
    if s["hours_to_stockout"] is None or not s["stockout_time"]:
        return (f"no stockout expected within 72 hours, 24-hour risk {level}" if lang is EN
                else f"৭২ ঘণ্টার মধ্যে শেষ হওয়ার সম্ভাবনা কম, ২৪ ঘণ্টার ঝুঁকি {level}")
    hours, when = _n(s["hours_to_stockout"], lang), _n(s["stockout_time"], lang)
    day = DAY[lang][s["stockout_day"]]
    if lang is EN:
        return f"may run out in about {hours} hours (around {when} {day}), 24-hour risk {level}"
    return f"প্রায় {hours} ঘণ্টায় শেষ হতে পারে ({day} {when}-এর কাছাকাছি), ২৪ ঘণ্টার ঝুঁকি {level}"


def _whatif(r: dict[str, Any] | None, lang: Lang) -> str:
    if r is None:
        return ASK_AMOUNT[lang]
    name, amt, add = FLOAT[lang][r["float_type"]], amount(r["delta_bdt"], lang), r["delta_bdt"] > 0
    if r["status"] == "not_ready":
        return NOT_READY[lang]
    if r["status"] == "out_of_bounds":
        return (f"Changing {name} by {amt} would take it below zero or above its capacity. Try a "
                "smaller amount." if lang is EN else
                f"{name}-এ {amt} পরিবর্তন করলে তা শূন্যের নিচে বা সীমার ওপরে চলে যাবে। কম পরিমাণ দিয়ে "
                "চেষ্টা করুন।")
    after, before = _scenario(r["after"], lang), _scenario(r["before"], lang)
    if lang is EN:
        verb = f"add {amt} to" if add else f"take {amt} out of"
        return _end([f"If you {verb} {name} now: {after}.", f"Without it: {before}."], lang, True)
    verb = "যোগ করলে" if add else "কমালে"
    return _end([f"এখন {name}-এ {amt} {verb}: {after}।", f"না করলে: {before}।"], lang, True)


def _swap_line(s: dict[str, Any], lang: Lang) -> str:
    amt, name = amount(s["amount_bdt"], lang), FLOAT[lang][s["float_type"]]
    p, km = s["partner"], _n(s["distance_km"], lang)
    status, resp = STATUS[s["status"]][lang], RESPONSE[s["my_response"]][lang]
    sid = _n(s["id"], lang)
    if lang is EN:
        verb = "give" if s["role"] == "give" else "receive"
        prep = "to" if s["role"] == "give" else "from"
        return (f"Swap {sid}: you {verb} {amt} {name.lower()} {prep} {p['code']} ({p['name']}), "
                f"{km} km away; {status}, your answer: {resp}.")
    verb = "দেবেন" if s["role"] == "give" else "পাবেন"
    return (f"অদল-বদল {sid}: {p['code']} ({p['name']}, {km} কিমি দূরে) — আপনি {amt} {name} {verb}; "
            f"{status}, আপনার উত্তর: {resp}।")


def _swaps(r: dict[str, Any], lang: Lang) -> str:
    if r["status"] == "not_ready":
        return NOT_READY[lang]
    if not r["items"]:
        return ("There is no swap suggestion for this account right now." if lang is EN else
                "এই মুহূর্তে এই অ্যাকাউন্টের জন্য কোনো অদল-বদলের প্রস্তাব নেই।")
    total = _n(r["total"], lang)
    head = (f"Swap suggestions for this account: {total}." if lang is EN else
            f"এই অ্যাকাউন্টের অদল-বদলের প্রস্তাব: {total}টি।")
    return _end([head] + [_swap_line(s, lang) for s in r["items"]], lang, True)


def _forecast(r: dict[str, Any], lang: Lang) -> str:
    if r["status"] == "not_ready":
        return NOT_READY[lang]
    start = f"{_n(r['from_time'], lang)} {DAY[lang][r['from_day']]}"
    end = f"{_n(r['to_time'], lang)} {DAY[lang][r['to_day']]}"
    parts = [f"Forecast from {start} to {end}:" if lang is EN
             else f"{start} থেকে {end} পর্যন্ত পূর্বাভাস:"]
    for f in r["floats"]:
        demand, name = DEMAND[lang][f["demand_type"]], FLOAT[lang][f["float_type"]]
        demand = demand[:1].upper() + demand[1:]
        exp, lo, hi = (amount(f[f"{k}_bdt"], lang) for k in ("expected", "low", "high"))
        parts.append(f"{demand} about {exp} (likely {lo} to {hi}), drawing down {name}." if lang
                     is EN else f"{demand} প্রায় {exp} (সম্ভাব্য {lo} থেকে {hi}), এতে {name} কমবে।")
    return " ".join(parts)


def _howto(passages: list[dict[str, Any]], lang: Lang) -> str:
    titles = "; ".join(dict.fromkeys(p["title"] for p in passages))
    body = " ".join(p["text"] for p in passages[:2])
    if lang is EN:
        return _end([f"From the Liquidity Playbook: {body}", f"Source: {titles}."], lang, True)
    return _end([f"লিকুইডিটি প্লেবুক অনুযায়ী: {body}", f"সূত্র: {titles}।"], lang, True)


def render(data: dict[str, Any], lang: Lang) -> Draft:
    """Draft for every copilot route except `status` (that reuses the agent briefing)."""
    route = Route(data["route"])
    if route in REFUSE:
        return Draft(REFUSE[route][lang], [])
    result: dict[str, Any] | None = data.get("result")
    if route is Route.whatif:
        return Draft(_whatif(result, lang), [])
    if route is Route.swap_status and result is not None:
        return Draft(_swaps(result, lang), [])
    if route is Route.forecast_window and result is not None:
        return Draft(_forecast(result, lang), [])
    if route is Route.howto and data.get("playbook"):
        return Draft(_howto(data["playbook"], lang), [])
    return Draft(NOT_READY[lang], [])

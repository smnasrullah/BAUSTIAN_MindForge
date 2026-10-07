"""Deterministic bn/en wording of a van plan, built only from its evidence pack
(app/services/van_plan_actions.evidence). It is the draft the LLM rewrites through the guarded
service (intent van_narrative) and the fallback whenever that fails.
"""

from typing import Any

from app.llm.templates import NOTICE
from app.models.enums import Lang
from ml.explain.templates import amount, bn_digits

EN, BN = Lang.en, Lang.bn


def _n(x: float | int, lang: Lang) -> str:
    text = str(round(x))
    return bn_digits(text) if lang is BN else text


def _plan(d: dict[str, Any], lang: Lang) -> str:
    trips, served, km = _n(d["trips"], lang), _n(d["served"], lang), _n(d["km"], lang)
    cost, base = amount(d["total_bdt"], lang), amount(d["separate_total_bdt"], lang)
    if lang is EN:
        return (f"{trips} van trip(s) bring cash to {served} agent(s) over {km} km. Estimated "
                f"cost {cost}, against {base} if every agent got a separate trip. The order "
                "weighs driving cost against each agent's expected cash stockout time.")
    return (f"{trips}টি ভ্যান ট্রিপে {served} জন এজেন্টের কাছে ক্যাশ যাবে, মোট {km} কিমি। "
            f"আনুমানিক খরচ {cost}; প্রত্যেক এজেন্টের জন্য আলাদা ট্রিপ দিলে হতো {base}। "
            "রুটের ক্রম গাড়ির খরচ আর প্রত্যেক এজেন্টের ক্যাশ ফুরানোর সম্ভাব্য সময়ের মধ্যে "
            "ভারসাম্য রাখে।")


def _dropped(d: dict[str, Any], lang: Lang) -> str:
    if not d["dropped"]:
        return ""
    n = {k: _n(d[k], lang) for k in ("dropped", "swap_suggested", "cost_gt_value", "capacity")}
    if lang is EN:
        return (f"{n['dropped']} agent(s) are not on a van: {n['swap_suggested']} covered by a "
                f"swap, {n['cost_gt_value']} where a trip costs more than the cash it protects, "
                f"{n['capacity']} beyond van capacity or shift time.")
    return (f"{n['dropped']} জন এজেন্ট ভ্যানে নেই: সোয়াপে {n['swap_suggested']} জন, ট্রিপের "
            f"খরচ রক্ষা পাওয়া ক্যাশের চেয়ে বেশি বলে {n['cost_gt_value']} জন, ভ্যানের ধারণক্ষমতা "
            f"বা শিফটের সময় ছাড়িয়ে যাওয়ায় {n['capacity']} জন।")


def _excluded(d: dict[str, Any], lang: Lang) -> str:
    if not d.get("excluded"):
        return ""
    n = _n(d["excluded"], lang)
    return (f"{n} agent(s) were taken off the plan by you." if lang is EN
            else f"আপনি {n} জন এজেন্টকে পরিকল্পনা থেকে বাদ দিয়েছেন।")


def _risk(d: dict[str, Any], lang: Lang) -> str:
    if not d.get("flagged"):
        return ""
    n = _n(d["flagged"], lang)
    return (f"{n} agent(s) may run out of cash before the van arrives; consider a swap or an "
            "earlier van for them." if lang is EN
            else f"{n} জন এজেন্টের ক্যাশ ভ্যান পৌঁছানোর আগেই ফুরিয়ে যেতে পারে; তাঁদের জন্য "
            "সোয়াপ বা আগের ভ্যান বিবেচনা করুন।")


def _fair(d: dict[str, Any], lang: Lang) -> str:
    parts: list[str] = []
    if d.get("fairness_forced"):
        n = _n(d["fairness_forced"], lang)
        parts.append(f"{n} stop(s) were added so that every area gets its fair share of vans."
                     if lang is EN else
                     f"প্রতিটি এলাকা যেন ন্যায্যভাবে ভ্যান পায়, তাই {n}টি স্টপ যোগ করা হয়েছে।")
    if d.get("fairness_short"):
        parts.append("Some areas stay below the fair-service target because no van can reach "
                     "them in time." if lang is EN else
                     "কিছু এলাকায় সময়মতো কোনো ভ্যান পৌঁছাতে পারে না, তাই সেখানে ন্যায্য সেবার "
                     "লক্ষ্য পূরণ হয়নি।")
    return " ".join(parts)


def _source(d: dict[str, Any], lang: Lang) -> str:
    if d["distance_source"] == "road_cache":
        return "Distances come from the road cache." if lang is EN else \
            "দূরত্ব রোড ক্যাশ থেকে নেওয়া।"
    return ("Distances are estimates (straight line times a road factor)." if lang is EN
            else "দূরত্ব আনুমানিক (সোজা দূরত্ব গুণ রাস্তার গুণক)।")


def render(d: dict[str, Any], lang: Lang) -> str:
    parts = [_plan(d, lang), _dropped(d, lang), _excluded(d, lang), _risk(d, lang),
             _fair(d, lang), _source(d, lang), NOTICE[lang]]
    return " ".join(p for p in parts if p)

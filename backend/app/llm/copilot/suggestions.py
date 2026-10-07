"""Suggested Copilot questions: the single source for GET /copilot/suggestions and for
scripts/record_replay.py. Copilot replay is keyed by the exact question text, so only these
questions get recorded LLM wording; anything else falls back to the template answer."""

from app.models.enums import Lang

COPILOT_DEMO: dict[Lang, tuple[str, ...]] = {
    Lang.en: ("When will my cash run out?", "How do I request cash?",
              "What does a red alert mean?", "Do I have any swap offers?",
              "What is the expected demand in the next 6 hours?"),
    Lang.bn: ("আমার ক্যাশ কখন শেষ হবে?", "কীভাবে ক্যাশ টাকা চাইব?", "লাল সতর্কতা মানে কী?",
              "অদল-বদলের কী অবস্থা?", "আগামী ৬ ঘণ্টার চাহিদার পূর্বাভাস"),
}


def for_lang(lang: Lang) -> tuple[str, ...]:
    return COPILOT_DEMO[lang]

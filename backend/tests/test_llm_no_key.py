# ruff: noqa: F811  (fixtures imported from test_llm_api are test parameters here)
"""LC-3: wording without an API key. Every LLM surface (explanation, agent / distributor briefing,
anomaly narrative, copilot) is labelled `no_api_key` while it serves template wording, and
generated_by stays truthful (template / replay / llm). Replay only runs on the fixed clock.
No test makes a live call: providers are mocked, or `build` fails the test if reached."""

import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sse_starlette.sse import AppStatus

from app.core.config import Settings, get_settings
from app.llm import guard, numbers, providers, templates
from app.llm.mode import no_api_key, replay_skipped, resolve_mode
from app.llm.packs import Pack
from app.llm.providers import ProviderError
from app.models.enums import Lang, LlmIntent
from tests.auth_helpers import ADMIN, AGENT_MIRPUR, DIST_DHAKA, agent_id, bearer
from tests.test_llm_api import (  # noqa: F401
    FakeProvider,
    _logs,
    _narrate,
    echo,
    live,
    llm_env,
    scored,
)

API = "/api/v1"
DIGIT = re.compile(r"[0-9০-৯]")


def _no_live_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(providers, "build", lambda mode, settings: pytest.fail("live call"))


def _chat(client: TestClient, h: dict[str, str], message: str, lang: str) -> dict[str, Any]:
    AppStatus.should_exit_event = None
    res = client.post(f"{API}/copilot/chat", headers=h, json={"message": message, "lang": lang})
    assert res.status_code == 200, res.text
    last = res.text.strip().split("event: done")[-1]
    data = next(line[5:].strip() for line in last.splitlines() if line.startswith("data:"))
    answer: dict[str, Any] = json.loads(data)["answer"]
    return answer


def _settings(path: Path, **over: Any) -> Settings:
    """Settings as a deployment would set them (the replay file is the `llm_env` path)."""
    return get_settings().model_copy(update={"llm_replay_file": path, **over})


# --- mode helpers -------------------------------------------------------------------------------

def test_replay_runs_on_the_fixed_clock_only(llm_env: Path) -> None:
    llm_env.write_text("{}", encoding="utf-8")
    fixed = _settings(llm_env, clock_mode="fixed", llm_provider="auto")
    assert resolve_mode(fixed) == "replay" and not replay_skipped(fixed)
    on_live = fixed.model_copy(update={"clock_mode": "live"})
    assert resolve_mode(on_live) == "template" and replay_skipped(on_live)
    explicit = on_live.model_copy(update={"llm_provider": "replay"})
    assert resolve_mode(explicit) == "replay" and not replay_skipped(explicit)


def test_no_api_key_means_template_only_when_a_key_is_missing(llm_env: Path) -> None:
    base = _settings(llm_env, llm_provider="auto")
    assert no_api_key(base) is True
    assert no_api_key(base.model_copy(update={"llm_provider": "template"})) is False
    keyed = base.model_copy(update={"llm_api_key": SecretStr("test-key-not-real")})
    assert no_api_key(keyed) is False and resolve_mode(keyed) == "anthropic"


# --- every surface, no key ----------------------------------------------------------------------

@pytest.mark.parametrize("lang", ["en", "bn"])
def test_no_key_label_on_agent_surfaces(client: TestClient, scored: Path,
                                        monkeypatch: pytest.MonkeyPatch, lang: str) -> None:
    _no_live_call(monkeypatch)
    h = bearer(client, AGENT_MIRPUR)
    own = f"{API}/agents/{agent_id('AGT-0001')}/briefing"
    chat_q = "When will my cash run out?" if lang == "en" else "আমার ক্যাশ কখন শেষ হবে?"
    surfaces = {
        "narrate": _narrate(client, h, lang),
        "briefing": client.get(own, params={"lang": lang}, headers=h).json(),
        "copilot": _chat(client, h, chat_q, lang),
    }
    for name, body in surfaces.items():
        assert (body["generated_by"], body["provider"]) == ("template", "template"), name
        assert body["no_api_key"] is True and body["fallback_reason"] is None, name
        assert body["text"] == body["template_text"], name
    assert {r.generated_by.value for r in _logs()} == {"template"}


@pytest.mark.parametrize("lang", ["en", "bn"])
def test_no_key_label_on_distributor_briefing(client: TestClient, scored: Path,
                                              monkeypatch: pytest.MonkeyPatch, lang: str) -> None:
    _no_live_call(monkeypatch)
    res = client.get(f"{API}/distributor/briefing", params={"lang": lang},
                     headers=bearer(client, DIST_DHAKA))
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["generated_by"], body["no_api_key"]) == ("template", True)


@pytest.mark.usefixtures("flagged")
def test_no_key_label_on_anomaly_narrative(client: TestClient, llm_env: Path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    _no_live_call(monkeypatch)
    h = bearer(client, ADMIN)
    flag = client.get(f"{API}/anomalies", headers=h).json()["items"][0]
    for lang in ("en", "bn"):
        body = client.get(f"{API}/anomalies/{flag['id']}/narrative", params={"lang": lang},
                          headers=h).json()
        assert (body["generated_by"], body["no_api_key"]) == ("template", True)


def test_status_says_no_key_and_why_replay_is_skipped(client: TestClient, scored: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    h = bearer(client, ADMIN)
    status = client.get(f"{API}/llm/status", headers=h).json()
    assert (status["key_configured"], status["no_api_key"]) == (False, True)
    assert status["replay_skipped"] is None  # no recorded file at all
    scored.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("CLOCK_MODE", "live")
    get_settings.cache_clear()
    status = client.get(f"{API}/llm/status", headers=h).json()
    assert (status["mode"], status["replay_skipped"]) == ("template", "live_clock")
    monkeypatch.setenv("CLOCK_MODE", "fixed")
    get_settings.cache_clear()
    status = client.get(f"{API}/llm/status", headers=h).json()
    assert (status["mode"], status["replay_skipped"]) == ("replay", None)


def test_recorded_wording_is_skipped_on_the_live_clock(client: TestClient, scored: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    h = bearer(client, AGENT_MIRPUR)
    first = _narrate(client, h, "en")
    scored.write_text(json.dumps({first["evidence_hash"]: {
        "intent": "narrate", "lang": "en", "model": "recorded-model", "cited_factors": [],
        "text": "Recorded wording. " + first["template_text"]}}), encoding="utf-8")
    _no_live_call(monkeypatch)
    assert _narrate(client, h, "en")["generated_by"] == "replay"  # fixed clock: used
    monkeypatch.setenv("CLOCK_MODE", "live")
    get_settings.cache_clear()
    body = _narrate(client, h, "en")  # same evidence, live clock: skipped by design
    assert (body["generated_by"], body["no_api_key"]) == ("template", True)


# --- with a key ---------------------------------------------------------------------------------

def test_with_key_wording_is_not_labelled_no_key(client: TestClient, scored: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    live(monkeypatch, FakeProvider(echo))
    h = bearer(client, AGENT_MIRPUR)
    assert _narrate(client, h, "en")["no_api_key"] is False
    own = f"{API}/agents/{agent_id('AGT-0001')}/briefing"
    body = client.get(own, headers=h).json()
    assert (body["generated_by"], body["no_api_key"]) == ("llm", False)
    assert _chat(client, h, "When will my cash run out?", "en")["no_api_key"] is False
    assert client.get(f"{API}/llm/status", headers=h).json()["no_api_key"] is False


def test_failed_live_call_is_template_but_not_no_key(client: TestClient, scored: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    live(monkeypatch, FakeProvider(ProviderError("boom")))
    body = _narrate(client, bearer(client, AGENT_MIRPUR), "en")
    assert (body["generated_by"], body["fallback_reason"]) == ("template", "error")
    assert body["no_api_key"] is False


def test_template_provider_by_choice_is_not_labelled_no_key(client: TestClient, scored: Path,
                                                            monkeypatch: pytest.MonkeyPatch
                                                            ) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "template")
    get_settings.cache_clear()
    _no_live_call(monkeypatch)
    body = _narrate(client, bearer(client, AGENT_MIRPUR), "en")
    assert (body["generated_by"], body["no_api_key"]) == ("template", False)


def test_copilot_refusal_is_not_a_missing_key_notice(client: TestClient, scored: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    _no_live_call(monkeypatch)
    body = _chat(client, bearer(client, AGENT_MIRPUR), "Write a poem about cricket", "en")
    assert (body["generated_by"], body["no_api_key"]) == ("template", False)


# --- template wording ---------------------------------------------------------------------------

def _briefing_pack(red: int, swaps: int, flags: int) -> Pack:
    top = [{"code": "AGT-0001", "district": "Dhaka", "level": "red", "probability": 0.8,
            "worst_float": "cash", "hours_to_stockout": 3.5}] if red else []
    return Pack(LlmIntent.distributor_briefing, {
        "horizon_h": 24, "agents_total": 10, "levels": {"red": red, "amber": 2, "green": 8 - red},
        "top": top, "swaps_pending": swaps, "anomalies_open": flags, "factors": []}, None)


@pytest.mark.parametrize("lang", [Lang.en, Lang.bn])
def test_distributor_template_gives_an_ordered_next_step(lang: Lang) -> None:
    steps = templates.NEXT_STEP[lang]
    for red, swaps, flags, key in ((2, 0, 0, "red"), (0, 1, 0, "queues"), (0, 0, 3, "queues"),
                                   (0, 0, 0, "calm")):
        pack = _briefing_pack(red, swaps, flags)
        text = templates.render(pack, lang).text
        assert steps[key] in text and text.endswith(templates.NOTICE[lang])
        guard.check_numbers(text, numbers.allowed_from(pack.data))  # no number added


@pytest.mark.parametrize("lang", [Lang.en, Lang.bn])
def test_added_sentences_carry_no_numbers(lang: Lang) -> None:
    added = [*templates.NEXT_STEP[lang].values(), *templates.NO_ACTION[lang].values(),
             templates.ANOMALY_NEXT[lang]]
    assert added and not any(DIGIT.search(s) for s in added)


@pytest.mark.parametrize("lang", [Lang.en, Lang.bn])
def test_agent_briefing_without_action_says_what_to_do(lang: Lang) -> None:
    floats = [{"float_type": "cash", "demand_type": "cash_out", "balance_bdt": 90000,
               "level_24h": "green", "probability_24h": 0.05, "hours_to_stockout": None,
               "stockout_time": None, "stockout_day": None, "confidence": 0.8,
               "top_driver": None}]
    data = {"agent": {"code": "AGT-0001", "district": "Dhaka"}, "level": "green",
            "floats": floats, "actions": [], "factors": []}
    green = templates.render(Pack(LlmIntent.agent_briefing, data, None), lang).text
    assert green.endswith(templates.NO_ACTION[lang][True])
    amber = templates.render(Pack(LlmIntent.agent_briefing, {**data, "level": "amber"}, None),
                             lang).text
    assert amber.endswith(templates.NO_ACTION[lang][False])

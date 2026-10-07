"""LLM endpoints with mocked providers: fallback on timeout, numbers guard + regeneration, cache,
per-user rate limit, global daily cap, replay with no key, role scoping, llm_call_log."""

import json
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_engine
from app.llm import providers
from app.llm.limits import user_limiter
from app.llm.providers import Completion, ProviderError, ProviderTimeout
from app.models import LlmCallLog
from tests.auth_helpers import ADMIN, AGENT_MIRPUR, DIST_DHAKA, agent_id, bearer
from tests.conftest import N_TRAINED_AGENTS, use_template

API = "/api/v1"
DRAFT = re.compile(r"<draft>\n(.*)\n</draft>", re.DOTALL)
Reply = Callable[[str, str], str]


class FakeProvider:
    name = "anthropic"
    model = "fake-model"

    def __init__(self, *replies: Reply | Exception) -> None:
        self.replies = list(replies)
        self.calls = 0

    def complete(self, system: str, user: str, max_tokens: int) -> Completion:
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        if isinstance(reply, Exception):
            raise reply
        return Completion(text=reply(system, user), prompt_tokens=100, completion_tokens=40)


def _lang(system: str) -> str:
    return "bn" if '"lang": "bn"' in system else "en"


def echo(system: str, user: str) -> str:
    """A well-behaved model: rewrites nothing, so every number is the draft's."""
    found = DRAFT.search(user)
    assert found is not None
    return json.dumps({"text": found.group(1), "lang": _lang(system), "cited_factors": []},
                      ensure_ascii=False)


def invents(system: str, user: str) -> str:
    extra = " ৳৯৯,৯৯৯ বেশি লাগবে।" if _lang(system) == "bn" else " Expect BDT 99,999 more."
    body = json.loads(echo(system, user))
    return json.dumps({**body, "text": body["text"] + extra}, ensure_ascii=False)


@pytest.fixture
def llm_env(env: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """No key, and a replay file path that does not exist yet (template mode)."""
    replay = env / "demo_replay.json"
    monkeypatch.setenv("LLM_REPLAY_FILE", str(replay))
    get_settings.cache_clear()
    user_limiter.reset()
    yield replay
    user_limiter.reset()


@pytest.fixture
def scored(seeded: Path, trained: tuple[Path, Path], scored_template: Path, llm_env: Path,
           monkeypatch: pytest.MonkeyPatch) -> Path:
    """Trained DB + forecasts + risk cache (copy of the session template), as `ready` plus risk."""
    monkeypatch.setenv("ARTIFACTS_DIR", str(trained[1]))
    get_settings.cache_clear()
    use_template(seeded, scored_template)
    return llm_env


def live(monkeypatch: pytest.MonkeyPatch, fake: FakeProvider, **env: str) -> FakeProvider:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_API_KEY", "test-key-not-real")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    monkeypatch.setattr(providers, "build", lambda mode, settings: fake)
    return fake


def _narrate(client: TestClient, h: dict[str, str], lang: str = "en",
             target: str = "cash") -> dict[str, Any]:
    res = client.post(f"{API}/explanations/narrate", headers=h,
                      json={"agent_id": agent_id("AGT-0001"), "target": target, "lang": lang})
    assert res.status_code == 200, res.text
    body: dict[str, Any] = res.json()
    return body


def _logs() -> list[LlmCallLog]:
    with Session(get_engine()) as session:
        return list(session.scalars(select(LlmCallLog).order_by(LlmCallLog.id)))


def test_template_mode_without_key(client: TestClient, scored: Path) -> None:
    body = _narrate(client, bearer(client, AGENT_MIRPUR))
    assert body["generated_by"] == "template" and body["provider"] == "template"
    assert body["text"] == body["template_text"] and body["fallback_reason"] is None
    assert body["model_version"] and body["advisory"] is True and body["cited_factors"]
    assert [(r.provider, r.generated_by.value) for r in _logs()] == [("template", "template")]


def test_live_wording_is_cached(client: TestClient, scored: Path,
                                monkeypatch: pytest.MonkeyPatch) -> None:
    fake = live(monkeypatch, FakeProvider(echo))
    h = bearer(client, AGENT_MIRPUR)
    first = _narrate(client, h, "bn")
    assert (first["generated_by"], first["provider"], first["cached"]) == ("llm", "anthropic",
                                                                           False)
    again = _narrate(client, h, "bn")
    assert again["cached"] is True and again["text"] == first["text"] and fake.calls == 1
    assert again["evidence_hash"] == first["evidence_hash"]
    rows = _logs()
    assert [r.provider for r in rows] == ["anthropic", "cache"]
    assert rows[0].prompt_tokens == 100 and rows[0].latency_ms >= 0
    assert rows[0].guard_result.value == "pass" and rows[0].model == "fake-model"


def test_timeout_retries_once_then_template(client: TestClient, scored: Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    fake = live(monkeypatch, FakeProvider(ProviderTimeout("timeout")))
    body = _narrate(client, bearer(client, AGENT_MIRPUR))
    assert body["generated_by"] == "template" and body["fallback_reason"] == "timeout"
    assert body["guard_result"] == "timeout" and body["text"] == body["template_text"]
    assert fake.calls == 2
    assert [(r.provider, r.guard_result.value) for r in _logs()] == [
        ("anthropic", "timeout"), ("anthropic", "timeout"), ("template", "timeout")]


@pytest.mark.parametrize(("fault", "label"), [
    (ProviderError("connection refused"), "provider down"),
    (lambda system, user: "Sure! Here is the explanation you asked for.", "invalid JSON"),
    (RuntimeError("provider bug"), "unexpected error"),
])
def test_broken_provider_falls_back_to_the_template(client: TestClient, scored: Path,
                                                   monkeypatch: pytest.MonkeyPatch,
                                                   fault: Reply | Exception, label: str) -> None:
    """The page always gets its wording, labelled as the template, never an error."""
    live(monkeypatch, FakeProvider(fault))
    body = _narrate(client, bearer(client, AGENT_MIRPUR))
    assert body["generated_by"] == "template", label
    assert body["text"] == body["template_text"] and body["fallback_reason"] is not None
    assert _logs()[-1].generated_by.value == "template"


def test_timeout_then_success(client: TestClient, scored: Path,
                              monkeypatch: pytest.MonkeyPatch) -> None:
    fake = live(monkeypatch, FakeProvider(ProviderTimeout("timeout"), echo))
    body = _narrate(client, bearer(client, AGENT_MIRPUR))
    assert body["generated_by"] == "llm" and fake.calls == 2


@pytest.mark.parametrize("lang", ["bn", "en"])
def test_numbers_guard_regenerates_then_template(client: TestClient, scored: Path,
                                                 monkeypatch: pytest.MonkeyPatch,
                                                 lang: str) -> None:
    fake = live(monkeypatch, FakeProvider(invents))
    body = _narrate(client, bearer(client, AGENT_MIRPUR), lang)
    assert body["generated_by"] == "template" and body["fallback_reason"] == "numbers_fail"
    assert body["text"] == body["template_text"] and fake.calls == 2
    assert all("99999" in (r.error or "") for r in _logs()[:2])


def test_numbers_guard_regeneration_succeeds(client: TestClient, scored: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    fake = live(monkeypatch, FakeProvider(invents, echo))
    body = _narrate(client, bearer(client, AGENT_MIRPUR), "bn")
    assert body["generated_by"] == "llm" and fake.calls == 2


def test_daily_cap_is_global(client: TestClient, scored: Path,
                             monkeypatch: pytest.MonkeyPatch) -> None:
    fake = live(monkeypatch, FakeProvider(ProviderTimeout("timeout")),
                LLM_DAILY_CALL_CAP="2")
    assert _narrate(client, bearer(client, AGENT_MIRPUR))["fallback_reason"] == "timeout"
    other = _narrate(client, bearer(client, ADMIN), "bn")  # another user, no cache hit
    assert other["fallback_reason"] == "daily_cap" and other["generated_by"] == "template"
    assert fake.calls == 2
    status = client.get(f"{API}/llm/status", headers=bearer(client, ADMIN)).json()
    assert (status["calls_today"], status["daily_cap"]) == (2, 2)
    assert status["mode"] == "anthropic" and status["live"] is True


def test_user_rate_limit(client: TestClient, scored: Path,
                         monkeypatch: pytest.MonkeyPatch) -> None:
    fake = live(monkeypatch, FakeProvider(echo), LLM_USER_CALLS_PER_MIN="1")
    h = bearer(client, AGENT_MIRPUR)
    assert _narrate(client, h, "en")["generated_by"] == "llm"
    limited = _narrate(client, h, "bn")
    assert limited["fallback_reason"] == "rate_limited" and fake.calls == 1
    assert _narrate(client, bearer(client, ADMIN), "bn")["generated_by"] == "llm"


def test_replay_mode_without_key(client: TestClient, scored: Path,
                                 monkeypatch: pytest.MonkeyPatch) -> None:
    h = bearer(client, AGENT_MIRPUR)
    first = _narrate(client, h, "en")  # template mode: no key, no replay file
    scored.write_text(json.dumps({first["evidence_hash"]: {
        "intent": "narrate", "lang": "en", "model": "recorded-model", "cited_factors": [],
        "text": "Recorded wording. " + first["template_text"]}}), encoding="utf-8")
    monkeypatch.setattr(providers, "build", lambda mode, settings: pytest.fail("no live call"))
    body = _narrate(client, h, "en")
    assert (body["generated_by"], body["provider"], body["model"]) == (
        "replay", "replay", "recorded-model")
    assert body["text"].startswith("Recorded wording.")
    miss = _narrate(client, h, "en", target="emoney")
    assert miss["generated_by"] == "template" and miss["fallback_reason"] == "replay_miss"
    status = client.get(f"{API}/llm/status", headers=h).json()
    assert (status["mode"], status["replay_entries"], status["key_configured"]) == (
        "replay", 1, False)
    assert status["last_error"] == "replay_miss"


def test_replay_entry_with_invented_numbers_is_rejected(client: TestClient, scored: Path) -> None:
    h = bearer(client, AGENT_MIRPUR)
    first = _narrate(client, h, "en")
    scored.write_text(json.dumps({first["evidence_hash"]: {
        "lang": "en", "text": "Expect BDT 99,999 more."}}), encoding="utf-8")
    assert _narrate(client, h, "en")["generated_by"] == "template"


def test_agent_briefing_and_scoping(client: TestClient, scored: Path) -> None:
    own, other = (f"{API}/agents/{agent_id(c)}/briefing" for c in ("AGT-0001", "AGT-0002"))
    assert client.get(own).status_code == 401
    h = bearer(client, AGENT_MIRPUR)
    for lang, mark in (("en", "AGT-0001"), ("bn", "ঝুঁকি")):
        res = client.get(own, params={"lang": lang}, headers=h)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["intent"] == "agent_briefing" and mark in body["text"]
        assert body["model_version"] and body["generated_at"]
    assert client.get(other, headers=h).status_code == 403
    assert client.get(other, headers=bearer(client, DIST_DHAKA)).status_code == 403
    res = client.post(f"{API}/explanations/narrate", headers=h,
                      json={"agent_id": agent_id("AGT-0002")})
    assert res.status_code == 403


def test_distributor_briefing(client: TestClient, scored: Path) -> None:
    url = f"{API}/distributor/briefing"
    res = client.get(url, params={"lang": "en"}, headers=bearer(client, DIST_DHAKA))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["intent"] == "distributor_briefing" and "agents" in body["text"]
    assert "approve" in body["text"]  # human-approval notice
    assert client.get(url, headers=bearer(client, AGENT_MIRPUR)).status_code == 403
    every = client.get(url, params={"lang": "en"}, headers=bearer(client, ADMIN)).json()
    assert f"across {N_TRAINED_AGENTS} agents" in every["text"]


def test_not_ready_without_caches(client: TestClient, seeded: Path, llm_env: Path) -> None:
    h = bearer(client, ADMIN)
    assert client.get(f"{API}/distributor/briefing", headers=h).status_code == 503
    assert client.get(f"{API}/anomalies/1/narrative", headers=h).status_code == 503
    res = client.post(f"{API}/explanations/narrate", headers=h,
                      json={"agent_id": agent_id("AGT-0001")})
    assert res.status_code == 503
    status = client.get(f"{API}/llm/status", headers=h).json()
    assert status["mode"] == "template" and status["calls_today"] == 0
    assert client.get(f"{API}/llm/status").status_code == 401


@pytest.mark.usefixtures("flagged")
def test_anomaly_narrative(client: TestClient, llm_env: Path) -> None:
    h = bearer(client, ADMIN)
    flags = client.get(f"{API}/anomalies", headers=h).json()["items"]
    assert flags
    url = f"{API}/anomalies/{flags[0]['id']}/narrative"
    res = client.get(url, params={"lang": "en"}, headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["intent"] == "anomaly_narrative" and flags[0]["agent"]["code"] in body["text"]
    assert "not a finding" in body["text"]
    assert body["cited_factors"] == [r["feature"] for r in flags[0]["reasons"]]
    assert client.get(url, headers=bearer(client, AGENT_MIRPUR)).status_code == 403
    assert client.get(f"{API}/anomalies/999999/narrative", headers=h).status_code == 404

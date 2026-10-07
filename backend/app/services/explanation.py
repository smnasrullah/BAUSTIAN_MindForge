"""Forecast explanations: TreeSHAP drivers written with the forecast cache; template reasons."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.models import Agent, Event, ForecastExplanation, ModelVersion
from app.models.enums import FLOAT_DEMAND, FloatType, Lang
from app.schemas.explanation import AgentExplanation, Reason
from app.services.evidence import evidence_pack
from app.services.model_registry import active_model
from ml.explain import drivers as drv
from ml.explain.factors import EXPLAIN_WINDOW_H, window_shap
from ml.explain.facts import event_facts, merge, numeric_facts
from ml.explain.templates import sentence
from ml.features.panel import Panel
from ml.inference.forecaster import Forecaster
from ml.registry import FORECAST_MODEL


def _utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)


def window_events(session: Session, start: datetime, end: datetime) -> list[Event]:
    return list(session.scalars(select(Event).where(Event.starts_at < end, Event.ends_at > start)))


def write_cache(session: Session, mv: ModelVersion, forecaster: Forecaster, panel: Panel,
                origin: int, now: datetime, generated_at: datetime, num_threads: int = 1) -> int:
    """Replace every explanation row with the drivers at `origin` (= now). Returns rows."""
    events = window_events(session, now, now + timedelta(hours=EXPLAIN_WINDOW_H))
    by_district = {d: event_facts(events, d, now) for d in panel.districts}
    rows: list[dict[str, Any]] = []
    for float_type, demand in FLOAT_DEMAND.items():
        shap = window_shap(forecaster, panel, demand.value, origin, EXPLAIN_WINDOW_H, num_threads)
        numeric = numeric_facts(panel, demand.value, origin, EXPLAIN_WINDOW_H)
        for i, agent_id in enumerate(panel.agent_ids.tolist()):
            facts = merge(numeric[i], by_district[panel.districts[panel.district[i]]])
            rows.append({
                "model_version_id": mv.id, "agent_id": agent_id, "float_type": float_type,
                "ts": now, "window_h": EXPLAIN_WINDOW_H,
                "usual_bdt": round(float(shap.usual[i]), 2),
                "drivers": [d.as_json() for d in drv.rank(shap.impacts[i], facts)],
                "generated_at": generated_at,
            })
    session.execute(delete(ForecastExplanation))
    if rows:
        session.execute(insert(ForecastExplanation), rows)
    return len(rows)


def load(session: Session, agent_id: int, float_type: FloatType
         ) -> tuple[ModelVersion, ForecastExplanation] | None:
    mv = active_model(session, FORECAST_MODEL)
    if mv is None:
        return None
    row = session.scalar(select(ForecastExplanation).where(
        ForecastExplanation.agent_id == agent_id, ForecastExplanation.float_type == float_type,
        ForecastExplanation.model_version_id == mv.id))
    return None if row is None else (mv, row)


def reasons(row: ForecastExplanation, lang: Lang) -> list[Reason]:
    demand = FLOAT_DEMAND[row.float_type].value
    return [Reason(factor=d.factor, impact=d.impact_bdt, direction="up" if d.impact_bdt > 0
                   else "down", share=d.share,
                   sentence=sentence(d.factor, d.impact_bdt, d.facts, demand, lang, row.window_h))
            for d in drv.top([drv.Driver.from_json(x) for x in row.drivers])]


def agent_explanation(session: Session, agent: Agent, float_type: FloatType, lang: Lang
                      ) -> AgentExplanation | None:
    if (hit := load(session, agent.id, float_type)) is None:
        return None
    mv, row = hit
    return AgentExplanation(
        agent_id=agent.id, target=float_type, demand_type=FLOAT_DEMAND[float_type], lang=lang,
        as_of=_utc(row.ts), window_hours=row.window_h, model_version=mv.version,
        generated_at=_utc(row.generated_at), usual_bdt=float(row.usual_bdt),
        reasons=reasons(row, lang), evidence=evidence_pack(session, agent, mv, row),
    )

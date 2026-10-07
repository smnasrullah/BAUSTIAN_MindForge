"""Model card (F12): the active models, their held-out metrics, data, intended use and limits."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Agent, Distributor, ModelVersion, SystemMeta
from app.models.enums import Lang
from app.schemas.responsible_ai import DataInfo, ModelCard, ModelInfo
from app.services import fairness
from app.services import model_card_text as text
from app.services.model_registry import active_model
from ml.registry import ANOMALY_MODEL, FORECAST_MODEL, HELPER_MODEL

FORECAST_KEYS = ("mae_bdt", "mae_baseline_bdt", "mae_skill", "coverage_q10_q90",
                 "coverage_q10_q90_raw")
ANOMALY_KEYS = ("precision", "recall", "agent_precision", "agent_recall")
HELPER_GROUPS = ("blind", "sim_rule_score", "sim_learned_order")
HELPER_KEYS = ("auc", "brier", "ece", "acceptance_rate", "covered_rate")


def _utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts


def _when(value: Any) -> datetime | None:
    return _utc(datetime.fromisoformat(value)) if isinstance(value, str) else None


def _numbers(metrics: dict[str, Any], groups: tuple[str, ...], keys: tuple[str, ...]
             ) -> dict[str, float]:
    """Flat `group.key` -> value for the headline held-out metrics."""
    out: dict[str, float] = {}
    for g in groups:
        part = metrics.get(g)
        if isinstance(part, dict):
            out |= {f"{g}.{k}": float(part[k]) for k in keys
                    if isinstance(part.get(k), int | float)}
    return out


def _info(mv: ModelVersion, kind: text.Text, purpose: text.Text, metrics: dict[str, float],
          lang: Lang) -> ModelInfo:
    return ModelInfo(name=mv.model_name, version=mv.version, kind=kind[lang],
                     purpose=purpose[lang], trained_at=_utc(mv.trained_at), metrics=metrics)


def _meta(session: Session, key: str) -> Any:
    row = session.get(SystemMeta, key)
    return row.value if row else None


def model_card(session: Session, lang: Lang) -> ModelCard | None:
    mv = active_model(session, FORECAST_MODEL)
    if mv is None:
        return None
    models = [_info(mv, text.FORECAST_KIND, text.FORECAST_PURPOSE,
                    _numbers(mv.metrics, ("cash_out", "cash_in"), FORECAST_KEYS), lang)]
    anomaly = active_model(session, ANOMALY_MODEL)
    if anomaly is not None:
        models.append(_info(anomaly, text.ANOMALY_KIND, text.ANOMALY_PURPOSE,
                            _numbers(anomaly.metrics, ("holdout",), ANOMALY_KEYS), lang))
    helper = active_model(session, HELPER_MODEL)
    if helper is not None:
        models.append(_info(helper, text.HELPER_KIND, text.HELPER_PURPOSE,
                            _numbers(helper.metrics, HELPER_GROUPS, HELPER_KEYS), lang))
    span = _meta(session, "data_range") or {}
    seed, version = _meta(session, "seed"), _meta(session, "data_version")
    data = DataInfo(
        source=text.SOURCE[lang], seed=seed if isinstance(seed, int) else None,
        data_version=version if isinstance(version, str) else None,
        start=_when(span.get("start")), end=_when(span.get("end")),
        holdout_start=_when(span.get("holdout_start")),
        n_agents=session.scalar(select(func.count()).select_from(Agent)) or 0,
        n_distributors=session.scalar(select(func.count()).select_from(Distributor)) or 0)
    return ModelCard(lang=lang, advisory_only=True, human_oversight=text.HUMAN_OVERSIGHT[lang],
                     models=models, data=data, intended_use=text.INTENDED_USE[lang],
                     out_of_scope=text.OUT_OF_SCOPE[lang], limitations=text.LIMITATIONS[lang],
                     fairness=fairness.gaps(session), model_version=mv.version,
                     generated_at=datetime.now(UTC))

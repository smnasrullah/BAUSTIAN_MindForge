"""model_versions rows for the committed artifacts (one active version per model name)."""

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import ModelVersion
from ml.inference import helper_accept
from ml.inference.forecaster import ArtifactError
from ml.registry import (
    ANOMALY_MANIFEST,
    ANOMALY_MODEL,
    FORECAST_MODEL,
    HELPER_MANIFEST,
    HELPER_MODEL,
    read_manifest,
    verify,
    verify_anomaly,
)


def _digest(manifest: dict[str, Any]) -> str:
    files: dict[str, str] = manifest["files"]
    return hashlib.sha256("".join(files[k] for k in sorted(files)).encode()).hexdigest()


def _find(session: Session, model_name: str, version: str) -> ModelVersion | None:
    return session.scalar(select(ModelVersion).where(
        ModelVersion.model_name == model_name, ModelVersion.version == version))


def _activate(session: Session, model_name: str, manifest: dict[str, Any],
              metrics: dict[str, Any]) -> ModelVersion:
    """Upsert one manifest's model as the only active version of its name (idempotent)."""
    version = str(manifest["model_version"])
    row = _find(session, model_name, version)
    if row is None:
        row = ModelVersion(model_name=model_name, version=version)
        session.add(row)
    row.trained_at = datetime.fromisoformat(manifest["trained_at"])
    row.artifact_sha256 = _digest(manifest)
    row.metrics = metrics
    session.execute(update(ModelVersion).where(ModelVersion.model_name == model_name,
                                               ModelVersion.version != version)
                    .values(is_active=False))
    row.is_active = True
    session.flush()
    return row


def register_forecast_model(session: Session, artifacts_dir: Path) -> ModelVersion:
    """Upsert the manifest's forecast model as the active version (idempotent)."""
    ok, why = verify(artifacts_dir)
    manifest = read_manifest(artifacts_dir)
    if not ok or manifest is None:
        raise ArtifactError(f"forecast artifacts invalid: {why}")
    return _activate(session, FORECAST_MODEL, manifest, manifest["forecast"]["holdout_metrics"])


def register_anomaly_model(session: Session, artifacts_dir: Path) -> ModelVersion:
    """Upsert the anomaly detector as the active version; metrics = precision/recall."""
    ok, why = verify_anomaly(artifacts_dir)
    manifest = read_manifest(artifacts_dir, ANOMALY_MANIFEST)
    if not ok or manifest is None:
        raise ArtifactError(f"anomaly artifacts invalid: {why}")
    return _activate(session, ANOMALY_MODEL, manifest, manifest["anomaly"]["metrics"])


def register_helper_model(session: Session, artifacts_dir: Path) -> ModelVersion | None:
    """Upsert the helper acceptance model (simulated behaviour only) when its artifact is
    present and intact; metrics = blind calibration + the policy simulation summary."""
    manifest = read_manifest(artifacts_dir, HELPER_MANIFEST)
    if manifest is None or helper_accept.load(artifacts_dir) is None:
        return None
    h = manifest["helper"]
    metrics: dict[str, Any] = {"blind": {k: h["metrics"]["blind"][k]
                                         for k in ("auc", "brier", "ece", "yes_rate")}}
    for name, sim in h["policy_simulation"].items():
        metrics[f"sim_{name}"] = {k: sim[k] for k in ("acceptance_rate", "covered_rate",
                                                     "asks_per_request") if k in sim}
    return _activate(session, HELPER_MODEL, manifest, metrics)


def register_candidate(session: Session, model_name: str, manifest: dict[str, Any],
                       metrics: dict[str, Any]) -> tuple[ModelVersion, bool]:
    """Record a retrained model as an inactive version; serving keeps the active one.

    Returns (row, reproduced): the same seed and data give the same version string, so a
    retrain that matches an existing version is a reproducibility check, not a new row.
    """
    version = str(manifest["model_version"])
    row = _find(session, model_name, version)
    if row is not None:
        return row, True
    row = ModelVersion(model_name=model_name, version=version, is_active=False,
                       trained_at=datetime.fromisoformat(manifest["trained_at"]),
                       artifact_sha256=_digest(manifest), metrics=metrics)
    session.add(row)
    session.flush()
    return row, False


def active_model(session: Session, model_name: str) -> ModelVersion | None:
    return session.scalar(select(ModelVersion).where(
        ModelVersion.model_name == model_name, ModelVersion.is_active.is_(True)))

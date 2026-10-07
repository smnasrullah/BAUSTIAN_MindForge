"""Artifact manifest: names, sha256 and metrics of the committed model files."""

import hashlib
import json
from pathlib import Path
from typing import Any

from ml.features.build import FEATURES

MANIFEST = "manifest.json"
FORECAST_MODEL = "demand_forecast"
FORECAST_SEMVER = "1.1.0"  # 1.1: validation-period selection + conformal band calibration
QUANTILES: tuple[float, ...] = (0.1, 0.5, 0.9)
CONFORMAL_FILE = "forecast_conformal.json"  # q10-q90 offsets (ml/inference/conformal.py)
# Joint stockout copula per agent segment (ml/training/dependence.py), validation residuals.
DEPENDENCE_FILE = "stockout_dependence.json"
# Agent anomaly detector (F9): own manifest, so it never touches the forecast's hashes.
ANOMALY_MANIFEST = "anomaly_manifest.json"
ANOMALY_MODEL = "agent_anomaly"
ANOMALY_SEMVER = "1.0.0"
ANOMALY_FILE = "anomaly_iforest.joblib"
# Helper acceptance model (learning to match; simulated behaviour only): own manifest too.
HELPER_MANIFEST = "helper_manifest.json"
HELPER_MODEL = "helper_acceptance"
HELPER_SEMVER = "1.0.0"
HELPER_FILE = "helper_accept.json"


def forecast_file(target: str) -> str:
    return f"forecast_{target}.joblib"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_manifest(artifacts_dir: Path, name: str = MANIFEST) -> dict[str, Any] | None:
    try:
        data = json.loads((artifacts_dir / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _files_ok(artifacts_dir: Path, m: dict[str, Any]) -> tuple[bool, str]:
    for name, digest in m.get("files", {}).items():
        path = artifacts_dir / name
        if not path.is_file() or sha256_file(path) != digest:
            return False, f"hash mismatch: {name}"
    if not m.get("files"):
        return False, "no files listed"
    return True, "ok"


def verify(artifacts_dir: Path) -> tuple[bool, str]:
    """True when the manifest exists, every file hash matches and the feature list is current."""
    m = read_manifest(artifacts_dir)
    if m is None:
        return False, "manifest missing"
    if tuple(m.get("forecast", {}).get("features", ())) != FEATURES:
        return False, "feature list changed"
    return _files_ok(artifacts_dir, m)


def verify_anomaly(artifacts_dir: Path) -> tuple[bool, str]:
    # Imported here: the anomaly features use the refill rule, whose module imports this one.
    from ml.features.anomaly import MEASURES

    m = read_manifest(artifacts_dir, ANOMALY_MANIFEST)
    if m is None:
        return False, "anomaly manifest missing"
    features = tuple(m.get("anomaly", {}).get("features", ()))
    if not features or any(f not in MEASURES for f in features):
        return False, "anomaly feature list unknown"
    return _files_ok(artifacts_dir, m)

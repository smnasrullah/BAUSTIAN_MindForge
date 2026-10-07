"""Helper acceptance model (learning to match): P(an asked helper says yes).

LEARNED FROM SIMULATED BEHAVIOUR ONLY (ml/data_gen/helpers.py). It ranks and sizes waves INSIDE
the helper set the rules already allow (opt-in, radius, surplus, caps and cooldowns stay rules);
it never adds a helper, removes one, or decides anything about money. Logistic regression on
standardised features with a Platt recalibration fitted on the validation period; stored as
plain numbers (JSON), no pickled code.
"""

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ml.registry import HELPER_FILE, HELPER_MANIFEST, read_manifest, sha256_file

FEATURES = ("distance_km", "hour_busy", "hour_night", "asks_7d", "log_surplus_ratio",
            "tier", "reliability", "log_asked")


def hour_band(hod: int) -> str:
    """busy 10:00-17:59, edge 08:00-09:59 and 18:00-20:59, night otherwise (local time)."""
    if 10 <= hod < 18:
        return "busy"
    if 8 <= hod < 21:
        return "edge"
    return "night"


def feature_row(distance_km: float, hod: int, asks_7d: int, surplus: float, amount: float,
                tier: int, asked: int, accepted: int) -> list[float]:
    """What the system can see when it asks: distance, hour band, asks in the last 7 days, own
    surplus over the amount (log, >= 0), tier, smoothed past yes-rate, log(1 + times asked)."""
    band = hour_band(hod)
    return [distance_km, float(band == "busy"), float(band == "night"), float(asks_7d),
            math.log(max(surplus / max(amount, 1.0), 1.0)), float(tier),
            (accepted + 1) / (asked + 2), math.log1p(asked)]


@dataclass(frozen=True)
class AcceptModel:
    version: str
    features: tuple[str, ...]
    mean: np.ndarray
    scale: np.ndarray
    coef: np.ndarray
    intercept: float
    platt_a: float = 1.0
    platt_b: float = 0.0

    def logit(self, x: np.ndarray) -> np.ndarray:
        return ((x - self.mean) / self.scale) @ self.coef + self.intercept

    def predict(self, x: np.ndarray) -> np.ndarray:
        """(n, len(features)) -> calibrated P(yes)."""
        z = self.platt_a * self.logit(x) + self.platt_b
        return 1.0 / (1.0 + np.exp(-z))

    def to_json(self) -> dict[str, Any]:
        return {"features": list(self.features), "mean": self.mean.tolist(),
                "scale": self.scale.tolist(), "coef": self.coef.tolist(),
                "intercept": self.intercept, "platt_a": self.platt_a, "platt_b": self.platt_b}

    @classmethod
    def from_json(cls, version: str, blob: dict[str, Any]) -> "AcceptModel":
        return cls(version, tuple(blob["features"]), np.array(blob["mean"]),
                   np.array(blob["scale"]), np.array(blob["coef"]), float(blob["intercept"]),
                   float(blob["platt_a"]), float(blob["platt_b"]))


def load(artifacts_dir: Path) -> AcceptModel | None:
    """None when the artifact is missing or its hash does not match the manifest."""
    m = read_manifest(artifacts_dir, HELPER_MANIFEST)
    path = artifacts_dir / HELPER_FILE
    if m is None or not path.is_file() or m.get("files", {}).get(HELPER_FILE) != sha256_file(path):
        return None
    return AcceptModel.from_json(str(m["model_version"]),
                                 json.loads(path.read_text(encoding="utf-8")))


def at_least_one_yes(probs: list[float]) -> float:
    return 1.0 - math.prod(1.0 - p for p in probs)

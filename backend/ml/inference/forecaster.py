"""Quantile demand forecaster: low / expected / high per target for one origin."""

import json
from dataclasses import dataclass
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np

from ml.features.build import build, grid
from ml.features.panel import TARGETS, Panel
from ml.inference.conformal import Conformal
from ml.registry import (
    CONFORMAL_FILE,
    FORECAST_MODEL,
    QUANTILES,
    forecast_file,
    read_manifest,
    verify,
)


class ArtifactError(RuntimeError):
    pass


@dataclass
class Forecaster:
    model_name: str
    model_version: str
    boosters: dict[str, list[lgb.Booster]]  # target -> boosters in QUANTILES order
    conformal: Conformal | None = None  # q10-q90 band calibration (validation period)
    threads: int = 1  # LightGBM predict threads (serving: 1; offline training/backtests: more)

    @classmethod
    def load(cls, artifacts_dir: Path, calibrated: bool = True) -> "Forecaster":
        """calibrated: apply the conformal band offsets when the artifacts have them."""
        ok, why = verify(artifacts_dir)
        manifest = read_manifest(artifacts_dir)
        if not ok or manifest is None:
            raise ArtifactError(f"forecast artifacts invalid: {why}")
        boosters: dict[str, list[lgb.Booster]] = {}
        for target in TARGETS:
            blob: dict[str, str] = joblib.load(artifacts_dir / forecast_file(target))
            boosters[target] = [lgb.Booster(model_str=blob[str(q)]) for q in QUANTILES]
        conformal = None
        path = artifacts_dir / CONFORMAL_FILE
        if calibrated and CONFORMAL_FILE in manifest.get("files", {}) and path.is_file():
            conformal = Conformal.from_json(json.loads(path.read_text(encoding="utf-8")))
        return cls(FORECAST_MODEL, str(manifest["model_version"]), boosters, conformal)

    def raw_rows(self, panel: Panel, target: str, rows: np.ndarray, origins: np.ndarray,
                 horizons: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """((n, 3) BDT before calibration: clipped at 0 and sorted, scale (n,))."""
        x, scale = build(panel, target, rows, origins, horizons)
        z = np.column_stack([b.predict(x, num_threads=self.threads)
                             for b in self.boosters[target]])
        return np.sort(np.maximum(z, 0.0), axis=1) * scale[:, None], scale

    def predict_rows(self, panel: Panel, target: str, rows: np.ndarray, origins: np.ndarray,
                     horizons: np.ndarray) -> np.ndarray:
        """(n, 3) BDT [low, expected, high]: clipped at 0, low <= mid <= high, calibrated band
        when a conformal calibration is loaded."""
        pred, scale = self.raw_rows(panel, target, rows, origins, horizons)
        return self.band(panel, target, rows, horizons, pred, scale)

    def band(self, panel: Panel, target: str, rows: np.ndarray, horizons: np.ndarray,
             raw: np.ndarray, scale: np.ndarray) -> np.ndarray:
        """The served band for raw predictions: calibrated when a calibration is loaded."""
        if self.conformal is None:
            return raw
        region = None if panel.region is None else panel.region[rows]
        return self.conformal.apply(target, raw, scale, panel.tier[rows], panel.area[rows],
                                    horizons, region)

    def predict_origin(self, panel: Panel, origin: int, horizon: int) -> dict[str, np.ndarray]:
        """target -> (agents, horizon, 3) for every panel agent, horizons 1..horizon."""
        rows, origins, hs = grid(len(panel.agent_ids), origin, horizon)
        return {t: self.predict_rows(panel, t, rows, origins, hs).reshape(-1, horizon, 3)
                for t in TARGETS}

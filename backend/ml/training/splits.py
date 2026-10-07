"""Train / validation / blind-test split of the fixed timeline, by TARGET hour index t.

    train       t <  train_end             models are fitted here only
    validation  train_end <= t < val_end   hyper-parameters, thresholds, contamination and the
                                           conformal offsets are chosen here only
    blind test  val_end <= t < n_hours     the last 14 days; scored once, after every choice

Features may look back across a boundary (history before an origin is always known at that
origin); a target never does. Leakage tests: tests/test_ml_split.py.
"""

from dataclasses import dataclass

import numpy as np

from ml.data_gen.timeline import HOLDOUT_START, N_HOURS, VAL_START, hour_index


class LeakageError(AssertionError):
    pass


@dataclass(frozen=True)
class Split:
    train_end: int
    val_end: int
    n_hours: int

    def __post_init__(self) -> None:
        if not 0 < self.train_end < self.val_end < self.n_hours:
            raise ValueError("split must satisfy 0 < train_end < val_end < n_hours")

    def check_train(self, targets: np.ndarray) -> None:
        if len(targets) and int(targets.max()) >= self.train_end:
            raise LeakageError("a training target lies in the validation or test period")

    def check_validation(self, targets: np.ndarray) -> None:
        if len(targets) and (int(targets.min()) < self.train_end
                             or int(targets.max()) >= self.val_end):
            raise LeakageError("a selection target lies outside the validation period")

    def check_test(self, targets: np.ndarray) -> None:
        if len(targets) and int(targets.min()) < self.val_end:
            raise LeakageError("a test target lies before the blind test period")

    def as_dict(self) -> dict[str, int]:
        return {"train_end_h": self.train_end, "val_end_h": self.val_end,
                "n_hours": self.n_hours}


FIXED_SPLIT = Split(hour_index(VAL_START), hour_index(HOLDOUT_START), N_HOURS)

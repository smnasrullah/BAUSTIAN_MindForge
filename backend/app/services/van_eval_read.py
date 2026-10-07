"""The committed van routing evaluation (ml/van/van_v3_eval.json, synthetic data): policies A-D
over >= 5 seeds with intervals, and the sensitivity runs. Built offline by
`python -m ml.van.evaluate`; this only reads it."""

import json
import logging
from pathlib import Path

from pydantic import ValidationError

from app.core.config import BACKEND_DIR
from app.schemas.van_plan import VanEvalOut

EVAL_FILE = BACKEND_DIR / "ml" / "van" / "van_v3_eval.json"
log = logging.getLogger(__name__)


def load(path: Path | None = None) -> VanEvalOut | None:
    """None (logged) when the file is missing or does not match the schema."""
    path = path or EVAL_FILE
    try:
        return VanEvalOut.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        log.warning("van evaluation file missing: %s", path)
    except (ValueError, ValidationError) as exc:
        log.warning("van evaluation file unreadable: %s", type(exc).__name__)
    return None

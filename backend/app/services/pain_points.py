"""Liquidity pain-point discovery: FIELD interviews, LITERATURE and SIMULATED personas.

Reads plain files, no database. Field rows come only from data/field/interviews.csv; the
simulated personas are team hypotheses and are always labelled so. Nothing here is generated.
"""

import csv
import json
from pathlib import Path

import yaml

from app.core.config import BACKEND_DIR
from app.schemas.evidence import (
    IncidenceOut,
    IncidenceRowOut,
    LiteratureOut,
    PainPointOut,
    PainPointsOut,
    PersonaOut,
)

FIELD_DIRS = (Path("/data/field"), BACKEND_DIR.parent / "data" / "field")
INCIDENCE_FILE = BACKEND_DIR / "data" / "evidence" / "incidence_sensitivity.json"

# tag -> (label en, label bn, feature en, feature bn, route)
TAXONOMY: dict[str, tuple[str, str, str, str, str]] = {
    "cash_shortage": (
        "Cash runs out", "ক্যাশ শেষ হয়ে যায়",
        "Dual-float forecast and time-to-stockout", "ডুয়াল-ফ্লোট পূর্বাভাস ও স্টকআউটের সময়",
        "/agent/stockout"),
    "emoney_shortage": (
        "E-money runs out", "ই-মানি শেষ হয়ে যায়",
        "Risk at 6, 24 and 72 hours", "৬, ২৪ ও ৭২ ঘণ্টার ঝুঁকি", "/agent/stockout"),
    "excess_liquidity": (
        "Excess cash or e-money", "বাড়তি ক্যাশ বা ই-মানি",
        "Rebalance recommendation and swap matching", "রিব্যালেন্স সুপারিশ ও সোয়াপ ম্যাচিং",
        "/distributor/swaps"),
    "delayed_rebalancing": (
        "Delayed rebalancing", "রিব্যালেন্সে দেরি",
        "Rebalance recommendation and van route plan",
        "রিব্যালেন্স সুপারিশ ও ভ্যান রুট পরিকল্পনা", "/distributor/map"),
    "emergency_support": (
        "Emergency support", "জরুরি সহায়তা",
        "Liquidity help requests to nearby helpers",
        "কাছের সহায়কদের কাছে তারল্য সহায়তার অনুরোধ", "/distributor/map"),
    "demand_unpredictability": (
        "Unpredictable demand", "অনিশ্চিত চাহিদা",
        "Event-aware forecast and Why? explanation", "ইভেন্ট-সচেতন পূর্বাভাস ও কেন? ব্যাখ্যা",
        "/agent/stockout"),
    "trust_in_swaps": (
        "Trust in swapping float", "ফ্লোট বদলে আস্থা",
        "Human-approved swaps and Responsible AI panel",
        "মানুষের অনুমোদিত সোয়াপ ও দায়িত্বশীল এআই প্যানেল", "/distributor/swaps"),
}

LITERATURE: tuple[LiteratureOut, ...] = (
    LiteratureOut(
        source="MicroSave/Helix survey of 2,800 agents in Bangladesh",
        year_note="undated in the source, appears mid-2010s; verify the year",
        fact="Most agents have cash and e-float delivered by a runner employed by a distributor "
             "or aggregator.", tags=["delayed_rebalancing"]),
    LiteratureOut(
        source="MicroSave, Liquidity: solving agents' perennial problem",
        year_note="year not stated in our notes",
        fact="In Bangladesh and Pakistan liquidity is usually delivered by runners; float-level "
             "alerts and inter-agent transfers are discussed as ideas.",
        tags=["cash_shortage", "emoney_shortage", "delayed_rebalancing"]),
    LiteratureOut(
        source="Mondato, How best to keep afloat",
        year_note="three surveyed countries, not Bangladesh-specific",
        fact="Agents cited inability to predict demand as a significant factor in float "
             "management.", tags=["demand_unpredictability"]),
)


def field_dir() -> Path | None:
    return next((d for d in FIELD_DIRS if d.is_dir()), None)


def _field_tags(directory: Path | None) -> tuple[int, dict[str, int]]:
    path = None if directory is None else directory / "interviews.csv"
    if path is None or not path.is_file():
        return 0, {}
    counts: dict[str, int] = {}
    n = 0
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if not any((v or "").strip() for v in row.values()):
                continue
            n += 1
            tag = (row.get("top_pain_point_tag") or "").strip()
            if tag:
                counts[tag] = counts.get(tag, 0) + 1
    return n, counts


def _personas(directory: Path | None) -> list[PersonaOut]:
    path = None if directory is None else directory / "personas_simulated.yaml"
    if path is None or not path.is_file():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [PersonaOut(**p) for p in raw.get("personas", [])]


def _incidence(path: Path) -> IncidenceOut | None:
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = [IncidenceRowOut(
        buffer_factor=lv["buffer_factor"],
        baseline_stockout_hours=lv["baseline"]["stockout_hours"],
        baseline_share=lv["baseline"]["share_of_agent_hours"],
        ai_stockout_hours=lv["ai"]["stockout_hours"], ai_share=lv["ai"]["share_of_agent_hours"],
        hours_avoided=lv["stockout_hours_avoided"], percent_reduction=lv["percent_reduction"],
        value_saved_bdt=lv["value_saved_bdt"], van_trips_avoided=lv["van_trips_avoided"])
        for lv in raw["levels"]]
    return IncidenceOut(note=raw["purpose"], seed=raw["seed"], agents=raw["agents"],
                        date=raw["date"], rows=rows)


def build(directory: Path | None = None, incidence: Path = INCIDENCE_FILE) -> PainPointsOut:
    directory = directory if directory is not None else field_dir()
    n_field, field_counts = _field_tags(directory)
    personas = _personas(directory)
    points = [PainPointOut(
        tag=tag, label_en=en, label_bn=bn, field_count=field_counts.get(tag, 0),
        literature_count=sum(tag in lit.tags for lit in LITERATURE),
        simulated_count=sum(tag in p.tags for p in personas),
        feature_en=f_en, feature_bn=f_bn, feature_route=route)
        for tag, (en, bn, f_en, f_bn, route) in TAXONOMY.items()]
    points.sort(key=lambda p: (-p.field_count, -(p.literature_count + p.simulated_count), p.tag))
    return PainPointsOut(field_interviews_count=n_field, pain_points=points,
                         literature=list(LITERATURE), personas=personas,
                         incidence=_incidence(incidence))

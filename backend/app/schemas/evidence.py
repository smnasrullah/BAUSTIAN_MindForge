from typing import Literal

from pydantic import BaseModel


class PainPointOut(BaseModel):
    tag: str
    label_en: str
    label_bn: str
    field_count: int
    literature_count: int
    simulated_count: int
    feature_en: str
    feature_bn: str
    feature_route: str


class LiteratureOut(BaseModel):
    source: str
    year_note: str
    fact: str
    tags: list[str]


class PersonaOut(BaseModel):
    id: str
    title_en: str
    title_bn: str
    hypothesis_en: str
    hypothesis_bn: str
    tags: list[str]
    source_ref: str | None = None
    label: Literal["SIMULATED"] = "SIMULATED"


class IncidenceRowOut(BaseModel):
    buffer_factor: float
    baseline_stockout_hours: int
    baseline_share: float
    ai_stockout_hours: int
    ai_share: float
    hours_avoided: int
    percent_reduction: float | None
    value_saved_bdt: float
    van_trips_avoided: int


class IncidenceOut(BaseModel):
    note: str
    seed: int
    agents: int
    date: str
    rows: list[IncidenceRowOut]


class PainPointsOut(BaseModel):
    field_interviews_count: int
    pain_points: list[PainPointOut]
    literature: list[LiteratureOut]
    personas: list[PersonaOut]
    incidence: IncidenceOut | None

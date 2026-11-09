from __future__ import annotations
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field
STATES = Literal["alive", "critical", "departed", "insufficient_data"]
Number = Annotated[float, Field(allow_inf_nan=False)]

class OpenModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class Period(OpenModel):
    start: int
    end: int


class Source(OpenModel):
    name: str
    url: str
    model: str
    attribution: str
    description: str


class City(OpenModel):
    id: str
    name: str
    representative_point: dict
    grid: dict | None


class Culture(OpenModel):
    text: str
    source_name: str
    source_url: str


class Metric(OpenModel):
    key: Literal["temperature", "precipitation", "diurnal_range"]
    name: str
    unit: str
    baseline: Number | None
    recent: Number | None
    delta: Number | None
    baseline_std: Number | None
    scale: Number
    weight: Number
    baseline_n: Annotated[int, Field(ge=0, le=30)]
    recent_n: Annotated[int, Field(ge=0, le=30)]


class Annual(OpenModel):
    year: int
    start: str
    end: str
    valid: bool
    reason: str | None
    temperature: Number | None
    precipitation: Number | None
    diurnal_range: Number | None


class Term(OpenModel):
    id: str
    name: str
    season: Literal["春", "夏", "秋", "冬"]
    order: int
    status: STATES
    score: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)] | None
    score_display: str
    reason: str | None
    summary: str
    culture: Culture
    historical_portrait: str
    metrics: list[Metric]
    annual: list[Annual]
    sensitivity: dict


class Report(OpenModel):
    schema_version: Literal["1.0"]
    report_id: str
    is_demo: bool
    city: City
    data_status: Literal["demo", "ready"]
    baseline: Period
    recent: Period
    source: Source
    method_version: Literal["v0.1"]
    generated_at: str
    summary: str
    review_status: str
    quality: dict
    terms: Annotated[list[Term], Field(min_length=24, max_length=24)]



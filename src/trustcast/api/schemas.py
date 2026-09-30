"""API contract (Pydantic v2). Written before the implementation; the OpenAPI document served at
``/openapi.json`` is generated from these models. Every response carries the disclaimer.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

from trustcast import DISCLAIMER, __version__

Variable = Literal["precip", "tmax"]


class Envelope(BaseModel):
    """Fields present in every response."""

    disclaimer: str = DISCLAIMER
    generated_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))
    api_version: str = __version__


class Health(Envelope):
    status: Literal["ok", "degraded"]
    products: dict[str, str | None]  # "<region>/<variable>" -> latest init (ISO) or None
    notes: list[str] = []


class SourceStatus(BaseModel):
    source: str
    label: str
    kind: Literal["nwp", "ai", "ens"]
    adapters: list[str]
    status: Literal["ok", "stale", "failed", "not_configured", "unknown"]
    detail: str = ""
    last_archived_init: str | None = None
    eval_first_init: str | None = None
    eval_last_init: str | None = None
    licence: str = ""


class Sources(Envelope):
    sources: list[SourceStatus]


class LeadValue(BaseModel):
    lead_day: int
    valid_day: dt.date
    value: float | None
    lo90: float | None = None
    hi90: float | None = None
    prob: dict[str, float | None] = {}  # threshold (str) -> probability
    sources: dict[str, float | None] = {}  # raw source values
    weights: dict[str, float] = {}
    regime: str | None = None
    defer: bool = False


class PointForecast(Envelope):
    region: str
    variable: Variable
    units: str
    init_time: dt.datetime
    lat: float
    lon: float
    cell_lat: float
    cell_lon: float
    leads: list[LeadValue]


class GridLayer(Envelope):
    region: str
    variable: Variable
    layer: str
    units: str
    init_time: dt.datetime
    lead_day: int
    valid_day: dt.date
    lats: list[float]
    lons: list[float]
    values: list[list[float | None]]
    vmin: float | None = None
    vmax: float | None = None
    available_layers: list[str] = []


class SkillCell(BaseModel):
    lat: float
    lon: float
    best_source: str | None
    dmse: dict[str, float | None]


class SkillMap(Envelope):
    region: str
    variable: Variable
    lead_day: int
    init_time: dt.datetime
    half_life_days: float
    cells: list[SkillCell]


class LeaderboardRow(BaseModel):
    source: str
    kind: str
    lead_day: int
    rmse: float | None
    rmse_lo: float | None
    rmse_hi: float | None
    crps: float | None = None
    ets_heavy: float | None = None
    n_cases: int | None = None
    recent_rmse: float | None = None


class Leaderboard(Envelope):
    region: str
    variable: Variable
    sample: str
    period: str
    rows: list[LeaderboardRow]


class VerificationSummary(Envelope):
    phases: dict[str, dict]
    scoreboard_generated: str | None
    notes: list[str]


class DistrictAlert(BaseModel):
    district_id: str
    district: str
    state: str
    lead_day: int
    valid_day: dt.date
    level: Literal["none", "yellow", "orange", "red"]
    event: str
    probability: float | None
    value: float | None
    defer: bool
    coverage: float


class Alerts(Envelope):
    region: str
    variable: Variable
    init_time: dt.datetime
    rule: str
    alerts: list[DistrictAlert]


class Explanation(Envelope):
    district_id: str
    district: str
    state: str
    variable: Variable
    init_time: dt.datetime
    lead_day: int
    valid_day: dt.date
    value: float | None
    lo90: float | None
    hi90: float | None
    probabilities: dict[str, float | None]
    weights: dict[str, float]
    top_features: list[tuple[str, float]]
    regime: str | None
    defer: bool
    sentence: str
    method: str


class Bulletin(Envelope):
    district_id: str
    language: Literal["en", "hi"]
    init_time: dt.datetime
    text: str
    numbers: dict[str, float]
    validated: bool
    validation_errors: list[str] = []


class ReplaySeries(BaseModel):
    forecast: str
    lead_day: int
    values: dict[str, float | None]  # valid_day ISO -> value


class Replay(Envelope):
    event_id: str
    title: str
    region: str
    variable: Variable
    district_id: str
    focus_day: dt.date
    observed: dict[str, float | None]
    series: list[ReplaySeries]
    notes: list[str] = []


class OverrideIn(BaseModel):
    district_id: str
    variable: Variable
    valid_day: dt.date
    value: float | None = None
    distrust_sources: list[str] = []
    reason: str = Field(min_length=5, max_length=1000)
    author: str = Field(min_length=1, max_length=100)


class OverrideOut(Envelope):
    id: int
    stored: OverrideIn
    effect: str

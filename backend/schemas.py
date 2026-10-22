from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ClinicalContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spreading_redness: bool = False
    pus: bool = False
    fever: bool = False
    severe_pain: bool = False
    rapid_worsening: bool = False
    deep_or_gaping_wound: bool = False
    bite_or_puncture: bool = False
    diabetic: bool = False
    immunocompromised: bool = False
    no_improvement_after_days: int = Field(default=0, ge=0, le=3650)
    sustained_abnormal_trend: bool = False


class ReadingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=1, max_length=80)
    wound_id: str = Field(min_length=1, max_length=80)
    ts: datetime
    ph: float | None = Field(ge=0, le=14)
    skin_temp_c: float | None = Field(ge=25, le=45)
    moisture_pct: float | None = Field(ge=0, le=100)
    battery_pct: int = Field(ge=0, le=100)
    sensor_status: Literal["available", "dropout"]
    clinical_context: ClinicalContext = Field(default_factory=ClinicalContext)

    @field_validator("ts")
    @classmethod
    def timestamp_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ts must include a timezone")
        return value


class ReadingView(BaseModel):
    id: int
    device_id: str
    wound_id: str
    ts: datetime
    ph: float | None
    skin_temp_c: float | None
    moisture_pct: float | None
    battery_pct: int
    sensor_status: Literal["available", "dropout"]
    data_source: Literal["SIMULATED"] = "SIMULATED"

    model_config = ConfigDict(from_attributes=True)


class MetricStatus(BaseModel):
    ph: Literal["low", "normal", "high", "check"]
    temperature: Literal["normal", "warm", "check"]
    moisture: Literal["low", "normal", "high", "check"]


class ReadingStatus(BaseModel):
    status: Literal["all_good", "keep_watching", "see_doctor_today"]
    reason_code: Literal[
        "readings_in_expected_ranges",
        "abnormal_reading",
        "high_wound_ph",
        "sensor_dropout",
        "red_flag",
        "no_reading_yet",
    ]
    needs_clinician: bool
    data_source: Literal["SIMULATED"] = "SIMULATED"
    metric_status: MetricStatus
    reading: ReadingView | None


class ScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: Literal[
        "healing",
        "early_infection",
        "heavy_exudate",
        "inflammation_spike",
        "sensor_dropout",
    ]


class ApolloRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=500)
    language: Literal["en", "hi"] = "en"


class ApolloCitation(BaseModel):
    n: int
    title: str
    url: str | None
    domain: str
    retrieved_at: str | None
    origin: Literal["tinyfish_live", "offline"]


class ApolloCall(BaseModel):
    kind: str
    status: str
    detail: str
    result_count: int
    elapsed_ms: int
    query: str


class ApolloGuidance(BaseModel):
    mode: Literal["live", "cached", "offline"]
    topic: str
    query_sent: str | None
    source_count: int
    domain_count: int


class ApolloReply(BaseModel):
    answer: str
    citations: list[ApolloCitation]
    needs_doctor: bool
    escalation: str | None
    red_flags: list[str]
    guidance: ApolloGuidance
    calls: list[ApolloCall]


class TinyFishActivity(BaseModel):
    ts: datetime
    kind: str
    topic: str
    query: str
    status: str
    detail: str
    result_count: int
    elapsed_ms: int


class CareRequest(BaseModel):
    area: str = Field(min_length=3, max_length=80)


class CarePlace(BaseModel):
    name: str
    address: str
    phone: str
    open_status: str


class CareReply(BaseModel):
    places: list[CarePlace]
    mode: Literal["live", "cached"]
    area: str
    retrieved_at: str
    source: str = "Google Maps, read by a TinyFish browser agent"
    run_id: str | None = None


class HistoryPoint(BaseModel):
    ts: datetime
    ph: float | None
    skin_temp_c: float | None
    moisture_pct: float | None
    status: str


class HistoryReply(BaseModel):
    points: list[HistoryPoint]
    total: int
    first_ts: datetime | None
    last_ts: datetime | None
    status_counts: dict[str, int]
    data_source: Literal["SIMULATED"] = "SIMULATED"


class TrendReply(BaseModel):
    advisory_only: bool
    experimental: bool
    trained_on: str
    available: bool
    risk: float | None = None
    level: Literal["low", "watch", "rising"] | None = None
    window: int | None = None
    reason: str | None = None
    have: int | None = None
    need: int | None = None

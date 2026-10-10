"""Python mirror of libs/common/api-contracts. No currency/index conversion."""

import re
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Finite = Annotated[float, Field(allow_inf_nan=False, strict=True)]
Nonnegative = Annotated[Finite, Field(ge=0)]
Month = Annotated[int, Field(ge=1, le=12, strict=True)]
TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d"
    r"(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$"
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_max_length=10000)


class Transaction(StrictModel):
    ts: str
    direction: Literal["in", "out"]
    channel: Literal["card", "transfer", "qr", "cash_in", "other"]
    amount_index: Annotated[Finite, Field(gt=0, le=1e12)]

    @field_validator("ts")
    @classmethod
    def timestamp_valid(cls, value: str) -> str:
        if not TIMESTAMP.fullmatch(value):
            raise ValueError("Invalid ISO transaction timestamp")
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


class ScoreRequest(StrictModel):
    business_id: Annotated[str, Field(min_length=1, max_length=100)]
    requested_amount: Annotated[Nonnegative, Field(le=1e15)] | None = None
    currency: Literal["UZS"] = "UZS"
    as_of_date: str
    transactions: Annotated[list[Transaction], Field(min_length=1, max_length=20000)]

    @field_validator("as_of_date")
    @classmethod
    def date_valid(cls, value: str) -> str:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Expected YYYY-MM-DD")
        if date.fromisoformat(value).year >= 9999:
            raise ValueError("Next 12 forecast months exceed supported calendar")
        return value

    @model_validator(mode="after")
    def cutoff_valid(self) -> "ScoreRequest":
        if any(row.ts[:10] > self.as_of_date for row in self.transactions):
            raise ValueError("Transactions must not be after the assessment date")
        first = min(
            int(row.ts[:4]) * 12 + int(row.ts[5:7]) for row in self.transactions
        )
        last = int(self.as_of_date[:4]) * 12 + int(self.as_of_date[5:7])
        if last - first + 1 > 240:
            raise ValueError("History through assessment date is limited to 240 months")
        return self


class CashflowSummary(StrictModel):
    avg_monthly_inflow_index: Nonnegative
    inflow_volatility: Nonnegative
    net_monthly_surplus_index: Finite
    trend: Literal["growing", "stable", "declining"]


class RecommendedLoan(StrictModel):
    max_affordable_installment_index: Nonnegative
    suggested_principal_index: Nonnegative
    suggested_term_months: Annotated[int, Field(ge=1, le=120, strict=True)]
    rationale: str


class Seasonality(StrictModel):
    monthly_forecast_index: Annotated[list[Finite], Field(min_length=12, max_length=12)]
    weak_months: Annotated[list[Month], Field(max_length=12)]
    strong_months: Annotated[list[Month], Field(max_length=12)]

    @model_validator(mode="after")
    def disjoint(self) -> "Seasonality":
        if (
            len(set(self.weak_months)) != len(self.weak_months)
            or len(set(self.strong_months)) != len(self.strong_months)
            or set(self.weak_months) & set(self.strong_months)
        ):
            raise ValueError("Weak/strong months must be unique and disjoint")
        return self


class ScheduleRow(StrictModel):
    month_offset: Annotated[int, Field(ge=1, le=120, strict=True)]
    installment_index: Nonnegative
    note: Literal["reduced", "normal", "increased"]


class Factor(StrictModel):
    factor: Annotated[str, Field(min_length=1, max_length=1000)]
    impact: Literal["positive", "negative"]
    weight: Finite


class Explanation(StrictModel):
    top_factors: Annotated[list[Factor], Field(max_length=100)]
    advisory: Annotated[list[str], Field(max_length=100)]


class ScoreResponse(StrictModel):
    business_id: Annotated[str, Field(min_length=1, max_length=100)]
    as_of_date: str
    capacity_score: Annotated[Finite, Field(ge=0, le=100)]
    score_band: Literal["low", "medium", "high"]
    cashflow_summary: CashflowSummary
    recommended_loan: RecommendedLoan
    seasonality: Seasonality
    adaptive_schedule: Annotated[list[ScheduleRow], Field(max_length=120)]
    explanation: Explanation
    confidence: Annotated[Finite, Field(ge=0, le=1)]
    flags: Annotated[list[Annotated[str, Field(max_length=500)]], Field(max_length=100)]
    model_version: Annotated[str, Field(min_length=1, max_length=100)]
    request_id: Annotated[str, Field(min_length=1, max_length=200)]

    @field_validator("as_of_date")
    @classmethod
    def date_valid(cls, value: str) -> str:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Expected YYYY-MM-DD")
        date.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def schedule_valid(self) -> "ScoreResponse":
        schedule = self.adaptive_schedule
        if any(row.month_offset != i + 1 for i, row in enumerate(schedule)):
            raise ValueError("Schedule offsets must be contiguous")
        if schedule and len(schedule) != self.recommended_loan.suggested_term_months:
            raise ValueError("Schedule must match term")
        if self.recommended_loan.suggested_principal_index > 0 and not schedule:
            raise ValueError("Positive principal requires schedule")
        return self

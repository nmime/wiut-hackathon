"""The Nest /score wire contract, with bounded candidate-specific validation."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Finite = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Nonnegative = Annotated[Finite, Field(ge=0)]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d"
    r"(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$"
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def validate_date(value: str) -> str:
    if not DATE_RE.fullmatch(value):
        raise ValueError("Expected a real calendar date in YYYY-MM-DD format")
    date.fromisoformat(value)
    return value


class Transaction(StrictModel):
    ts: str
    direction: Literal["in", "out"]
    channel: Literal["card", "transfer", "qr", "cash_in", "other"]
    amount_index: Annotated[Finite, Field(ge=1e-12, le=1e12)]

    @field_validator("ts")
    @classmethod
    def valid_timestamp(cls, value: str):
        if not TIMESTAMP_RE.fullmatch(value):
            raise ValueError("Expected a real ISO transaction timestamp")
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


class ScoreRequest(StrictModel):
    business_id: str = Field(min_length=1, max_length=100)
    requested_amount: Annotated[Nonnegative, Field(le=1e15)] | None = None
    currency: Literal["UZS"] = "UZS"
    as_of_date: str
    transactions: list[Transaction] = Field(min_length=1, max_length=20000)

    @field_validator("as_of_date")
    @classmethod
    def valid_date(cls, value: str):
        return validate_date(value)

    @model_validator(mode="after")
    def cutoff(self):
        if self.business_id != self.business_id.strip():
            raise ValueError("Business ID must not contain surrounding whitespace")
        if self.as_of_date > datetime.now(UTC).date().isoformat():
            raise ValueError("Assessment date must not be in the future")
        if any(row.ts[:10] > self.as_of_date for row in self.transactions):
            raise ValueError("Transactions must not be after the assessment date")
        earliest = min(row.ts[:7] for row in self.transactions)
        start = date.fromisoformat(earliest + "-01")
        end = date.fromisoformat(self.as_of_date)
        if (end.year - start.year) * 12 + end.month - start.month > 600:
            raise ValueError(
                "The candidate accepts at most 50 years of transaction history"
            )
        return self


class Cashflow(StrictModel):
    avg_monthly_inflow_index: Nonnegative
    inflow_volatility: Nonnegative
    net_monthly_surplus_index: Finite
    trend: Literal["growing", "stable", "declining"]


class Loan(StrictModel):
    max_affordable_installment_index: Nonnegative
    suggested_principal_index: Nonnegative
    suggested_term_months: int = Field(strict=True, ge=1, le=120)
    rationale: str = Field(max_length=10000)


class Seasonality(StrictModel):
    monthly_forecast_index: list[Finite] = Field(min_length=12, max_length=12)
    weak_months: list[Annotated[int, Field(strict=True, ge=1, le=12)]] = Field(
        max_length=12
    )
    strong_months: list[Annotated[int, Field(strict=True, ge=1, le=12)]] = Field(
        max_length=12
    )

    @model_validator(mode="after")
    def unique_months(self):
        if len(set(self.weak_months)) != len(self.weak_months) or len(
            set(self.strong_months)
        ) != len(self.strong_months):
            raise ValueError("Seasonal months must be unique")
        if set(self.weak_months) & set(self.strong_months):
            raise ValueError("Weak and strong months must be disjoint")
        return self


class Payment(StrictModel):
    month_offset: int = Field(strict=True, ge=1, le=120)
    installment_index: Nonnegative
    note: Literal["reduced", "normal", "increased"]


class Factor(StrictModel):
    factor: str = Field(min_length=1, max_length=1000)
    impact: Literal["positive", "negative"]
    weight: Finite


class Explanation(StrictModel):
    top_factors: list[Factor] = Field(max_length=100)
    advisory: list[Annotated[str, Field(max_length=10000)]] = Field(max_length=100)


class Provenance(StrictModel):
    real_revenue_weight: Finite = Field(ge=0, le=1)
    synthetic_net_weight: Finite = Field(ge=0, le=1)
    expense_mode: Literal[
        "observed_cost_regression",
        "observed_cost_projection",
        "synthetic_trained",
        "not_used",
    ]
    revenue_candidate: str = Field(min_length=1, max_length=100)
    real_training_targets: int = Field(strict=True, ge=0)


class LoanTerms(StrictModel):
    annual_rate: Finite = Field(ge=0, le=1)
    schedule_type: Literal["annuity", "adaptive"]
    total_interest_index: Nonnegative
    total_repayment_index: Nonnegative
    requested_amount_policy: Literal["capacity_checked", "context_only"]


class ScoreResponse(StrictModel):
    business_id: str = Field(min_length=1, max_length=100)
    as_of_date: str
    capacity_score: Finite = Field(ge=0, le=100)
    score_band: Literal["low", "medium", "high"]
    cashflow_summary: Cashflow
    recommended_loan: Loan
    seasonality: Seasonality
    adaptive_schedule: list[Payment] = Field(max_length=120)
    explanation: Explanation
    confidence: Finite = Field(ge=0, le=1)
    forecast_provenance: Provenance
    flags: list[Annotated[str, Field(max_length=500)]] = Field(max_length=100)
    model_version: str = Field(min_length=1, max_length=100)
    request_id: str = Field(min_length=1, max_length=200)
    loan_terms: LoanTerms

    @field_validator("as_of_date")
    @classmethod
    def valid_date(cls, value):
        return validate_date(value)

    @model_validator(mode="after")
    def financial_invariants(self):
        rows = self.adaptive_schedule
        principal = self.recommended_loan.suggested_principal_index
        if any(row.month_offset != index + 1 for index, row in enumerate(rows)):
            raise ValueError("Payment offsets must be contiguous and one-based")
        if rows and len(rows) != self.recommended_loan.suggested_term_months:
            raise ValueError("Schedule length must match the term")
        total = sum(row.installment_index for row in rows)
        if (principal > 0 and total == 0) or (principal == 0 and total > 0):
            raise ValueError("Principal and repayment must both be zero or positive")
        terms = self.loan_terms
        tolerance = max(
            1e-12, 1e-9 * max(total, principal, terms.total_repayment_index)
        )
        if (
            abs(total - terms.total_repayment_index) > tolerance
            or abs(total - principal - terms.total_interest_index) > tolerance
        ):
            raise ValueError("Principal, interest and repayments do not reconcile")
        provenance = self.forecast_provenance
        if (
            abs(provenance.real_revenue_weight + provenance.synthetic_net_weight - 1)
            > 1e-9
        ):
            raise ValueError("Forecast blend weights must sum to one")
        if (provenance.real_revenue_weight == 0) != (
            provenance.expense_mode == "not_used"
        ):
            raise ValueError("Revenue projection expense policy is inconsistent")
        return self

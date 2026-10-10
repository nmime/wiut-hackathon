"""Declared synthetic stochastic business process; no bank/client dataset used.

Future realised events are the target, never a generated capacity/default label.
Latent parameters and cohort labels are not available to the forecast model.
"""

import calendar
from dataclasses import dataclass

import numpy as np

from .public_data import retail_seasonal_factors
from .schemas import ScoreRequest, Transaction

SEED = 20261010
TRAIN_COUNT = 180
VALIDATION_COUNT = 60
TEST_COUNT = 120
COHORTS = (
    "stable",
    "seasonal",
    "growing",
    "declining",
    "volatile_growth",
    "pattern_break",
    "cold_start",
    "negative_surplus",
    "unseen_seasonality",
)


def month_id(year: int, month: int) -> int:
    return year * 12 + month - 1


def month_text(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


@dataclass
class SyntheticBusiness:
    business_id: str
    cohort: str
    months: np.ndarray
    inflow: np.ndarray
    outflow: np.ndarray
    transactions: list[Transaction]
    cutoff: int

    @property
    def future_net(self) -> np.ndarray:
        return (self.inflow - self.outflow)[self.cutoff : self.cutoff + 12]

    def request(self, cutoff: int | None = None) -> ScoreRequest:
        end = self.cutoff if cutoff is None else cutoff
        last = int(self.months[end - 1])
        year, month = last // 12, last % 12 + 1
        as_of = f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
        return ScoreRequest(
            business_id=self.business_id,
            as_of_date=as_of,
            transactions=[row for row in self.transactions if row.ts[:10] <= as_of],
        )


def generate_business(split: str, position: int) -> SyntheticBusiness:
    split_offset = {"train": 0, "validation": 10000, "test": 20000}[split]
    rng = np.random.default_rng(SEED + split_offset + position)
    # A genuinely new seasonal mechanism occurs only in the held-out test set.
    allowed = COHORTS if split == "test" else COHORTS[:-1]
    cohort = allowed[position % len(allowed)]
    cutoff = int(rng.integers(30, 43))
    if cohort == "cold_start":
        cutoff = int(rng.integers(2, 10))
    length = cutoff + 12
    first_month = month_id(2021, 1) + int(rng.integers(0, 24))
    months = np.arange(first_month, first_month + length)
    t = np.arange(length)
    base = float(rng.uniform(90, 1200))
    phase = rng.uniform(0, 2 * np.pi)
    amplitude = 0.05 if cohort == "stable" else rng.uniform(0.1, 0.5)
    if cohort == "seasonal":
        amplitude = rng.uniform(0.45, 0.75)
    angle = 2 * np.pi * (months % 12) / 12 + phase
    seasonal = 1 + amplitude * np.sin(angle)
    if cohort in {"seasonal", "growing", "declining", "volatile_growth"}:
        # Public 2020–2022 aggregate calendar patterns calibrate only a component
        # of synthetic revenue. No real business expenses/repayment labels exist.
        retail_component = retail_seasonal_factors()[months % 12]
        seasonal = 0.5 * seasonal + 0.5 * retail_component
    drift = {
        "growing": 0.014,
        "volatile_growth": 0.018,
        "declining": -0.015,
    }.get(cohort, float(rng.uniform(-0.004, 0.004)))
    sigma = 0.38 if cohort == "volatile_growth" else rng.uniform(0.04, 0.18)
    noise = rng.lognormal(-(sigma**2) / 2, sigma, length)
    # Correlated shocks plus independent expenses make forecasts imperfect.
    shock = np.zeros(length)
    for i in range(1, length):
        shock[i] = 0.45 * shock[i - 1] + rng.normal(0, sigma * 0.3)
    if cohort == "pattern_break":
        break_at = cutoff - int(rng.integers(0, 5))
        seasonal[break_at:] = 1 - amplitude * np.sin(angle[break_at:])
        noise[break_at:] *= rng.uniform(0.45, 0.85)
    if cohort == "unseen_seasonality":
        seasonal = 1 + 0.6 * np.sin(angle * 2) + 0.15 * np.cos(angle * 3)
    inflow = np.maximum(0, base * seasonal * np.exp(drift * t + shock) * noise)
    cost_share = (
        rng.uniform(1.04, 1.2)
        if cohort == "negative_surplus"
        else rng.uniform(0.35, 0.73)
    )
    outflow = inflow * cost_share * rng.lognormal(
        -(0.08**2) / 2, 0.08, length
    ) + base * rng.uniform(0.015, 0.09) * rng.lognormal(0, 0.25, length)
    if cohort in {"volatile_growth", "pattern_break"}:
        missing = rng.choice(length, size=max(1, length // 16), replace=False)
        inflow[missing] = 0
    transactions: list[Transaction] = []
    channel_mix = rng.dirichlet([2, 2, 2, 1, 0.5])
    channels = ["card", "transfer", "qr", "cash_in", "other"]
    for month_index, incoming, outgoing in zip(months, inflow, outflow, strict=True):
        for direction, total in (("in", incoming), ("out", outgoing)):
            if total <= 0:
                continue
            event_count = int(rng.integers(5, 18))
            sizes = rng.dirichlet(np.full(event_count, 0.7)) * total
            for amount in sizes:
                day = int(rng.integers(1, 28))
                transactions.append(
                    Transaction(
                        ts=f"{month_text(int(month_index))}-{day:02d}T12:00:00Z",
                        direction=direction,
                        channel=str(rng.choice(channels, p=channel_mix)),
                        amount_index=float(amount),
                    )
                )
    transactions.sort(key=lambda row: row.ts)
    return SyntheticBusiness(
        f"synthetic-{split}-{position:04d}",
        cohort,
        months,
        inflow,
        outflow,
        transactions,
        cutoff,
    )


def generate_split(split: str) -> list[SyntheticBusiness]:
    count = {"train": TRAIN_COUNT, "validation": VALIDATION_COUNT, "test": TEST_COUNT}[
        split
    ]
    return [generate_business(split, position) for position in range(count)]

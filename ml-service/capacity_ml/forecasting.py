"""Lag/calendar gradient boosting, seasonal baseline and validation-only choice."""

import calendar
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from .generator import month_id
from .public_data import calibration_digest
from .revenue_data import revenue_data_digest
from .schemas import ScoreRequest

if TYPE_CHECKING:
    from .public_revenue import PublicRevenueModel

ARTIFACT_FORMAT = 2
TRANSFER_WEIGHTS = (0.0, 0.25, 0.5, 1.0)
FEATURE_NAMES = (
    "lag1",
    "lag2",
    "lag3",
    "lag6",
    "lag12",
    "mean3",
    "mean6",
    "mean12",
    "volatility12",
    "trend12",
    "horizon",
    "calendar_sin",
    "calendar_cos",
    "seasonal_naive",
    "history_length",
    "inflow_mean12",
    "outflow_mean12",
)


def pipeline_source_digest() -> str:
    digest = hashlib.sha256()
    for name in (
        "generator.py",
        "forecasting.py",
        "scoring.py",
        "train.py",
        "public_data.py",
        "public_revenue.py",
        "revenue_data.py",
    ):
        digest.update(Path(__file__).with_name(name).read_bytes())
    digest.update(calibration_digest().encode())
    digest.update(revenue_data_digest().encode())
    return digest.hexdigest()


@dataclass
class MonthlyHistory:
    months: np.ndarray
    inflow: np.ndarray
    outflow: np.ndarray
    forecast_start: int
    partial_month_excluded: bool = False
    partial_only: bool = False

    @property
    def net(self) -> np.ndarray:
        return self.inflow - self.outflow


def aggregate(request: ScoreRequest) -> MonthlyHistory:
    year, month, day = map(int, request.as_of_date.split("-"))
    as_of_month = month_id(year, month)
    first = min(
        month_id(int(row.ts[:4]), int(row.ts[5:7])) for row in request.transactions
    )
    partial = day != calendar.monthrange(year, month)[1]
    last_complete = as_of_month - int(partial)
    partial_only = first > last_complete
    last = as_of_month if partial_only else last_complete
    months = np.arange(first, last + 1)
    inflow = np.zeros(len(months))
    outflow = np.zeros(len(months))
    for row in request.transactions:
        index = month_id(int(row.ts[:4]), int(row.ts[5:7])) - first
        if 0 <= index < len(months):
            target = inflow if row.direction == "in" else outflow
            target[index] += row.amount_index
    return MonthlyHistory(
        months,
        inflow,
        outflow,
        as_of_month + 1,
        partial and not partial_only,
        partial_only,
    )


def seasonal_forecast(history: MonthlyHistory) -> np.ndarray:
    result = []
    net = history.net
    for target in range(history.forecast_start, history.forecast_start + 12):
        matching = net[history.months % 12 == target % 12]
        result.append(float(matching[-1]) if len(matching) else float(np.mean(net)))
    return np.asarray(result)


def normalizer(history: MonthlyHistory) -> float:
    incoming = float(np.mean(history.inflow[-12:]))
    outgoing = float(np.mean(history.outflow[-12:]))
    return incoming if incoming > 0 else outgoing if outgoing > 0 else 1.0


def feature_matrix(history: MonthlyHistory) -> np.ndarray:
    net = history.net
    scale = normalizer(history)
    trailing = net[-12:]
    slope = (
        float(np.polyfit(np.arange(len(trailing)), trailing, 1)[0])
        if len(trailing) > 1
        else 0.0
    )
    lags = [
        float(net[-lag] if len(net) >= lag else np.mean(net))
        for lag in (1, 2, 3, 6, 12)
    ]
    base = lags + [
        float(np.mean(net[-3:])),
        float(np.mean(net[-6:])),
        float(np.mean(trailing)),
        float(np.std(trailing)),
        slope,
    ]
    baseline = seasonal_forecast(history)
    features = []
    for horizon in range(12):
        target = history.forecast_start + horizon
        angle = 2 * np.pi * (target % 12) / 12
        features.append(
            [value / scale for value in base]
            + [
                (target - int(history.months[-1])) / 12,
                float(np.sin(angle)),
                float(np.cos(angle)),
                float(baseline[horizon]) / scale,
                min(len(net), 48) / 48,
                float(np.mean(history.inflow[-12:])) / scale,
                float(np.mean(history.outflow[-12:])) / scale,
            ]
        )
    return np.asarray(features)


@dataclass
class ForecastModel:
    estimator: HistGradientBoostingRegressor
    blend_weight: float
    version: str
    selection: dict
    public_revenue_model: "PublicRevenueModel | None" = None
    expense_estimator: HistGradientBoostingRegressor | None = None
    transfer_weight: float = 0.0
    artifact_format: int = ARTIFACT_FORMAT

    def predict_candidates(self, history: MonthlyHistory) -> dict[str, np.ndarray]:
        seasonal = seasonal_forecast(history)
        with threadpool_limits(limits=1):
            boosting = self.estimator.predict(feature_matrix(history)) * normalizer(
                history
            )
        return {
            "seasonal_naive": seasonal,
            "gradient_boosting": boosting,
            "blend_50": (seasonal + boosting) / 2,
        }

    def predict_synthetic(self, history: MonthlyHistory) -> np.ndarray:
        candidates = self.predict_candidates(history)
        return (1 - self.blend_weight) * candidates[
            "seasonal_naive"
        ] + self.blend_weight * candidates["gradient_boosting"]

    def predict_public_net(self, history: MonthlyHistory) -> np.ndarray:
        if self.public_revenue_model is None or self.expense_estimator is None:
            raise ValueError("Missing trained revenue/expense components")
        with threadpool_limits(limits=1):
            expenses = np.maximum(
                self.expense_estimator.predict(feature_matrix(history))
                * normalizer(history),
                0,
            )
        return self.public_revenue_model.predict(history) - expenses

    def predict_transfer_candidates(
        self, history: MonthlyHistory
    ) -> dict[float, np.ndarray]:
        synthetic = self.predict_synthetic(history)
        public_net = self.predict_public_net(history)
        return {
            weight: (1 - weight) * synthetic + weight * public_net
            for weight in TRANSFER_WEIGHTS
        }

    def predict(self, history: MonthlyHistory) -> np.ndarray:
        synthetic = self.predict_synthetic(history)
        if self.transfer_weight == 0:
            return synthetic
        return (
            1 - self.transfer_weight
        ) * synthetic + self.transfer_weight * self.predict_public_net(history)

    def save(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        joblib.dump(self, temporary)
        temporary.replace(destination)

    @classmethod
    def load(cls, path: str | Path) -> "ForecastModel":
        # joblib is executable serialization: load only our locally built artifact.
        model = joblib.load(path)
        if not isinstance(model, cls) or model.artifact_format != ARTIFACT_FORMAT:
            raise ValueError(
                "Unsupported/corrupt local model artifact; retrain explicitly"
            )
        if model.blend_weight not in (0.0, 0.5, 1.0) or not model.version:
            raise ValueError("Invalid artifact selection metadata")
        if model.estimator.n_features_in_ != len(FEATURE_NAMES):
            raise ValueError("Model feature schema mismatch; retrain explicitly")
        if model.transfer_weight not in TRANSFER_WEIGHTS:
            raise ValueError("Invalid public transfer weight")
        if model.public_revenue_model is None or model.expense_estimator is None:
            raise ValueError("Missing trained public revenue/expense components")
        if model.public_revenue_model.selected not in (
            "seasonal_naive",
            "trend_adjusted_seasonal",
            "gradient_boosting",
        ):
            raise ValueError("Invalid public revenue model selection")
        if model.expense_estimator.n_features_in_ != len(
            FEATURE_NAMES
        ) or model.public_revenue_model.estimator.n_features_in_ != len(FEATURE_NAMES):
            raise ValueError("Revenue/expense feature schema mismatch")
        if model.selection.get("source_sha256") != pipeline_source_digest():
            raise ValueError("Stale model artifact: source changed; retrain explicitly")
        return model

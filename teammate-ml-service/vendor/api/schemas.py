"""Pydantic-схемы: из них FastAPI строит OpenAPI-контракт для бэкенда (docs/openapi.json)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from config import DEFAULT_ANNUAL_RATE, DEFAULT_TERM, MAX_TERM, MIN_TERM


class Issue(BaseModel):
    line: Optional[int] = Field(None, description="Номер строки в файле (заголовок = 1)")
    column: Optional[str] = None
    reason: str
    value: Optional[str] = None


class ValidationErrorBody(BaseModel):
    detail: str
    file: str = "transactions.csv"
    errors: list[Issue]
    warnings: list[Issue] = []
    n_errors_total: int
    request_id: Optional[str] = Field(None, description="ID записи input_rejected в журнале аудита (GET /v1/audit/{id})")


class AssessParams(BaseModel):
    """Параметры заявки. Передаются JSON-строкой в поле формы `params`."""
    business_id: Optional[str] = Field(None, description="Обязателен, если в файле несколько бизнесов")
    requested_amount: Optional[float] = Field(None, gt=0, description="Если не указана — вернётся максимальная рекомендуемая")
    term_months: int = Field(DEFAULT_TERM, ge=MIN_TERM, le=MAX_TERM)
    annual_rate: float = Field(DEFAULT_ANNUAL_RATE, ge=0, le=1, description="Годовая ставка, доля (0.24 = 24%)")
    issue_month: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}$", description="Месяц выдачи YYYY-MM; первый платёж — в следующем месяце")
    as_of_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Дата выгрузки; по умолчанию — максимальная дата в файле")
    lang: Literal["ru", "uz"] = "ru"


class ProfileMonth(BaseModel):
    month: str
    inflow_total: float
    inflow_card: float
    inflow_qr: float
    inflow_transfer: float
    inflow_cash_other: float
    outflow_total: float
    outflow_fixed: float
    outflow_debt: float
    net_flow: float
    n_in_txn: float
    active_days: float
    unique_payers: float
    top_payer_share: Optional[float] = None


class ForecastMonth(BaseModel):
    month: str
    inflow_p10: float
    inflow_p50: float
    inflow_p90: float
    outflow_operating_p50: float
    debt_service: float
    free_cash_flow_p10: float
    free_cash_flow_p50: float
    free_cash_flow_p90: float
    season_label: Literal["weak", "normal", "strong"]
    season_index: float = Field(description="Детрендированное лог-отклонение прогноза притока")
    ramadan_share: float


class DecompItem(BaseModel):
    key: str
    label: str
    value: float


class Confidence(BaseModel):
    level: Literal["low", "medium", "high"]
    value: float
    history_factor: float
    interval_factor: float
    relative_interval_width: float
    reasons: list[str]


class MonthCap(BaseModel):
    month: str
    capacity: float


class RiskTier(BaseModel):
    """Второй уровень: больше сумма, выше вероятность перегрузки. Принимать ли его — решает офицер."""
    band: str = Field(description="Полоса прогноза, по которой считается платёж (P20)")
    buffer_k: float
    target_coverage: float = Field(description="Покрытие, под которое калиброван k (0.80)")
    max_installment: float
    recommended_amount: float
    expected_overload_share: float = Field(description="Прогнозная доля месяцев, где свободный поток < платежа")
    decomposition: list[DecompItem]
    monthly_capacity: list[MonthCap]
    label: str


class Capacity(BaseModel):
    max_installment: float = Field(description="Основной уровень (P10, покрытие 90%): максимальный посильный фиксированный платёж, сум/мес")
    recommended_amount: float = Field(description="PV max_installment при заданных ставке и сроке")
    expected_overload_share: float = Field(description="Прогнозная доля месяцев, где свободный поток < max_installment")
    capacity_score: float = Field(description="0..100: вероятность (%), что свободный поток месяца >= reference_load × средний приток")
    buffer_k: float
    reference_load: float
    confidence: Confidence
    decomposition: list[DecompItem]
    monthly_capacity: list[MonthCap]
    risk_tier: Optional[RiskTier] = Field(None, description="Уровень повышенного риска (P20, покрытие 80%)")


class ScheduleRow(BaseModel):
    n: int
    month: str
    payment: float
    interest: float
    principal: float
    balance: float
    capacity: float
    over_capacity: bool


class ScheduleComparison(BaseModel):
    annuity_overload_months: int
    adaptive_overload_months: int
    annuity_overload_volume: float
    adaptive_overload_volume: float
    annuity_total_interest: float
    adaptive_total_interest: float
    interest_difference: float


class Suggestions(BaseModel):
    reason: str
    max_amount_for_term: float
    min_term_for_amount: Optional[int] = None
    max_amount_risk_tier: Optional[float] = Field(None, description="Максимальная сумма на этот срок на уровне повышенного риска")


class Schedule(BaseModel):
    amount: float
    amount_source: Literal["requested", "recommended"]
    term_months: int
    annual_rate: float
    issue_month: str
    annuity_payment: float
    status: Literal["within_capacity", "within_risk_capacity", "exceeds_capacity", "no_capacity"] = Field(
        description="within_capacity — укладывается в основной уровень; within_risk_capacity — только в уровень "
                    "повышенного риска (решение за офицером)")
    capacity_tier: Literal["main", "risk"] = Field(description="По capacity какого уровня построен график")
    adaptive_available: bool
    adaptive_unavailable_reason: Optional[str] = None
    annuity: list[ScheduleRow]
    adaptive: Optional[list[ScheduleRow]] = None
    comparison: Optional[ScheduleComparison] = None
    suggestions: Optional[Suggestions] = None
    notes: list[str] = []


class Factor(BaseModel):
    factor: str
    name_ru: str
    name_uz: str
    contribution_log: float
    effect_pct: float
    direction: Literal["up", "down"]
    text_ru: str
    text_uz: str


class Benchmark(BaseModel):
    feature: str
    name: str
    value: float
    population_median: float
    band: str


class ScheduleReason(BaseModel):
    month: str
    change_vs_annuity: float
    season_label: str
    forecast_free_cash_flow: float
    ramadan: bool
    extrapolated: bool
    text_ru: str


class Advice(BaseModel):
    key: str
    severity: Literal["high", "medium", "low", "info"]
    text_ru: str
    text_uz: str


class Explanations(BaseModel):
    summary_ru: str
    top_factors: list[Factor]
    outflow_factors: list[Factor]
    capacity_decomposition: list[DecompItem]
    profile_benchmarks: list[Benchmark]
    schedule_reasons: list[ScheduleReason]
    advice: list[Advice]
    advice_llm: Optional[str] = Field(None, description="Только при ML_ENABLE_LLM=1; в проде — локально/шаблоны")


class DataQuality(BaseModel):
    rows: int
    businesses_in_file: int
    rows_for_business: int
    months_used: int
    first_month: Optional[str]
    last_complete_month: Optional[str]
    excluded_months: list[str]
    history_mode: Literal["refused", "no_seasonality", "reduced_seasonality", "full"]
    warnings: list[Issue]


class AuditInfo(BaseModel):
    request_id: str
    created_at: str
    model_version: str
    generator_version: str
    service_version: str
    csv_sha256: str
    business_csv_sha256: Optional[str] = None
    params: AssessParams


class AssessmentResponse(BaseModel):
    request_id: str
    status: Literal["ok", "refused"]
    business_id: str
    refusal_reason: Optional[str] = None
    data_quality: DataQuality
    profile_features: dict[str, Optional[float]]
    history: list[ProfileMonth]
    forecast: Optional[list[ForecastMonth]] = None
    capacity: Optional[Capacity] = None
    schedule: Optional[Schedule] = None
    explanations: Optional[Explanations] = None
    audit: AuditInfo
    disclaimer: str = ("Сервис не принимает кредитное решение. Это объяснимая оценка "
                       "платёжеспособности; решение принимает кредитный офицер.")


class ModifiedTerms(BaseModel):
    amount: Optional[float] = Field(None, gt=0)
    term_months: Optional[int] = Field(None, ge=MIN_TERM, le=MAX_TERM)
    annual_rate: Optional[float] = Field(None, ge=0, le=1)
    schedule_type: Optional[Literal["annuity", "adaptive"]] = None
    capacity_tier: Optional[Literal["main", "risk"]] = Field(
        None, description="risk — офицер осознанно принял уровень повышенного риска (P20)")


class DecisionIn(BaseModel):
    officer_id: str = Field(min_length=1)
    decision: Literal["approved", "rejected", "modified"]
    modified_terms: Optional[ModifiedTerms] = None
    comment: str = ""


class DecisionRecord(BaseModel):
    request_id: str
    logged_at: str
    hash: str
    officer_id: str
    decision: str
    modified_terms: Optional[ModifiedTerms] = None
    comment: str


class AssessmentRecord(BaseModel):
    request_id: str
    logged_at: str
    hash: str
    response: AssessmentResponse
    decisions: list[DecisionRecord]


class Health(BaseModel):
    status: str
    model_version: str
    generator_version: str
    service_version: str
    buffer_k: float
    llm_enabled: bool
    audit_records: int


class DemoRequest(BaseModel):
    industry: Literal["retail_food", "restaurant", "agriculture", "construction", "clothing",
                      "tourism", "it_services", "car_service", "education"] = "retail_food"
    base_revenue_mln: float = Field(80, ge=5, le=2000, description="Месячный приток, млн сум")
    seasonality: float = Field(0.35, ge=0, le=0.8, description="Амплитуда сезонности (лог)")
    growth: float = Field(0.1, ge=-0.6, le=0.8, description="Годовой тренд (лог)")
    volatility: float = Field(0.1, ge=0.01, le=0.4)
    history_months: int = Field(30, ge=3, le=36)
    fixed_share: float = Field(0.18, ge=0.02, le=0.5)
    has_loan: bool = False
    seed: int = 1


class DemoResponse(BaseModel):
    csv: str
    rows: int
    business_id: str
    future_actual: list[dict] = Field(description="Факт будущих 12 мес. из генератора — "
                                                  "только для визуального сравнения в демо, в /v1/assess не передаётся")

"""Оркестрация одного запроса /v1/assess: CSV -> валидация -> профиль -> A/B/C -> объяснения -> аудит."""
from __future__ import annotations

import hashlib
import math
import uuid
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from api.audit import AuditLog
from api.schemas import AssessmentResponse
from config import GENERATOR_VERSION, MAX_UPLOAD_BYTES, SERVICE_VERSION
from features.calendar import idx_to_str, ramadan_fraction, str_to_idx
from features.profile import build_monthly_profile, profile_features
from features.schema import (CsvStructureError, read_csv_bytes, validate_business,
                             validate_transactions)
from models import explain
from models.capacity import MAIN_BAND, RISK_BAND, assess_capacity, monthly_caps
from models.llm import paraphrase_advice
from models.plan import plan_loan
from models.registry import ModelBundle


class InputError(Exception):
    def __init__(self, detail: str, errors=None, warnings=None, n_total=0, file="transactions.csv"):
        super().__init__(detail)
        self.body = dict(detail=detail, file=file, errors=errors or [], warnings=warnings or [],
                         n_errors_total=n_total or len(errors or []))


def clean(obj):
    """NaN/inf -> None, numpy -> python."""
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


def finalize(resp: dict) -> dict:
    """Ответ проходит через pydantic-контракт: в аудит и клиенту уходит ровно то, что в OpenAPI."""
    return AssessmentResponse.model_validate(clean(resp)).model_dump(mode="json")


def assess(bundle: ModelBundle, audit: AuditLog, tx_bytes: bytes, params: dict,
           business_bytes: bytes | None = None) -> dict:
    if len(tx_bytes) > MAX_UPLOAD_BYTES:
        raise InputError(f"файл больше {MAX_UPLOAD_BYTES // 2**20} МБ")
    try:
        raw = read_csv_bytes(tx_bytes)
    except UnicodeDecodeError:
        raise InputError("файл не в кодировке UTF-8")
    except CsvStructureError as e:
        raise InputError("файл не разбирается как CSV", [i.to_dict() for i in e.issues], [], e.total)
    except Exception as e:  # noqa: BLE001
        raise InputError(f"не удалось прочитать CSV: {e}")
    v = validate_transactions(raw)
    if not v.ok:
        raise InputError("файл не прошёл валидацию", v.errors_dict(), v.warnings_dict(), v.n_errors_total)
    warnings = v.warnings_dict()

    biz_df = None
    if business_bytes:
        vb = validate_business(read_csv_bytes(business_bytes))
        if not vb.ok:
            raise InputError("business.csv не прошёл валидацию", vb.errors_dict(),
                             vb.warnings_dict(), vb.n_errors_total, file="business.csv")
        biz_df = vb.df
        warnings += vb.warnings_dict()

    tx = v.df
    ids = tx["business_id"].unique()
    bid = params.get("business_id")
    if bid is None:
        if len(ids) != 1:
            raise InputError(f"в файле {len(ids)} бизнесов — укажите business_id в params")
        bid = str(ids[0])
    elif bid not in set(ids):
        raise InputError(f"business_id {bid} отсутствует в файле")
    txb = tx[tx["business_id"] == bid]

    as_of = pd.Timestamp(params["as_of_date"]) + pd.Timedelta(hours=23, minutes=59) \
        if params.get("as_of_date") else tx["ts"].max()
    prof, infos = build_monthly_profile(txb, as_of=as_of)
    info = infos[bid]
    prof_b = prof[prof["business_id"] == bid].sort_values("month_idx")

    request_id = str(uuid.uuid4())
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    audit_info = dict(
        request_id=request_id, created_at=created, model_version=bundle.version,
        generator_version=bundle.meta.get("generator_version", GENERATOR_VERSION),
        service_version=SERVICE_VERSION, csv_sha256=hashlib.sha256(tx_bytes).hexdigest(),
        business_csv_sha256=hashlib.sha256(business_bytes).hexdigest() if business_bytes else None,
        params=params,
    )
    dq = dict(rows=v.n_rows, businesses_in_file=int(len(ids)), rows_for_business=int(len(txb)),
              months_used=info.months, first_month=info.first_month,
              last_complete_month=info.last_complete_month, excluded_months=info.excluded_months,
              history_mode=info.mode, warnings=warnings)
    pf = profile_features(prof_b)
    history = prof_b.drop(columns=["business_id", "month_idx", "outflow_operating"]).tail(36)
    resp = dict(request_id=request_id, business_id=bid, data_quality=dq, profile_features=pf,
                history=history.to_dict("records"), audit=audit_info)

    if info.mode == "refused":
        resp.update(status="refused",
                    refusal_reason=f"история {info.months} полных мес. — меньше минимальных 6. "
                                   f"Оценка платёжеспособности по такой истории ненадёжна.")
        resp = finalize(resp)
        audit.append("assessment", request_id, resp)
        return resp

    oked = ext_debt = None
    if biz_df is not None and bid in biz_df.index:
        oked = biz_df.at[bid, "industry_oked"] or None
        d = biz_df.at[bid, "existing_monthly_debt"]
        ext_debt = None if pd.isna(d) else float(d)
    fr = bundle.forecast.predict_business(prof_b, oked, ext_debt or 0.0)
    k = bundle.buffer_k
    labels, sidx = explain.season_labels(fr)
    q10_in, q90_in = fr.q(0.1, "in"), fr.q(0.9, "in")
    q10_f, q90_f = fr.q(0.1), fr.q(0.9)
    forecast = [dict(month=idx_to_str(m), inflow_p10=q10_in[j], inflow_p50=fr.in_p50[j],
                     inflow_p90=q90_in[j], outflow_operating_p50=fr.out_p50[j],
                     debt_service=fr.debt[j], free_cash_flow_p10=q10_f[j],
                     free_cash_flow_p50=fr.free_p50[j], free_cash_flow_p90=q90_f[j],
                     season_label=labels[j], season_index=round(float(sidx[j]), 4),
                     ramadan_share=round(ramadan_fraction(m), 3))
                for j, m in enumerate(fr.months)]

    term = int(params.get("term_months") or 12)
    rate = float(params.get("annual_rate") if params.get("annual_rate") is not None else 0.24)
    k_risk = bundle.buffer_k_risk
    cap = assess_capacity(fr, k, bundle.ref_load, rate, term, k_risk)
    month_caps = lambda c12: [dict(month=idx_to_str(m), capacity=round(float(c), 2))  # noqa: E731
                              for m, c in zip(fr.months, c12)]
    cap["monthly_capacity"] = month_caps(monthly_caps(fr, k, MAIN_BAND))
    if cap["risk_tier"] is not None:
        cap["risk_tier"]["monthly_capacity"] = month_caps(monthly_caps(fr, k_risk, RISK_BAND))
    if ext_debt:
        warnings.append(dict(line=None, column="existing_monthly_debt",
                             reason=f"учтён внешний долг {ext_debt:,.0f} сум/мес из business.csv",
                             value=None))

    issue_idx = str_to_idx(params["issue_month"]) if params.get("issue_month") else None
    try:
        plan = plan_loan(fr, k, rate, term, params.get("requested_amount"), issue_idx, k_risk)
    except ValueError as e:
        raise InputError(str(e))

    labels_by = dict(zip(fr.months, labels))
    free_by = {m: float(fr.free_p50[(m - fr.months[0]) % 12]) for m in plan["_pay_months"]}
    reasons = []
    if plan.get("_adaptive_payments") is not None:
        reasons = explain.schedule_reasons(plan["_pay_months"], plan["_adaptive_payments"],
                                           plan["annuity_payment"], fr,
                                           {m: labels_by.get(fr.months[0] + (m - fr.months[0]) % 12)
                                            for m in plan["_pay_months"]}, free_by)
    adv = explain.advice(pf, bundle.population, fr, labels)
    lang = params.get("lang", "ru")
    llm = paraphrase_advice([a["text_uz" if lang == "uz" else "text_ru"] for a in adv], lang)

    weak = [idx_to_str(m) for m, lab in zip(fr.months, labels) if lab == "weak"]
    summary = (f"Посильный фиксированный платёж — {explain.fmt_sum(cap['max_installment'])}/мес, "
               f"рекомендуемая сумма на {term} мес. — {explain.fmt_sum(cap['recommended_amount'])}. "
               f"Capacity score {cap['capacity_score']:.0f}/100, уверенность: {cap['confidence']['level']}. ")
    rt = cap["risk_tier"]
    if rt is not None and rt["max_installment"] > cap["max_installment"]:
        summary += (f"Уровень повышенного риска: до {explain.fmt_sum(rt['max_installment'])}/мес "
                    f"(сумма до {explain.fmt_sum(rt['recommended_amount'])} по аннуитету), прогнозная доля месяцев "
                    f"с перегрузкой {rt['expected_overload_share']:.0%} — на усмотрение офицера. ")
    if weak:
        summary += f"Прогнозно слабые месяцы: {', '.join(weak)}. "
    summary += {"within_capacity": "Запрошенные условия укладываются в прогнозный поток.",
                "within_risk_capacity": "Запрошенные условия укладываются только в уровень повышенного "
                                        "риска — решение за офицером.",
                "exceeds_capacity": "Запрошенные условия превышают посильные — см. предложения.",
                "no_capacity": "Свободного потока в слабые месяцы недостаточно для платежа."}[plan["status"]]

    resp.update(
        status="ok", forecast=forecast, capacity=cap, schedule=plan,
        explanations=dict(
            summary_ru=summary, top_factors=explain.top_factors(fr.shap_in),
            outflow_factors=explain.top_factors(fr.shap_out, 3, target="outflow"),
            capacity_decomposition=cap["decomposition"],
            profile_benchmarks=explain.profile_benchmarks(pf, bundle.population),
            schedule_reasons=reasons, advice=adv, advice_llm=llm),
    )
    resp = finalize(resp)
    audit.append("assessment", request_id, resp)
    return resp

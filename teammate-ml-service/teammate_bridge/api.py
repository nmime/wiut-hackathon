"""Private Nest-compatible adapter around the teammate's unchanged assess()."""

from __future__ import annotations

import calendar
import csv
import hashlib
import io
import json
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from teammate_bridge.audit import DurableAudit, VendorResponseCollector
from teammate_bridge.loader import load_candidate
from teammate_bridge.schemas import ScoreRequest, ScoreResponse

MAX_BODY_BYTES = 5 * 1024 * 1024
REQUEST_ID = re.compile(r"^[a-zA-Z0-9._:-]{1,200}$")


def transaction_csv(payload: ScoreRequest) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "business_id",
            "txn_id",
            "timestamp",
            "amount",
            "direction",
            "channel",
            "currency",
        ]
    )
    for index, row in enumerate(payload.transactions):
        # Existing transport forecasts group the supplied calendar components.
        # Strip only the timezone offset, preserving date, time and amount. Vendor
        # treats a naive timestamp as Tashkent local time, avoiding month shifts.
        timestamp = (
            datetime.fromisoformat(row.ts.replace("Z", "+00:00"))
            .replace(tzinfo=None)
            .isoformat()
        )
        transaction_id = hashlib.sha256(
            f"{payload.business_id}:{index}".encode()
        ).hexdigest()
        writer.writerow(
            [
                payload.business_id,
                transaction_id,
                timestamp,
                format(Decimal(str(row.amount_index)), "f"),
                row.direction,
                "cash" if row.channel == "cash_in" else row.channel,
                "UZS",
            ]
        )
    return output.getvalue().encode()


def map_result(
    payload: ScoreRequest,
    original: dict,
    recommendation: dict,
    version: str,
    request_id: str,
) -> dict:
    profile = original["profile_features"]
    capacity = original["capacity"]
    forecast = original["forecast"]
    plan = recommendation["schedule"]
    confidence = capacity["confidence"]["value"]
    trend = profile["trend_annual"]
    score = capacity["capacity_score"]
    rows = plan["adaptive"] or plan["annuity"]
    total = sum(row["payment"] for row in rows)
    principal = plan["amount"]
    interest = total - principal
    if interest < 0:
        raise ValueError("Vendor rounded repayments are below the principal")
    factors = original["explanations"]["top_factors"]
    flags = [
        "teammate_candidate",
        "synthetic_training_only",
        "category_unavailable",
        "counterparty_unavailable",
        "amount_index_1_to_1_uzs",
        "calendar_components_preserved",
        "human_review_required",
        "annual_rate_24_percent",
        f"native_schedule_status_{original['schedule']['status']}",
        f"history_mode_{original['data_quality']['history_mode']}",
    ]
    if original["schedule"]["status"] != "within_capacity" and payload.requested_amount:
        flags.append("requested_amount_exceeds_main_capacity")
    if not plan["adaptive_available"]:
        flags.append("adaptive_schedule_unavailable_annuity_used")
    if payload.requested_amount == 0:
        flags.append("requested_amount_zero_treated_as_unspecified")
    if original["data_quality"]["excluded_months"]:
        flags.append("partial_first_month_excluded")
    advisory = [
        "Candidate forecast and calibration were trained on 420 synthetic businesses. Real borrower accuracy has not been established; this is payment capacity, not default probability.",
        "Monetary conversion for this adapter is explicit: 1 amount_index = 1 UZS. Use only actual UZS transaction imports.",
        "The shared transaction import has no categories or counterparties. Debt, own transfers, fixed costs and customer concentration cannot be identified separately. Review these omissions before a credit decision.",
        f"Native teammate loan calculation uses {plan['annual_rate']:.0%} annual interest over {plan['term_months']} months. Total repayment includes interest; no zero-interest assumption is used.",
        "Supplied timestamp calendar components are preserved. The candidate uses complete month-end cutoffs and may exclude a first month whose earliest transaction is on day 10 or later.",
    ]
    if original["schedule"]["status"] != "within_capacity" and payload.requested_amount:
        advisory.append(
            f"The original requested terms returned {original['schedule']['status']}. The displayed loan and repayment schedule use the genuine main-tier recommendation instead; higher-risk capacity requires a separate human review."
        )
    advisory.extend(item["text_ru"] for item in original["explanations"]["advice"])
    if not plan["adaptive_available"] and plan["adaptive_unavailable_reason"]:
        advisory.append(plan["adaptive_unavailable_reason"])
    return ScoreResponse.model_validate(
        {
            "business_id": payload.business_id,
            "as_of_date": payload.as_of_date,
            "capacity_score": score,
            "score_band": "high"
            if score >= 70
            else ("medium" if score >= 40 else "low"),
            "cashflow_summary": {
                "avg_monthly_inflow_index": profile["inflow_mean_12"],
                "inflow_volatility": profile["inflow_cv"],
                "net_monthly_surplus_index": profile["net_mean_12"],
                "trend": "growing"
                if trend > 0.05
                else ("declining" if trend < -0.05 else "stable"),
            },
            "recommended_loan": {
                "max_affordable_installment_index": capacity["max_installment"],
                "suggested_principal_index": principal,
                "suggested_term_months": plan["term_months"],
                "rationale": original["explanations"]["summary_ru"]
                + f" Displayed principal: {principal:,.2f} UZS; native APR {plan['annual_rate']:.0%}, {plan['term_months']} months. The frozen candidate was trained on synthetic businesses; real borrower accuracy is unverified.",
            },
            "seasonality": {
                "monthly_forecast_index": [
                    row["free_cash_flow_p50"] for row in forecast
                ],
                "weak_months": [
                    int(row["month"][5:7])
                    for row in forecast
                    if row["season_label"] == "weak"
                ],
                "strong_months": [
                    int(row["month"][5:7])
                    for row in forecast
                    if row["season_label"] == "strong"
                ],
            },
            "adaptive_schedule": [
                {
                    "month_offset": index + 1,
                    "installment_index": row["payment"],
                    "note": "reduced"
                    if row["payment"] < plan["annuity_payment"] * 0.98
                    else (
                        "increased"
                        if row["payment"] > plan["annuity_payment"] * 1.02
                        else "normal"
                    ),
                }
                for index, row in enumerate(rows)
            ],
            "explanation": {
                "top_factors": [
                    {
                        "factor": item["name_ru"],
                        "impact": "positive"
                        if item["direction"] == "up"
                        else "negative",
                        "weight": item["contribution_log"],
                    }
                    for item in factors
                ],
                "advisory": advisory,
            },
            "confidence": confidence,
            "forecast_provenance": {
                "real_revenue_weight": 0.0,
                "synthetic_net_weight": 1.0,
                # This enum describes the real-revenue expense projection contribution,
                # which is not used here. The native synthetic-trained outflow model is
                # separately and explicitly disclosed above.
                "expense_mode": "not_used",
                "revenue_candidate": "teammate_lightgbm_synthetic",
                "real_training_targets": 0,
            },
            "flags": flags,
            "model_version": version,
            "request_id": request_id,
            "loan_terms": {
                "annual_rate": plan["annual_rate"],
                "schedule_type": "adaptive" if plan["adaptive"] else "annuity",
                "total_interest_index": interest,
                "total_repayment_index": total,
                "requested_amount_policy": "capacity_checked",
            },
        }
    ).model_dump(mode="json")


class ScoringAuditMiddleware:
    """Bound input and release responses only after the completion is durable."""

    def __init__(self, app, state):
        self.app, self.state = app, state

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["path"] != "/score"
            or scope["method"] != "POST"
        ):
            return await self.app(scope, receive, send)
        supplied = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        request_id = supplied if REQUEST_ID.fullmatch(supplied) else str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        started, body, digest = time.perf_counter(), bytearray(), hashlib.sha256()
        too_large, disconnected = False, False
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                disconnected = True
                break
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > MAX_BODY_BYTES:
                digest.update(chunk[: MAX_BODY_BYTES - len(body)])
                too_large = True
                break
            body.extend(chunk)
            digest.update(chunk)
            if not message.get("more_body", False):
                break
        common = {
            "request_id": request_id,
            "input_hash": digest.hexdigest(),
            "input_hash_scope": "prefix" if too_large else "complete",
            "model_version": self.state.model_version,
            "model_artifact_sha256": self.state.model_artifact_sha256,
            "source_archive_sha256": self.state.manifest["archive_sha256"],
            "bridge_source_sha256": self.state.manifest["bridge_source_sha256"],
        }
        messages = []

        async def capture(message):
            messages.append(message)

        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return {"type": "http.disconnect"}

        try:
            self.state.audit.append({**common, "event": "assessment_requested"})
            if too_large or disconnected:
                await JSONResponse(
                    status_code=413 if too_large else 400,
                    content={
                        "detail": "Scoring body exceeds 5 MiB"
                        if too_large
                        else "Incomplete request body"
                    },
                )(scope, replay, capture)
            else:
                try:
                    await self.app(scope, replay, capture)
                except Exception:
                    messages.clear()
                    await JSONResponse(
                        status_code=500,
                        content={
                            "detail": "Candidate scoring failed; no recommendation generated"
                        },
                    )(scope, replay, capture)
            status = next(
                message["status"]
                for message in messages
                if message["type"] == "http.response.start"
            )
            problem = {}
            if status != 200:
                response_body = b"".join(
                    message.get("body", b"")
                    for message in messages
                    if message["type"] == "http.response.body"
                )
                if len(response_body) <= 16384:
                    problem = {"response_problem": json.loads(response_body)}
            self.state.audit.append(
                {
                    **common,
                    **scope["state"].get("result_metadata", {}),
                    **problem,
                    "event": "assessment_completed"
                    if status == 200
                    else "assessment_failed",
                    "status": status,
                    "latency_ms": (time.perf_counter() - started) * 1000,
                }
            )
        except OSError:
            messages.clear()
            await JSONResponse(
                status_code=503,
                content={
                    "detail": "Durable candidate audit unavailable; no recommendation released"
                },
            )(scope, replay, capture)
        for message in messages:
            if message["type"] == "http.response.start":
                message["headers"] = message.get("headers", []) + [
                    (b"x-request-id", request_id.encode())
                ]
            await send(message)


def create_app(
    audit_path: str | Path | None = None, vendor_root: Path | None = None
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        bundle, artifact_hash, version, manifest, snapshot, assess, input_error = (
            load_candidate(vendor_root)
        )
        application.state.bundle = bundle
        application.state.model_artifact_sha256 = artifact_hash
        application.state.model_version = version
        application.state.manifest = manifest
        application.state.vendor_assess = assess
        application.state.vendor_input_error = input_error
        application.state.inference_slot = threading.BoundedSemaphore(1)
        application.state.audit = DurableAudit(
            audit_path or os.environ.get("ML_AUDIT_PATH", "runtime/requests.jsonl")
        )
        try:
            yield
        finally:
            snapshot.cleanup()

    application = FastAPI(
        title="FlowCredit private teammate candidate",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(ScoringAuditMiddleware, state=application.state)

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        errors = error.errors()
        request.state.result_metadata = {
            "validation_errors": [
                {"path": list(item["loc"]), "message": item["msg"]}
                for item in errors[:20]
            ],
            "error_count": len(errors),
        }
        return JSONResponse(
            status_code=422,
            content={
                "code": "invalid_input",
                "detail": "Candidate input could not be validated. Check transaction dates, amounts and supported UZS currency.",
            },
        )

    @application.exception_handler(HTTPException)
    async def scoring_problem(_request, error):
        if isinstance(error.detail, dict) and "code" in error.detail:
            return JSONResponse(
                status_code=error.status_code,
                content=error.detail,
                headers=error.headers,
            )
        return JSONResponse(
            status_code=error.status_code,
            content={"detail": error.detail},
            headers=error.headers,
        )

    @application.get("/health")
    def health(request: Request):
        state = request.app.state
        return {
            "status": "ok",
            "model_version": state.model_version,
            "model_artifact_sha256": state.model_artifact_sha256,
            "source_archive_sha256": state.manifest["archive_sha256"],
            "bridge_source_sha256": state.manifest["bridge_source_sha256"],
            "local_inference": True,
            "synthetic_training_only": True,
            "serving_mode": "optional_teammate_candidate",
            "public_transfer_weight": 0.0,
            "public_training_targets": 0,
            "training_businesses": state.bundle.meta["n_train_businesses"],
            "annual_rate": 0.24,
            "assessment_cutoff": "completed_calendar_month_end",
            "external_llm_enabled": False,
            "provenance": "Frozen teammate LightGBM candidate trained on 420 synthetic businesses; no real-borrower accuracy or default labels. Missing categories and counterparties are disclosed. Native 24% annual interest is retained.",
        }

    @application.post("/score", response_model=ScoreResponse)
    def score(payload: ScoreRequest, request: Request):
        state = request.app.state
        cutoff = datetime.fromisoformat(payload.as_of_date)
        if cutoff.day != calendar.monthrange(cutoff.year, cutoff.month)[1]:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "month_end_required",
                    "detail": "The teammate candidate requires a completed calendar month-end assessment date. Select the latest completed month-end or use the real-data blend.",
                },
            )
        if not "2019-12-31" <= payload.as_of_date <= "2028-12-31":
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "unsupported_calendar",
                    "detail": "The teammate candidate supports forecast calendars from 2020 through 2029. Select a supported completed month-end or use the real-data blend.",
                },
            )
        if not state.inference_slot.acquire(blocking=False):
            raise HTTPException(
                status_code=429,
                detail="Candidate scorer is busy; retry shortly",
                headers={"Retry-After": "1"},
            )
        collector = VendorResponseCollector()
        try:
            tx_bytes = transaction_csv(payload)
            params = {
                "business_id": payload.business_id,
                "requested_amount": payload.requested_amount or None,
                "annual_rate": 0.24,
                "term_months": 12,
                "issue_month": payload.as_of_date[:7],
                "as_of_date": payload.as_of_date,
                "lang": "ru",
            }
            original = state.vendor_assess(state.bundle, collector, tx_bytes, params)
            if original["status"] == "refused":
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "insufficient_history",
                        "detail": "The teammate candidate needs at least 6 complete months of transaction history. Import more history or use the real-data blend.",
                    },
                )
            if original["profile_features"].get("inflow_cv") is None:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "invalid_input",
                        "detail": "No observed incoming revenue is available to estimate capacity reliably. Import actual incoming transactions.",
                    },
                )
            month_index = cutoff.year * 12 + cutoff.month - 1
            expected_forecast = [
                f"{(month_index + offset) // 12:04d}-{(month_index + offset) % 12 + 1:02d}"
                for offset in range(1, 13)
            ]
            if [row["month"] for row in original["forecast"]] != expected_forecast:
                raise ValueError(
                    "Vendor forecast months do not match the declared cutoff"
                )
            recommendation = original
            if (
                original["schedule"]["status"] != "within_capacity"
                and payload.requested_amount
            ):
                recommendation = state.vendor_assess(
                    state.bundle,
                    collector,
                    tx_bytes,
                    {**params, "requested_amount": None},
                )
            result = map_result(
                payload,
                original,
                recommendation,
                state.model_version,
                request.state.request_id,
            )
            request.state.result_metadata = {"result": result}
            return result
        except state.vendor_input_error as error:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "invalid_input",
                    "detail": "Candidate input could not be validated. Check transaction dates, amounts and supported UZS currency.",
                },
            ) from error
        finally:
            metadata = getattr(request.state, "result_metadata", {})
            request.state.result_metadata = {
                **metadata,
                "vendor_assessments": collector.records,
            }
            state.inference_slot.release()

    return application


app = create_app()

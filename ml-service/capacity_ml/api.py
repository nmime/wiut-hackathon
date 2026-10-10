"""FastAPI service with durable local audit, validation and no silent fallback."""

import hashlib
import json
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .forecasting import ForecastModel
from .schemas import ScoreRequest, ScoreResponse
from .scoring import score_request

MAX_BODY_BYTES = 5 * 1024 * 1024
REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")


def canonical_hash(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


class AuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        # Fail startup if the append-only audit target is unavailable.
        descriptor = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        os.close(descriptor)

    def append(self, entry: dict) -> None:
        row = {
            "created_at": datetime.now(UTC).isoformat(),
            **entry,
        }
        encoded = (json.dumps(row, sort_keys=True, allow_nan=False) + "\n").encode()
        with self.lock:
            descriptor = os.open(
                self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600
            )
            try:
                written = os.write(descriptor, encoded)
                if written != len(encoded):
                    raise OSError("Incomplete audit append")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)


class ScoreAuditMiddleware:
    """Bound ingestion and buffer the response until its audit entry is durable."""

    def __init__(self, app, state):
        self.app = app
        self.state = state

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["path"] != "/score"
            or scope["method"] != "POST"
        ):
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        supplied = headers.get(b"x-request-id", b"").decode("latin-1")
        request_id = supplied if REQUEST_ID.fullmatch(supplied) else str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.perf_counter()
        body = bytearray()
        digest = hashlib.sha256()
        too_large = False
        declared = headers.get(b"content-length", b"")
        try:
            too_large = bool(declared) and int(declared) > MAX_BODY_BYTES
        except ValueError:
            pass  # Server rejects malformed lengths; actual bytes are still bounded.
        disconnected = False
        if not too_large:
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
            "input_hash": digest.hexdigest() if body or not too_large else None,
            "input_hash_scope": "prefix" if too_large else "complete",
            "model_version": self.state.model.version,
        }
        try:
            self.state.audit.append({**common, "event": "assessment_requested"})
            messages = []

            async def capture(message):
                messages.append(message)

            replayed = False

            async def replay():
                nonlocal replayed
                if not replayed:
                    replayed = True
                    return {
                        "type": "http.request",
                        "body": bytes(body),
                        "more_body": False,
                    }
                return {"type": "http.disconnect"}

            if too_large or disconnected:
                response = JSONResponse(
                    status_code=413 if too_large else 400,
                    content={
                        "detail": "Scoring body exceeds 5 MiB"
                        if too_large
                        else "Incomplete request body"
                    },
                )
                await response(scope, replay, capture)
            else:
                try:
                    await self.app(scope, replay, capture)
                except Exception:
                    messages.clear()
                    response = JSONResponse(
                        status_code=500,
                        content={
                            "detail": "Local scoring failed; no recommendation generated"
                        },
                    )
                    await response(scope, replay, capture)
            status = next(
                message["status"]
                for message in messages
                if message["type"] == "http.response.start"
            )
            self.state.audit.append(
                {
                    **common,
                    **scope["state"].get("result_metadata", {}),
                    "event": "assessment_completed"
                    if status == 200
                    else "assessment_failed",
                    "status": status,
                    "latency_ms": (time.perf_counter() - started) * 1000,
                }
            )
        except OSError:
            messages = []
            response = JSONResponse(
                status_code=503,
                content={
                    "detail": "Durable ML audit unavailable; no recommendation released"
                },
            )

            async def capture_failure(message):
                messages.append(message)

            await response(scope, receive, capture_failure)
        for message in messages:
            if message["type"] == "http.response.start":
                message["headers"] = message.get("headers", []) + [
                    (b"x-request-id", request_id.encode())
                ]
            await send(message)


def create_app(
    model_path: str | Path | None = None, audit_path: str | Path | None = None
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        chosen = model_path or os.environ.get("ML_MODEL_PATH", "runtime/model.joblib")
        try:
            application.state.model = ForecastModel.load(chosen)
        except Exception as error:
            raise RuntimeError(
                "Local model missing/corrupt. Run `uv run python -m capacity_ml.train`; "
                "startup never fabricates a recommendation."
            ) from error
        application.state.audit = AuditLog(
            audit_path or os.environ.get("ML_AUDIT_PATH", "runtime/audit.jsonl")
        )
        yield

    application = FastAPI(
        title="FlowCredit payment capacity ML",
        version="0.1.0",
        lifespan=lifespan,
    )

    application.add_middleware(ScoreAuditMiddleware, state=application.state)

    @application.get("/health")
    def health(request: Request) -> dict:
        model = request.app.state.model
        training = model.public_revenue_model.metadata
        return {
            "status": "ok",
            "model_version": request.app.state.model.version,
            "local_inference": True,
            "synthetic_training_only": False,
            "serving_mode": request.app.state.model.selection["serving_mode"],
            "public_transfer_weight": request.app.state.model.transfer_weight,
            "public_training_targets": training["training_examples"],
            "public_training_sources": training["sources"],
            "real_revenue_candidate": model.public_revenue_model.selected,
            "real_revenue_estimator_used": bool(
                model.transfer_weight and training["selected_uses_trained_estimator"]
            ),
            "expense_mode": model.selection.get("expense_mode", "synthetic_trained"),
            "provenance": "Licensed public revenue observations train the inflow component. Borrower demonstration transactions remain synthetic; public sources supply no borrower expenses or repayment/default labels.",
        }

    @application.post("/score", response_model=ScoreResponse)
    def score(payload: ScoreRequest, request: Request) -> ScoreResponse:
        result = score_request(
            payload, request.app.state.model, request.state.request_id
        )
        # Validate once again before both hashing the result and returning it.
        result = ScoreResponse.model_validate(result.model_dump())
        request.state.result_metadata = {
            "business_id": payload.business_id,
            "as_of_date": payload.as_of_date,
            "response_hash": canonical_hash(result.model_dump()),
            "capacity_score": result.capacity_score,
            "suggested_principal_index": result.recommended_loan.suggested_principal_index,
            "result": result.model_dump(),
        }
        return result

    return application


app = create_app()

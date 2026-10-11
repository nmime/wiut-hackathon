"""One validated /score endpoint with a durable audit for the assembled model."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from hybrid.scorer import HybridInputError
from teammate_bridge.schemas import ScoreResponse

from capacity_ml.api import AuditLog, ScoreAuditMiddleware, canonical_hash
from capacity_ml.schemas import ScoreRequest

REPOSITORY = Path(__file__).resolve().parents[2]
DEFAULT_BUNDLE = Path(__file__).with_name("artifacts")


def final_source_identity() -> dict[str, str]:
    """Fingerprint the final policy without changing the frozen training recipe."""
    paths = sorted(Path(__file__).parent.glob("*.py")) + sorted(
        (REPOSITORY / "teammate-ml-service" / "hybrid").glob("*.py")
    )
    paths += [
        REPOSITORY / "ml-service" / "capacity_ml" / "api.py",
        REPOSITORY / "ml-service" / "capacity_ml" / "schemas.py",
        REPOSITORY / "hybrid-runtime" / "uv.lock",
    ]
    return {
        str(path.relative_to(REPOSITORY)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }


def create_app(
    bundle_path: str | Path | None = None,
    audit_path: str | Path | None = None,
    *,
    provider_factory=None,
    engine_factory=None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        from hybrid.scorer import HybridEngine

        from .provider import load_provider

        engine = None
        try:
            provider = (provider_factory or load_provider)(
                Path(
                    bundle_path or os.environ.get("FINAL_MODEL_BUNDLE", DEFAULT_BUNDLE)
                )
            )
            engine = (engine_factory or HybridEngine)()
            identity = {
                "revenue": provider.identity,
                "financial_engine": engine.identity,
                "final_source": final_source_identity(),
                "policy": {"annual_rate": 0.24, "term_months": 12},
            }
            # Identity describes the complete assembly. Each constituent learned
            # artifact hash is retained separately in both health and audit.
            artifact_sha256 = canonical_hash(identity)
            version = f"final-v1-{artifact_sha256[:16]}"
            application.state.provider = provider
            application.state.engine = engine
            application.state.identity = json.loads(
                json.dumps(identity, allow_nan=False)
            )
            application.state.model = SimpleNamespace(version=version)
            application.state.model_artifact_sha256 = artifact_sha256
            application.state.health = {
                **json.loads(json.dumps(provider.health, allow_nan=False)),
                "status": "ok",
                "model_version": version,
                "model_artifact_sha256": artifact_sha256,
                "identity_scope": "complete_local_model_assembly",
                "component_identity": application.state.identity,
                "local_inference": True,
                "synthetic_training_only": False,
                "serving_mode": "final_combined_model",
                "annual_interest_rate": 0.24,
                "term_months": 12,
                "schedule_policy": "seasonal_discounted_payment_capacity",
                "verdicts": ["affordable", "elevated_risk", "decline"],
                "human_review_required": True,
            }
            application.state.audit = AuditLog(
                audit_path
                or os.environ.get("ML_AUDIT_PATH", "runtime/final-audit.jsonl")
            )
        except Exception as error:
            if engine is not None:
                engine.close()
            raise RuntimeError(
                "Final model startup failed: a frozen component, calibration, "
                "dependency or durable audit is unavailable. No model is retrained "
                "or substituted at startup."
            ) from error
        try:
            yield
        finally:
            engine.close()

    application = FastAPI(
        title="FlowCredit final payment capacity model",
        version="1.0.0",
        lifespan=lifespan,
    )
    application.add_middleware(ScoreAuditMiddleware, state=application.state)

    @application.exception_handler(HybridInputError)
    async def invalid_history(_request: Request, error: HybridInputError):
        return JSONResponse(
            status_code=422, content={"code": error.code, "detail": error.detail}
        )

    @application.get("/health")
    def health(request: Request) -> dict:
        return request.app.state.health

    @application.post("/score", response_model=ScoreResponse)
    def score(payload: ScoreRequest, request: Request) -> ScoreResponse:
        from hybrid.scorer import assess_request

        assessment = assess_request(
            payload,
            request.app.state.provider,
            request.state.request_id,
            engine=request.app.state.engine,
        )
        body = assessment["result"]
        if isinstance(body, ScoreResponse):
            body = body.model_dump()
        result = ScoreResponse.model_validate(
            {**body, "model_version": request.app.state.model.version}
        )
        evidence = assessment["evidence"]
        # Audit metadata is checked before middleware persists and releases the
        # response. Nonfinite/malformed evidence fails the assessment.
        canonical_hash(evidence)
        request.state.result_metadata = {
            "business_id": payload.business_id,
            "as_of_date": payload.as_of_date,
            "response_hash": canonical_hash(result.model_dump()),
            "capacity_score": result.capacity_score,
            "suggested_principal_index": result.recommended_loan.suggested_principal_index,
            "component_identity": request.app.state.identity,
            "financial_evidence": evidence,
            "result": result.model_dump(),
        }
        return result

    return application


app = create_app()

"""FastAPI service exposing the suspension damage prediction engine.

Run with:  uvicorn suspension_predictor.api.main:app --reload
Then open  http://127.0.0.1:8000/  for the demo web UI, or POST to
/v1/predict directly (see README for the request shape and a demo API key).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .. import billing, vehicle_specs
from ..engine import predict as run_prediction
from ..models import AlignmentReading
from .schemas import AlignmentReadingIn, DiagnosticReportOut

app = FastAPI(
    title="Suspension Damage Predictor API",
    description=(
        "Predicts likely damaged/worn suspension components from wheel "
        "alignment readings (camber, caster, SAI, toe). Decision-support "
        "only -- not a substitute for physical inspection."
    ),
    version="0.1.0",
)

# NOTE: wide-open CORS is convenient for the bundled demo UI / evaluation.
# Restrict allow_origins to your real front-end domain(s) before production use.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> dict:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header.")
    try:
        return billing.get_tenant(x_api_key)
    except billing.InvalidApiKey:
        raise HTTPException(status_code=401, detail="Invalid API key.")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/v1/vehicles")
def vehicles(tenant: dict = Depends(require_api_key)):
    """List the illustrative seed vehicles available for spec auto-lookup."""
    return {"vehicles": vehicle_specs.list_vehicles()}


@app.get("/v1/usage")
def usage(x_api_key: Optional[str] = Header(default=None), tenant: dict = Depends(require_api_key)):
    return {
        "plan": tenant.get("plan"),
        "monthly_quota": tenant.get("monthly_quota"),
        "usage_this_period": tenant.get("usage_this_period"),
    }


@app.post("/v1/predict", response_model=DiagnosticReportOut)
def predict(
    payload: AlignmentReadingIn,
    x_api_key: Optional[str] = Header(default=None),
    tenant: dict = Depends(require_api_key),
):
    # Enforce/track subscription usage.
    try:
        billing.check_and_increment_usage(x_api_key)
    except billing.QuotaExceeded as e:
        raise HTTPException(status_code=429, detail=str(e))
    except billing.InvalidApiKey:
        raise HTTPException(status_code=401, detail="Invalid API key.")

    front_spec = payload.front_spec.to_domain() if payload.front_spec else None
    rear_spec = payload.rear_spec.to_domain() if payload.rear_spec else None

    if front_spec is None or (payload.rear and rear_spec is None):
        looked_up = None
        if payload.vehicle and payload.vehicle.make and payload.vehicle.model:
            looked_up = vehicle_specs.lookup_spec(
                payload.vehicle.make, payload.vehicle.model, payload.vehicle.year
            )
        if front_spec is None:
            if looked_up and looked_up["front"]:
                front_spec = looked_up["front"]
            else:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "front_spec was not supplied and no matching seed vehicle spec was found. "
                        "Provide front_spec explicitly (recommended: copy it from the alignment "
                        "printout) or supply vehicle.make/model/year matching /v1/vehicles."
                    ),
                )
        if payload.rear and rear_spec is None:
            if looked_up and looked_up["rear"]:
                rear_spec = looked_up["rear"]
            # rear_spec staying None is fine -- rear axle just won't be analyzed.

    reading = AlignmentReading(
        front=payload.front.to_domain(),
        front_spec=front_spec,
        rear=payload.rear.to_domain() if payload.rear else None,
        rear_spec=rear_spec,
        vehicle=payload.vehicle.to_domain() if payload.vehicle else None,
    )

    report = run_prediction(reading)
    return DiagnosticReportOut.from_domain(report)


_web_dir = Path(__file__).resolve().parent.parent / "web"
if _web_dir.exists():
    app.mount("/", StaticFiles(directory=str(_web_dir), html=True), name="web")

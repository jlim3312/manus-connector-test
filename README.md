# Suspension Damage Predictor

Predicts **likely damaged or worn suspension components** from a wheel
alignment reading (camber, caster, SAI/KPI, toe), with a transparent
explanation for every finding. Built as a small SaaS-ready service so it can
be sold as a recurring subscription to insurance companies for claims
triage.

> **⚠️ Not a certified diagnosis.** This tool is decision-support software.
> It flags patterns in alignment geometry that commonly correspond to
> specific worn or damaged parts, ranked by confidence, so an adjuster or
> technician can triage faster — it does not replace a physical inspection,
> and no repair/replace/claim decision should be made from its output alone.
> See "Legal & liability notes" below before selling this commercially.

## What it does

Feed it the four numbers every alignment printout has per wheel — **camber,
caster, SAI, toe** — plus the OEM spec range printed on the same sheet, and
it returns a ranked list of findings like:

```
[Moderate 65%] front left: Bent strut, control arm, or subframe/frame (steering axis assembly shifted)
    Issue: Camber out of spec
    Why:   Left camber (-2.5, spec -1 to 0.5) and SAI (16.0, spec 12.5 to 14.5) are BOTH out of
           spec together. This combined shift of the whole steering axis is the classic signature
           of a bent strut, control arm, or subframe/frame damage -- frequently collision-related.
    Inspect: Strut, Control arm, Subframe/crossmember alignment, Frame rail (that corner)
```

### Diagnostic logic (why each rule exists)

| Pattern observed | Likely cause flagged |
|---|---|
| Camber out of spec, **SAI in spec** | Bent spindle/knuckle **mount**, worn ball joint/bushing, sagged spring, or bent strut — not the knuckle geometry itself |
| Camber **and** SAI both out of spec together | Whole steering-axis assembly has moved: bent strut, control arm, or subframe/frame — often collision-related |
| SAI out of spec, camber **normal** | Isolates to a **bent steering knuckle/spindle** (SAI is defined by knuckle geometry, camber isn't) |
| Caster out of spec, **one side only** | Bent strut rod/control arm or a shifted subframe on that corner (often collision) |
| Caster off similarly on **both sides** | More likely worn bushings, ride-height change, or a modified/aftermarket suspension |
| Cross-camber or cross-caster (L−R) exceeds tolerance | Asymmetric wear/damage even if each side is individually "in spec"; explains a pull complaint |
| Toe out of spec on **one corner only** | That corner's tie rod end / tie rod |
| Same-side front **and** rear findings | Unibody/frame damage pattern — recommend a structural/frame measurement, not just a parts swap |

Every `Finding` also carries a `severity` (Minor/Moderate/Severe, scaled by
how far outside the tolerance band the reading is) and a `confidence` score,
and the report sorts worst-first.

## Architecture

```
suspension_predictor/
  models.py        Plain dataclasses: SpecRange, CornerReading, AxleSpec,
                    AlignmentReading, Finding, DiagnosticReport
  engine.py         The rule engine (predict()) -- all diagnostic logic lives
                    here, fully unit-testable with no I/O
  vehicle_specs.py   Optional seed-catalog lookup (make/model/year -> spec)
  billing.py         Minimal API-key / quota store (subscription-gating stub)
  cli.py              `python -m suspension_predictor.cli reading.json`
  api/
    main.py           FastAPI app: /v1/predict, /v1/vehicles, /v1/usage
    schemas.py        Pydantic request/response models
  web/                Static demo UI (index.html/app.js/style.css), served
                      by the API at "/"
data/
  vehicle_specs.json  Illustrative seed spec catalog (see caveat below)
  api_keys.json       Demo tenant/quota store
tests/                pytest suite for the engine and the API
```

The engine (`engine.py`) has **zero dependencies** on FastAPI/pydantic — it
takes and returns plain dataclasses, so it can be embedded in a batch job,
a desktop tool, or a different web framework without dragging the API layer
along.

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run the tests
pytest -q

# CLI: see an example input, then run it
python -m suspension_predictor.cli --example > reading.json
python -m suspension_predictor.cli reading.json

# API + demo web UI
uvicorn suspension_predictor.api.main:app --reload
# open http://127.0.0.1:8000/  (demo API key: demo-key-123)
```

### API example

```bash
curl -X POST http://127.0.0.1:8000/v1/predict \
  -H "Content-Type: application/json" \
  -H "X-API-Key: demo-key-123" \
  -d '{
    "front": {
      "left":  {"camber": -1.6, "caster": 4.4, "sai": 13.4, "toe": 0.05},
      "right": {"camber": -0.3, "caster": 4.5, "sai": 13.5, "toe": 0.02}
    },
    "front_spec": {
      "camber": {"min": -1.0, "max": 0.5},
      "caster": {"min": 3.7, "max": 5.2},
      "sai":    {"min": 12.5, "max": 14.5},
      "toe":    {"min": -0.08, "max": 0.08}
    }
  }'
```

`front_spec`/`rear_spec` are optional **if** you instead pass
`vehicle: {make, model, year}` matching an entry in `/v1/vehicles` — the API
will auto-fill from the seed catalog. **In production, always prefer copying
the spec block straight off the alignment machine's own printout** (every
shop alignment system — Hunter, Bosch, Snap-on, John Bean — prints the exact
OEM min/max for the VIN being tested); the bundled catalog is only a
convenience fallback (see caveat below).

### Docker

```bash
docker build -t suspension-predictor .
docker run -p 8000:8000 suspension-predictor
```

## ⚠️ Data caveat: `data/vehicle_specs.json`

The bundled vehicle catalog is **illustrative seed data for ~10 common
models**, not a verified OEM database — the exact numbers are representative
of the vehicle class, not pulled from a licensed spec source. Before relying
on the auto-fill lookup for real claims:

1. Replace/expand it with data licensed from a real source (Mitchell1,
   ALLDATA, identifix, or direct OEM service data), **or**
2. Keep the "always pass `front_spec`/`rear_spec` from the printout" flow as
   primary, and treat the catalog purely as a demo/fallback convenience —
   this is the recommended path and is already how the CLI/API are designed
   to be used.

## Subscription / SaaS roadmap

This repo includes a minimal, working **gating scaffold** so the product
shape is obvious, but it is intentionally not a full billing system:

- `data/api_keys.json` + `billing.py` stand in for a real tenant database —
  swap for Postgres/DynamoDB + a real per-tenant table before launch.
- Wire up **Stripe Billing** (Checkout + Customer Portal + webhooks) to:
  issue API keys on successful subscription, suspend on payment failure,
  and reset `usage_this_period` on each billing-cycle webhook.
- Add per-tenant plans (e.g. Starter/Pro/Enterprise = monthly prediction
  quota + seats), enforced in `require_api_key`/`check_and_increment_usage`.
- Add audit logging (who ran what prediction, on which claim number, when) —
  insurers will want this for compliance review.
- Add bulk/batch ingestion (CSV or PDF upload of an alignment printout) so
  an adjuster can drop in a scanned report instead of typing numbers.
- Add auth beyond a bare API key (OAuth/SSO) if selling to enterprise
  insurance IT departments.

## Legal & liability notes (read before selling this)

- Keep the "decision-support, not a certified diagnosis" framing in your
  Terms of Service and in the UI (already in `DiagnosticReport.disclaimer`)
  — insurers will use this to triage claims, and the tool should never be
  the sole basis for denying/approving a claim or a repair.
- Consider carrying **E&O (errors & omissions) / tech liability insurance**
  once this is used in real claims workflows, and have counsel review your
  ToS/SLA before signing insurance-company customers.
- Validate the rule engine's real-world accuracy against outcomes from
  certified alignment technicians before marketing it as more than a triage
  aid — track a confusion matrix (predicted component vs. what the shop
  actually found) and tune severity/confidence thresholds from that data.

## Testing

```bash
pytest -q          # engine + API tests (16 tests)
```

`tests/test_engine.py` covers the core diagnostic rules in isolation (no
HTTP layer). `tests/test_api.py` drives the FastAPI app via `TestClient` and
isolates the billing store per test so it never mutates the shipped
`data/api_keys.json`.

"""Optional convenience lookup of seed OEM-style spec ranges by make/model/year.

IMPORTANT: the bundled data/vehicle_specs.json is illustrative seed data, not
a verified OEM database. In production, the spec range printed on the actual
alignment machine printout for the vehicle being inspected should always be
used (pass it directly in the request) -- this lookup exists mainly for demos,
testing, and as a fallback when a printout's spec block is missing/illegible.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .models import AxleSpec, SpecRange

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "vehicle_specs.json"


def _axle_spec_from_dict(d: Optional[dict]) -> Optional[AxleSpec]:
    if d is None:
        return None
    camber = SpecRange(*d["camber"])
    toe = SpecRange(*d["toe"])
    caster = SpecRange(*d["caster"]) if "caster" in d else None
    sai = SpecRange(*d["sai"]) if "sai" in d else None
    return AxleSpec(camber=camber, toe=toe, caster=caster, sai=sai)


def load_catalog() -> dict:
    with open(_DATA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def lookup_spec(make: str, model: str, year: Optional[int] = None) -> Optional[dict]:
    """Return {"front": AxleSpec, "rear": Optional[AxleSpec]} for the closest
    matching seed entry, or None if nothing matches."""
    catalog = load_catalog()
    make_l, model_l = make.strip().lower(), model.strip().lower()
    for entry in catalog["vehicles"]:
        if entry["make"].lower() != make_l or entry["model"].lower() != model_l:
            continue
        if year is not None:
            if not (entry.get("year_min", 0) <= year <= entry.get("year_max", 9999)):
                continue
        return {
            "front": _axle_spec_from_dict(entry["front"]),
            "rear": _axle_spec_from_dict(entry.get("rear")),
        }
    return None


def list_vehicles() -> list:
    catalog = load_catalog()
    return [
        {"make": e["make"], "model": e["model"], "year_min": e["year_min"], "year_max": e["year_max"]}
        for e in catalog["vehicles"]
    ]

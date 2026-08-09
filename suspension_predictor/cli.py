"""Command-line interface: feed it a JSON alignment reading, get a report.

Usage:
    python -m suspension_predictor.cli path/to/reading.json
    python -m suspension_predictor.cli --example   # print an example input file

Input JSON shape (front_spec required; front/rear measured values required;
rear/rear_spec optional):

{
  "vehicle": {"year": 2022, "make": "Toyota", "model": "Camry"},
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
}
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from .engine import predict
from .models import AlignmentReading, AxleReading, AxleSpec, CornerReading, SpecRange, VehicleInfo

EXAMPLE = {
    "vehicle": {"year": 2022, "make": "Toyota", "model": "Camry", "claim_number": "CLM-00123"},
    "front": {
        "left": {"camber": -1.6, "caster": 4.4, "sai": 13.4, "toe": 0.05},
        "right": {"camber": -0.3, "caster": 4.5, "sai": 13.5, "toe": 0.02},
    },
    "front_spec": {
        "camber": {"min": -1.0, "max": 0.5},
        "caster": {"min": 3.7, "max": 5.2},
        "sai": {"min": 12.5, "max": 14.5},
        "toe": {"min": -0.08, "max": 0.08},
    },
}


def _spec(d):
    return SpecRange(**d) if d else None


def _corner(d):
    return CornerReading(**d)


def _axle_spec(d):
    if d is None:
        return None
    return AxleSpec(
        camber=_spec(d["camber"]), toe=_spec(d["toe"]),
        caster=_spec(d.get("caster")), sai=_spec(d.get("sai")),
        cross_camber_max=d.get("cross_camber_max"), cross_caster_max=d.get("cross_caster_max"),
    )


def reading_from_dict(d: dict) -> AlignmentReading:
    return AlignmentReading(
        front=AxleReading(left=_corner(d["front"]["left"]), right=_corner(d["front"]["right"])),
        front_spec=_axle_spec(d["front_spec"]),
        rear=AxleReading(left=_corner(d["rear"]["left"]), right=_corner(d["rear"]["right"])) if "rear" in d else None,
        rear_spec=_axle_spec(d.get("rear_spec")),
        vehicle=VehicleInfo(**d["vehicle"]) if "vehicle" in d else None,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Predict suspension damage from an alignment reading.")
    parser.add_argument("input", nargs="?", help="Path to a JSON alignment reading file.")
    parser.add_argument("--example", action="store_true", help="Print an example input JSON and exit.")
    args = parser.parse_args(argv)

    if args.example or not args.input:
        json.dump(EXAMPLE, sys.stdout, indent=2)
        print()
        if not args.input:
            return 0
        return 0

    with open(args.input, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    reading = reading_from_dict(data)
    report = predict(reading)

    print(f"\n{report.summary}\n")
    if report.structural_flag:
        print(f"STRUCTURAL FLAG: {report.structural_explanation}\n")

    for f in report.findings:
        loc = " ".join(x for x in [f.axle, f.side] if x)
        print(f"[{f.severity:8s} {f.confidence:.0%}] {loc}: {f.component}")
        print(f"    Issue: {f.issue} (measured {f.measured}, spec {f.spec})")
        print(f"    Why:   {f.explanation}")
        if f.recommended_inspection:
            print(f"    Inspect: {', '.join(f.recommended_inspection)}")
        print()

    print(f"Disclaimer: {report.disclaimer}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

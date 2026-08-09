"""Data models for the suspension damage predictor.

All angles are decimal degrees. Camber/caster/SAI follow the shop convention:
positive camber = top of wheel tilted outward, positive caster = steering axis
tilted toward the rear at the top. Toe is total per-corner toe in degrees,
positive = toe-in.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


@dataclass
class SpecRange:
    """An OEM (or shop-supplied) acceptable range for a single measurement,
    exactly as printed on an alignment sheet."""

    min: float
    max: float
    preferred: Optional[float] = None

    def __post_init__(self) -> None:
        if self.min > self.max:
            raise ValueError(f"SpecRange min ({self.min}) cannot exceed max ({self.max})")

    def in_spec(self, value: float) -> bool:
        return self.min <= value <= self.max

    def deviation(self, value: float) -> float:
        """Signed distance outside the range. 0.0 if within spec."""
        if value < self.min:
            return value - self.min
        if value > self.max:
            return value - self.max
        return 0.0

    def width(self) -> float:
        return max(self.max - self.min, 1e-6)


@dataclass
class CornerReading:
    """Measured values for one wheel."""

    camber: float
    toe: float
    caster: Optional[float] = None  # usually only meaningful on steer axle
    sai: Optional[float] = None  # Steering Axis Inclination / KPI


@dataclass
class AxleSpec:
    """OEM spec ranges applied to both corners of an axle, as printed on the
    alignment sheet. Cross tolerances are optional; when omitted the engine
    falls back to the width of the individual spec range."""

    camber: SpecRange
    toe: SpecRange
    caster: Optional[SpecRange] = None
    sai: Optional[SpecRange] = None
    cross_camber_max: Optional[float] = None
    cross_caster_max: Optional[float] = None


@dataclass
class AxleReading:
    left: CornerReading
    right: CornerReading


@dataclass
class VehicleInfo:
    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    vin: Optional[str] = None
    claim_number: Optional[str] = None


@dataclass
class AlignmentReading:
    front: AxleReading
    front_spec: AxleSpec
    rear: Optional[AxleReading] = None
    rear_spec: Optional[AxleSpec] = None
    vehicle: Optional[VehicleInfo] = None


@dataclass
class Finding:
    axle: str  # "front" | "rear" | "front-rear" (cross-axle pattern)
    side: Optional[str]  # "left" | "right" | None for axle/vehicle-level findings
    parameter: str  # e.g. "camber", "caster", "sai", "toe", "cross-camber"
    measured: Optional[float]
    spec: Optional[str]
    component: str  # suspected component(s)
    issue: str  # short label
    explanation: str
    severity: str  # "Minor" | "Moderate" | "Severe"
    confidence: float  # 0.0 - 1.0
    recommended_inspection: List[str] = field(default_factory=list)


@dataclass
class DiagnosticReport:
    vehicle: Optional[VehicleInfo]
    findings: List[Finding]
    structural_flag: bool
    structural_explanation: Optional[str]
    summary: str
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    disclaimer: str = (
        "This report is a computer-generated, rule-based decision-support estimate derived "
        "solely from the submitted alignment angles. It identifies components that commonly "
        "explain the observed geometry and is NOT a certified diagnosis. A physical inspection "
        "by a qualified technician is required before any repair, replacement, or claim decision."
    )

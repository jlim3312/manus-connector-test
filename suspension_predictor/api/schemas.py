"""Pydantic request/response schemas for the HTTP API, plus conversion
helpers to/from the plain-dataclass domain models used by the engine."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from .. import models as m


class SpecRangeIn(BaseModel):
    min: float
    max: float
    preferred: Optional[float] = None

    def to_domain(self) -> m.SpecRange:
        return m.SpecRange(min=self.min, max=self.max, preferred=self.preferred)


class AxleSpecIn(BaseModel):
    camber: SpecRangeIn
    toe: SpecRangeIn
    caster: Optional[SpecRangeIn] = None
    sai: Optional[SpecRangeIn] = None
    cross_camber_max: Optional[float] = None
    cross_caster_max: Optional[float] = None

    def to_domain(self) -> m.AxleSpec:
        return m.AxleSpec(
            camber=self.camber.to_domain(),
            toe=self.toe.to_domain(),
            caster=self.caster.to_domain() if self.caster else None,
            sai=self.sai.to_domain() if self.sai else None,
            cross_camber_max=self.cross_camber_max,
            cross_caster_max=self.cross_caster_max,
        )


class CornerReadingIn(BaseModel):
    camber: float
    toe: float
    caster: Optional[float] = None
    sai: Optional[float] = None

    def to_domain(self) -> m.CornerReading:
        return m.CornerReading(camber=self.camber, toe=self.toe, caster=self.caster, sai=self.sai)


class AxleReadingIn(BaseModel):
    left: CornerReadingIn
    right: CornerReadingIn

    def to_domain(self) -> m.AxleReading:
        return m.AxleReading(left=self.left.to_domain(), right=self.right.to_domain())


class VehicleInfoIn(BaseModel):
    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    vin: Optional[str] = None
    claim_number: Optional[str] = None

    def to_domain(self) -> m.VehicleInfo:
        return m.VehicleInfo(
            year=self.year, make=self.make, model=self.model,
            vin=self.vin, claim_number=self.claim_number,
        )


class AlignmentReadingIn(BaseModel):
    front: AxleReadingIn
    front_spec: Optional[AxleSpecIn] = Field(
        default=None,
        description="Required unless vehicle make/model/year matches a seed lookup entry.",
    )
    rear: Optional[AxleReadingIn] = None
    rear_spec: Optional[AxleSpecIn] = None
    vehicle: Optional[VehicleInfoIn] = None


class FindingOut(BaseModel):
    axle: str
    side: Optional[str]
    parameter: str
    measured: Optional[float]
    spec: Optional[str]
    component: str
    issue: str
    explanation: str
    severity: str
    confidence: float
    recommended_inspection: List[str]

    @classmethod
    def from_domain(cls, f: m.Finding) -> "FindingOut":
        return cls(**f.__dict__)


class DiagnosticReportOut(BaseModel):
    vehicle: Optional[VehicleInfoIn]
    findings: List[FindingOut]
    structural_flag: bool
    structural_explanation: Optional[str]
    summary: str
    generated_at: str
    disclaimer: str

    @classmethod
    def from_domain(cls, r: m.DiagnosticReport) -> "DiagnosticReportOut":
        return cls(
            vehicle=VehicleInfoIn(**r.vehicle.__dict__) if r.vehicle else None,
            findings=[FindingOut.from_domain(f) for f in r.findings],
            structural_flag=r.structural_flag,
            structural_explanation=r.structural_explanation,
            summary=r.summary,
            generated_at=r.generated_at,
            disclaimer=r.disclaimer,
        )

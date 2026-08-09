"""Rule-based inference engine that turns alignment angles into a ranked list
of suspected damaged/worn suspension components.

Domain logic summary (standard wheel-alignment diagnostic principles):

- Camber out of spec while SAI (steering axis inclination) is IN spec usually
  means the strut/spindle/knuckle mounting point itself has shifted relative
  to the steering axis: bent spindle/knuckle, worn ball joint/control-arm
  bushing, sagged spring, or a bent strut -- not the steering axis itself.
- Camber AND SAI out of spec together (same direction) means the whole
  steering-axis assembly has moved: classic signature of a bent strut,
  control arm, or subframe/frame damage, often collision-related.
- SAI alone out of spec with camber normal points specifically at a bent
  steering knuckle/spindle, since SAI is defined by the knuckle geometry.
- Caster out of spec on one side only suggests a bent strut rod / control
  arm or a shifted subframe on that side (frequently collision damage).
  Caster off by a similar amount on BOTH sides more often reflects worn
  bushings, ride-height change, or an aftermarket suspension.
- Cross-camber / cross-caster (left-right difference) beyond tolerance
  causes pull and points at asymmetric wear or damage even when each side
  individually reads within its own spec window.
- Toe out of spec on one corner only implicates that corner's tie rod end
  or steering linkage; both toe out or both toe in on an axle points at
  tie rod adjustment/wear, a worn rack, or (on solid-linkage cars) the
  center link/idler arm.
- The same defect pattern appearing at both the front AND rear corner on
  the same side of the vehicle is a strong signal of unibody/frame damage
  rather than an isolated worn part, and is flagged separately.

This module is intentionally transparent/explainable (every Finding carries
its reasoning) since the output is meant to support, not replace, a
technician's physical inspection -- important for any claims/insurance use.
"""
from __future__ import annotations

from typing import List, Optional

from .models import (
    AlignmentReading,
    AxleReading,
    AxleSpec,
    CornerReading,
    DiagnosticReport,
    Finding,
    SpecRange,
)

SEVERITY_ORDER = {"Minor": 0, "Moderate": 1, "Severe": 2}


def _severity_and_confidence(deviation: float, width: float) -> tuple[str, float]:
    ratio = abs(deviation) / width
    if ratio <= 1.0:
        severity = "Minor"
    elif ratio <= 2.0:
        severity = "Moderate"
    else:
        severity = "Severe"
    confidence = min(0.95, 0.40 + 0.25 * ratio)
    return severity, round(confidence, 2)


def _fmt_spec(spec: SpecRange) -> str:
    return f"{spec.min:g} to {spec.max:g}"


def _diagnose_camber(side: str, corner: CornerReading, spec: AxleSpec, dev: float) -> Finding:
    severity, confidence = _severity_and_confidence(dev, spec.camber.width())
    direction = "positive (leaning out)" if dev > 0 else "negative (leaning in)"

    if corner.sai is not None and spec.sai is not None:
        sai_ok = spec.sai.in_spec(corner.sai)
        if sai_ok:
            component = "Strut, spindle/knuckle mount, control-arm bushing/ball joint, or sagged spring"
            explanation = (
                f"{side.title()} camber is {direction} and out of spec ({corner.camber:g}, "
                f"spec {_fmt_spec(spec.camber)}), but SAI reads within spec "
                f"({corner.sai:g}, spec {_fmt_spec(spec.sai)}). Camber moving independently of SAI "
                "points at the mounting point (strut/knuckle) or a worn/sagged component rather than "
                "the steering knuckle geometry itself."
            )
            inspect = ["Strut and strut mount", "Upper/lower control arm bushings", "Ball joints", "Spring height/sag"]
        else:
            component = "Bent strut, control arm, or subframe/frame (steering axis assembly shifted)"
            explanation = (
                f"{side.title()} camber ({corner.camber:g}, spec {_fmt_spec(spec.camber)}) and SAI "
                f"({corner.sai:g}, spec {_fmt_spec(spec.sai)}) are BOTH out of spec together. This "
                "combined shift of the whole steering axis is the classic signature of a bent strut, "
                "control arm, or subframe/frame damage -- frequently collision-related."
            )
            inspect = ["Strut", "Control arm", "Subframe/crossmember alignment", "Frame rail (that corner)"]
    else:
        component = "Control arm, ball joint, strut/spring, or bushings (bent/worn)"
        explanation = (
            f"{side.title()} camber is {direction} and out of spec ({corner.camber:g}, "
            f"spec {_fmt_spec(spec.camber)}). SAI was not provided, so a knuckle-vs-mounting "
            "distinction can't be made from geometry alone."
        )
        inspect = ["Strut", "Control arms", "Ball joints", "Bushings", "Spring height"]

    return Finding(
        axle="", side=side, parameter="camber", measured=corner.camber, spec=_fmt_spec(spec.camber),
        component=component, issue="Camber out of spec", explanation=explanation,
        severity=severity, confidence=confidence, recommended_inspection=inspect,
    )


def _diagnose_sai_alone(side: str, corner: CornerReading, spec: AxleSpec) -> Optional[Finding]:
    if corner.sai is None or spec.sai is None:
        return None
    if not spec.camber.in_spec(corner.camber):
        return None  # handled by the combined camber+SAI rule above
    sai_dev = spec.sai.deviation(corner.sai)
    if sai_dev == 0:
        return None
    severity, confidence = _severity_and_confidence(sai_dev, spec.sai.width())
    return Finding(
        axle="", side=side, parameter="sai", measured=corner.sai, spec=_fmt_spec(spec.sai),
        component="Bent steering knuckle/spindle",
        issue="SAI out of spec with camber normal",
        explanation=(
            f"{side.title()} SAI is out of spec ({corner.sai:g}, spec {_fmt_spec(spec.sai)}) while "
            f"camber reads normal ({corner.camber:g}). Because SAI is defined by the steering knuckle "
            "geometry and camber is not affected, this isolates the fault to a bent knuckle/spindle."
        ),
        severity=severity, confidence=confidence,
        recommended_inspection=["Steering knuckle", "Spindle"],
    )


def _diagnose_caster(side: str, other_side_in_spec: bool, corner: CornerReading, spec: AxleSpec, dev: float) -> Finding:
    severity, confidence = _severity_and_confidence(dev, spec.caster.width())
    if other_side_in_spec:
        component = "Bent strut rod, control arm, or shifted subframe (this side only)"
        note = (
            "Caster is off on this side only, which typically means a bent strut rod/control arm "
            "or a subframe that has shifted on this corner -- often collision-related."
        )
    else:
        component = "Worn control-arm bushings, ride-height change, or non-OEM suspension"
        note = (
            "Caster is off on both sides similarly, which more often reflects worn bushings, "
            "a ride-height change (sagged/aftermarket springs), or a modified suspension rather "
            "than one-sided impact damage."
        )
    return Finding(
        axle="", side=side, parameter="caster", measured=corner.caster, spec=_fmt_spec(spec.caster),
        component=component, issue="Caster out of spec",
        explanation=f"{side.title()} caster is {corner.caster:g} (spec {_fmt_spec(spec.caster)}). {note}",
        severity=severity, confidence=confidence,
        recommended_inspection=["Strut rod", "Lower control arm", "Control arm bushings", "Subframe position"],
    )


def _diagnose_toe(side: str, corner: CornerReading, spec: AxleSpec, dev: float) -> Finding:
    severity, confidence = _severity_and_confidence(dev, spec.toe.width())
    direction = "toe-in" if dev > 0 else "toe-out"
    return Finding(
        axle="", side=side, parameter="toe", measured=corner.toe, spec=_fmt_spec(spec.toe),
        component="Tie rod end / tie rod (bent or worn) or loose steering linkage on that corner",
        issue=f"Individual toe out of spec ({direction})",
        explanation=(
            f"{side.title()} toe is {corner.toe:g} (spec {_fmt_spec(spec.toe)}), off on this corner only. "
            "An isolated toe error almost always traces to that corner's tie rod end or tie rod."
        ),
        severity=severity, confidence=confidence,
        recommended_inspection=["Tie rod end", "Tie rod", "Steering rack mount (that side)"],
    )


def _analyze_axle(axle_name: str, reading: AxleReading, spec: AxleSpec) -> List[Finding]:
    findings: List[Finding] = []
    sides = {"left": reading.left, "right": reading.right}
    camber_in_spec = {s: spec.camber.in_spec(c.camber) for s, c in sides.items()}
    caster_in_spec = {}

    for side, corner in sides.items():
        dev = spec.camber.deviation(corner.camber)
        if dev != 0:
            findings.append(_diagnose_camber(side, corner, spec, dev))
        else:
            sai_finding = _diagnose_sai_alone(side, corner, spec)
            if sai_finding:
                findings.append(sai_finding)

        if spec.caster is not None and corner.caster is not None:
            dev = spec.caster.deviation(corner.caster)
            caster_in_spec[side] = dev == 0
        if spec.toe is not None:
            dev = spec.toe.deviation(corner.toe)
            if dev != 0:
                findings.append(_diagnose_toe(side, corner, spec, dev))

    if spec.caster is not None and reading.left.caster is not None and reading.right.caster is not None:
        for side, corner in sides.items():
            other = "right" if side == "left" else "left"
            dev = spec.caster.deviation(corner.caster)
            if dev != 0:
                other_ok = caster_in_spec.get(other, True)
                findings.append(_diagnose_caster(side, other_ok, corner, spec, dev))

    # cross-camber
    cross_camber = reading.left.camber - reading.right.camber
    cross_camber_tol = spec.cross_camber_max if spec.cross_camber_max is not None else spec.camber.width()
    if abs(cross_camber) > cross_camber_tol:
        severity, confidence = _severity_and_confidence(cross_camber, cross_camber_tol)
        findings.append(Finding(
            axle="", side=None, parameter="cross-camber", measured=round(cross_camber, 3),
            spec=f"max diff {cross_camber_tol:g}",
            component="Asymmetric wear/damage: control arm, spring height, or bent component (side with outlier camber)",
            issue="Cross-camber exceeds tolerance",
            explanation=(
                f"Left-right camber difference is {cross_camber:g} deg (tolerance {cross_camber_tol:g}). "
                "Excess cross-camber causes the vehicle to pull toward the side with more negative camber "
                "and indicates asymmetric suspension geometry between the two sides."
            ),
            severity=severity, confidence=confidence,
            recommended_inspection=["Compare left vs right ride height", "Control arms", "Springs"],
        ))

    # cross-caster
    if spec.caster is not None and reading.left.caster is not None and reading.right.caster is not None:
        cross_caster = reading.left.caster - reading.right.caster
        cross_caster_tol = spec.cross_caster_max if spec.cross_caster_max is not None else spec.caster.width()
        if abs(cross_caster) > cross_caster_tol:
            severity, confidence = _severity_and_confidence(cross_caster, cross_caster_tol)
            findings.append(Finding(
                axle="", side=None, parameter="cross-caster", measured=round(cross_caster, 3),
                spec=f"max diff {cross_caster_tol:g}",
                component="Bent strut rod/control arm or shifted subframe (side with outlier caster)",
                issue="Cross-caster exceeds tolerance",
                explanation=(
                    f"Left-right caster difference is {cross_caster:g} deg (tolerance {cross_caster_tol:g}). "
                    "Excess cross-caster causes a steering pull and commonly indicates one-sided impact "
                    "damage to a strut rod, control arm, or subframe."
                ),
                severity=severity, confidence=confidence,
                recommended_inspection=["Strut rod", "Control arm", "Subframe alignment"],
            ))

    for f in findings:
        f.axle = axle_name
    return findings


def _structural_pattern(front_findings: List[Finding], rear_findings: List[Finding]) -> tuple[bool, Optional[str]]:
    front_sides = {f.side for f in front_findings if f.side in ("left", "right") and f.parameter in ("camber", "caster")}
    rear_sides = {f.side for f in rear_findings if f.side in ("left", "right") and f.parameter in ("camber", "toe")}
    shared = front_sides & rear_sides
    if shared:
        side = ", ".join(sorted(shared))
        return True, (
            f"Both the front and rear corners on the {side} side show geometry out of spec. A matching "
            "front+rear pattern on the same side is a strong indicator of unibody/frame damage on that "
            "side rather than an isolated worn part -- recommend a frame/structural measurement before "
            "replacing individual suspension components."
        )
    return False, None


def predict(reading: AlignmentReading) -> DiagnosticReport:
    """Run the rule engine over a full alignment reading and produce a
    ranked, explainable diagnostic report."""

    front_findings = _analyze_axle("front", reading.front, reading.front_spec)
    rear_findings: List[Finding] = []
    if reading.rear is not None and reading.rear_spec is not None:
        rear_findings = _analyze_axle("rear", reading.rear, reading.rear_spec)

    all_findings = front_findings + rear_findings
    structural_flag, structural_explanation = _structural_pattern(front_findings, rear_findings)

    all_findings.sort(key=lambda f: (SEVERITY_ORDER.get(f.severity, 0), f.confidence), reverse=True)

    if not all_findings:
        summary = "All measured angles are within the supplied spec ranges. No suspension damage indicated."
    else:
        severe = sum(1 for f in all_findings if f.severity == "Severe")
        moderate = sum(1 for f in all_findings if f.severity == "Moderate")
        minor = sum(1 for f in all_findings if f.severity == "Minor")
        parts = []
        if severe:
            parts.append(f"{severe} severe")
        if moderate:
            parts.append(f"{moderate} moderate")
        if minor:
            parts.append(f"{minor} minor")
        summary = f"{len(all_findings)} finding(s): " + ", ".join(parts) + "."
        if structural_flag:
            summary += " Possible structural/frame damage pattern detected."

    return DiagnosticReport(
        vehicle=reading.vehicle,
        findings=all_findings,
        structural_flag=structural_flag,
        structural_explanation=structural_explanation,
        summary=summary,
    )

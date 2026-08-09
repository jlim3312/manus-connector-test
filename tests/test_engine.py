import pytest

from suspension_predictor.engine import predict
from suspension_predictor.models import (
    AlignmentReading,
    AxleReading,
    AxleSpec,
    CornerReading,
    SpecRange,
)

FRONT_SPEC = AxleSpec(
    camber=SpecRange(-1.0, 0.5, -0.25),
    caster=SpecRange(3.7, 5.2, 4.45),
    toe=SpecRange(-0.08, 0.08, 0.0),
    sai=SpecRange(12.5, 14.5, 13.5),
)
REAR_SPEC = AxleSpec(
    camber=SpecRange(-1.5, 0.0, -0.75),
    toe=SpecRange(0.02, 0.28, 0.15),
)


def make_reading(front_left, front_right, rear_left=None, rear_right=None):
    front = AxleReading(left=front_left, right=front_right)
    rear = None
    rear_spec = None
    if rear_left is not None and rear_right is not None:
        rear = AxleReading(left=rear_left, right=rear_right)
        rear_spec = REAR_SPEC
    return AlignmentReading(front=front, front_spec=FRONT_SPEC, rear=rear, rear_spec=rear_spec)


def test_all_in_spec_no_findings():
    reading = make_reading(
        CornerReading(camber=-0.25, caster=4.45, sai=13.5, toe=0.0),
        CornerReading(camber=-0.25, caster=4.45, sai=13.5, toe=0.0),
    )
    report = predict(reading)
    assert report.findings == []
    assert "No suspension damage indicated" in report.summary
    assert report.structural_flag is False


def test_camber_out_sai_in_spec_points_at_mount_not_knuckle():
    # Left camber way out of spec, SAI stays normal -> strut/mount/arm, not knuckle
    reading = make_reading(
        CornerReading(camber=-2.5, caster=4.45, sai=13.5, toe=0.0),
        CornerReading(camber=-0.25, caster=4.45, sai=13.5, toe=0.0),
    )
    report = predict(reading)
    camber_findings = [f for f in report.findings if f.parameter == "camber" and f.side == "left"]
    assert len(camber_findings) == 1
    f = camber_findings[0]
    assert "SAI" in f.explanation
    assert "spindle" in f.component.lower() or "strut" in f.component.lower() or "bushing" in f.component.lower()
    assert f.severity in ("Minor", "Moderate", "Severe")


def test_camber_and_sai_both_out_points_at_bent_strut_or_frame():
    reading = make_reading(
        CornerReading(camber=-2.5, caster=4.45, sai=16.0, toe=0.0),
        CornerReading(camber=-0.25, caster=4.45, sai=13.5, toe=0.0),
    )
    report = predict(reading)
    camber_findings = [f for f in report.findings if f.parameter == "camber" and f.side == "left"]
    assert len(camber_findings) == 1
    assert "steering axis" in camber_findings[0].explanation.lower()
    assert "frame" in camber_findings[0].component.lower() or "subframe" in camber_findings[0].component.lower() \
        or "strut" in camber_findings[0].component.lower()


def test_sai_alone_out_of_spec_flags_knuckle():
    reading = make_reading(
        CornerReading(camber=-0.25, caster=4.45, sai=16.0, toe=0.0),
        CornerReading(camber=-0.25, caster=4.45, sai=13.5, toe=0.0),
    )
    report = predict(reading)
    sai_findings = [f for f in report.findings if f.parameter == "sai"]
    assert len(sai_findings) == 1
    assert "knuckle" in sai_findings[0].component.lower()


def test_one_sided_caster_flags_bent_strut_rod():
    reading = make_reading(
        CornerReading(camber=-0.25, caster=6.5, sai=13.5, toe=0.0),
        CornerReading(camber=-0.25, caster=4.45, sai=13.5, toe=0.0),
    )
    report = predict(reading)
    caster_findings = [f for f in report.findings if f.parameter == "caster"]
    assert any("strut rod" in f.component.lower() or "subframe" in f.component.lower() for f in caster_findings)


def test_isolated_toe_flags_tie_rod():
    reading = make_reading(
        CornerReading(camber=-0.25, caster=4.45, sai=13.5, toe=0.5),
        CornerReading(camber=-0.25, caster=4.45, sai=13.5, toe=0.0),
    )
    report = predict(reading)
    toe_findings = [f for f in report.findings if f.parameter == "toe"]
    assert len(toe_findings) == 1
    assert "tie rod" in toe_findings[0].component.lower()


def test_matching_front_rear_same_side_flags_structural():
    reading = make_reading(
        CornerReading(camber=-2.5, caster=4.45, sai=13.5, toe=0.0),
        CornerReading(camber=-0.25, caster=4.45, sai=13.5, toe=0.0),
        CornerReading(camber=-2.5, toe=0.15),
        CornerReading(camber=-0.75, toe=0.15),
    )
    report = predict(reading)
    assert report.structural_flag is True
    assert "left" in report.structural_explanation.lower()


def test_cross_camber_exceeds_tolerance():
    tight_cross_spec = AxleSpec(
        camber=SpecRange(-1.0, 0.5, -0.25),
        caster=SpecRange(3.7, 5.2, 4.45),
        toe=SpecRange(-0.08, 0.08, 0.0),
        sai=SpecRange(12.5, 14.5, 13.5),
        cross_camber_max=0.5,
    )
    reading = AlignmentReading(
        front=AxleReading(
            left=CornerReading(camber=-0.9, caster=4.45, sai=13.5, toe=0.0),
            right=CornerReading(camber=0.4, caster=4.45, sai=13.5, toe=0.0),
        ),
        front_spec=tight_cross_spec,
    )
    report = predict(reading)
    cross = [f for f in report.findings if f.parameter == "cross-camber"]
    assert len(cross) == 1


def test_findings_sorted_by_severity_desc():
    reading = make_reading(
        CornerReading(camber=-0.6, caster=4.45, sai=13.5, toe=0.0),  # minor-ish
        CornerReading(camber=-4.0, caster=4.45, sai=13.5, toe=0.0),  # severe
    )
    report = predict(reading)
    severities = [f.severity for f in report.findings if f.parameter == "camber"]
    order = {"Severe": 2, "Moderate": 1, "Minor": 0}
    assert all(order[severities[i]] >= order[severities[i + 1]] for i in range(len(severities) - 1))

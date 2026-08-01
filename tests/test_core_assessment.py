# tests/test_core_assessment.py
import pytest

from hunter8_core.assessment import GradeAssessment, ScreenAssessment


def test_screen_assessment_accepts_bounded_integer():
    result = ScreenAssessment.from_payload(
        {"fit_score": 65, "reason": "Plausible match."}
    )
    assert result.fit_score == 65


@pytest.mark.parametrize("value", [-1, 101, True, "65", None])
def test_screen_assessment_rejects_invalid_score(value):
    with pytest.raises(ValueError, match="fit_score"):
        ScreenAssessment.from_payload({"fit_score": value, "reason": "x"})


def test_grade_assessment_accepts_complete_payload():
    result = GradeAssessment.from_payload({
        "grade": "A",
        "reasoning": "Strong evidence.",
        "archetype": "applied-ai",
        "comp_signal": "$200k+",
        "red_flags": ["sponsorship unknown"],
    })
    assert result.grade == "A"
    assert result.red_flags == ("sponsorship unknown",)


@pytest.mark.parametrize("grade", ["", "D", "A+", None, []])
def test_grade_assessment_rejects_invalid_grade(grade):
    with pytest.raises(ValueError, match="grade"):
        GradeAssessment.from_payload({
            "grade": grade,
            "reasoning": "r",
            "archetype": "a",
            "comp_signal": "",
            "red_flags": [],
        })


def test_grade_assessment_rejects_string_red_flags():
    with pytest.raises(ValueError, match="red_flags"):
        GradeAssessment.from_payload({
            "grade": "B",
            "reasoning": "r",
            "archetype": "a",
            "comp_signal": "",
            "red_flags": "sponsorship unknown",
        })

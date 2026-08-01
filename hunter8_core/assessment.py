# hunter8_core/assessment.py
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast


Grade = Literal["A", "B", "C"]


def _string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


@dataclass(frozen=True)
class ScreenAssessment:
    fit_score: int
    reason: str

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, Any]
    ) -> "ScreenAssessment":
        score = payload.get("fit_score")
        if isinstance(score, bool) or not isinstance(score, int):
            raise ValueError("fit_score must be an integer")
        if not 0 <= score <= 100:
            raise ValueError("fit_score must be between 0 and 100")
        return cls(fit_score=score, reason=_string(payload, "reason"))


@dataclass(frozen=True)
class GradeAssessment:
    grade: Grade
    reasoning: str
    archetype: str
    comp_signal: str
    red_flags: tuple[str, ...]

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, Any]
    ) -> "GradeAssessment":
        raw_grade = payload.get("grade")
        if not isinstance(raw_grade, str) or raw_grade not in {"A", "B", "C"}:
            raise ValueError("grade must be one of A, B, C")
        raw_flags = payload.get("red_flags")
        if (
            not isinstance(raw_flags, list)
            or not all(isinstance(flag, str) for flag in raw_flags)
        ):
            raise ValueError("red_flags must be a list of strings")
        return cls(
            grade=cast(Grade, raw_grade),
            reasoning=_string(payload, "reasoning"),
            archetype=_string(payload, "archetype"),
            comp_signal=_string(payload, "comp_signal"),
            red_flags=tuple(raw_flags),
        )

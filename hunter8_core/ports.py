# hunter8_core/ports.py
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from hunter8_core.models import (
    CompanyThesis,
    ConfirmedProfile,
    JobPosting,
    MatchAssessment,
    ProfileDraft,
    ProfileQuestion,
    RankedMatch,
    SourceConfig,
)


class JsonModel(Protocol):
    def chat_json(self, system: str, user: str) -> Mapping[str, Any]:
        ...


class ResumeToProfile(Protocol):
    def extract(self, document_text: str) -> ProfileDraft:
        ...


class QuestionPlanner(Protocol):
    def plan(self, draft: ProfileDraft) -> Sequence[ProfileQuestion]:
        ...


class CompanyRecommender(Protocol):
    def recommend(self, profile: ConfirmedProfile) -> CompanyThesis:
        ...


class CompanySource(Protocol):
    def fetch(
        self, config: SourceConfig, *, timeout: float = 20.0
    ) -> Sequence[JobPosting]:
        ...


class EvidenceRanker(Protocol):
    def assess(
        self, profile: ConfirmedProfile, posting: JobPosting
    ) -> MatchAssessment:
        ...


class ShortlistRanker(Protocol):
    def order(
        self, assessments: Sequence[MatchAssessment]
    ) -> Sequence[RankedMatch]:
        ...

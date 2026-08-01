from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class JobPosting:
    url: str
    company: str
    title: str
    location: str
    source: str
    ats: str | None = None
    posted_at: str | None = None
    description: str = ""
    canonical_url: str | None = None
    fetched_at: str | None = None


@dataclass(frozen=True)
class SourceConfig:
    ats: str
    board: str
    company: str

    def __post_init__(self) -> None:
        if not self.ats or not self.board or not self.company:
            raise ValueError("ats, board, and company must be non-empty")


EvidenceState = Literal["draft", "confirmed", "rejected"]
CompanyTier = Literal["core", "adjacent", "exploratory"]
VerificationStatus = Literal["verified", "pending", "rejected"]
ConstraintStatus = Literal["pass", "fail", "unknown"]


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    claim: str
    category: str
    source_excerpt: str
    source_locator: str
    source_hash: str
    confidence: float
    state: EvidenceState

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.state not in {"draft", "confirmed", "rejected"}:
            raise ValueError("state must be draft, confirmed, or rejected")


@dataclass(frozen=True)
class ProfileQuestion:
    key: str
    prompt: str
    reason: str


@dataclass(frozen=True)
class ProfileDraft:
    target_role_shapes: tuple[str, ...]
    hard_constraints: tuple[str, ...]
    preferred_work: tuple[str, ...]
    excluded_work: tuple[str, ...]
    evidence: tuple[EvidenceItem, ...]
    known_gaps: tuple[str, ...]
    employer_thesis: str


@dataclass(frozen=True)
class ConfirmedProfile:
    profile_id: str
    version: int
    target_role_shapes: tuple[str, ...]
    hard_constraints: tuple[str, ...]
    preferred_work: tuple[str, ...]
    excluded_work: tuple[str, ...]
    evidence: tuple[EvidenceItem, ...]
    known_gaps: tuple[str, ...]
    employer_thesis: str

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("profile version must be at least 1")
        if any(item.state != "confirmed" for item in self.evidence):
            raise ValueError("ConfirmedProfile accepts confirmed evidence only")


@dataclass(frozen=True)
class CompanyRecommendation:
    name: str
    tier: CompanyTier
    reason: str
    evidence_ids: tuple[str, ...]
    official_careers_url: str | None
    verification_status: VerificationStatus

    def __post_init__(self) -> None:
        if self.tier not in {"core", "adjacent", "exploratory"}:
            raise ValueError("tier must be core, adjacent, or exploratory")
        if self.verification_status not in {"verified", "pending", "rejected"}:
            raise ValueError(
                "verification_status must be verified, pending, or rejected"
            )


@dataclass(frozen=True)
class CompanyThesis:
    profile_id: str
    profile_version: int
    recommendations: tuple[CompanyRecommendation, ...]


@dataclass(frozen=True)
class WatchedCompany:
    name: str
    tier: CompanyTier
    careers_url: str
    source: SourceConfig
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.tier not in {"core", "adjacent", "exploratory"}:
            raise ValueError("tier must be core, adjacent, or exploratory")


@dataclass(frozen=True)
class ConstraintResult:
    constraint: str
    status: ConstraintStatus
    explanation: str

    def __post_init__(self) -> None:
        if self.status not in {"pass", "fail", "unknown"}:
            raise ValueError("status must be pass, fail, or unknown")


@dataclass(frozen=True)
class MatchAssessment:
    posting_url: str
    profile_id: str
    profile_version: int
    constraint_results: tuple[ConstraintResult, ...]
    score: int
    explanation: str
    evidence_ids: tuple[str, ...]
    tradeoffs: tuple[str, ...]
    uncertainties: tuple[str, ...]
    provider: str
    model: str

    def __post_init__(self) -> None:
        if isinstance(self.score, bool) or not isinstance(self.score, int):
            raise ValueError("score must be an integer")
        if not 0 <= self.score <= 100:
            raise ValueError("score must be between 0 and 100")
        if self.profile_version < 1:
            raise ValueError("profile_version must be at least 1")

    @property
    def constraint_status(self) -> ConstraintStatus:
        statuses = {result.status for result in self.constraint_results}
        if "fail" in statuses:
            return "fail"
        if "unknown" in statuses:
            return "unknown"
        return "pass"


@dataclass(frozen=True)
class RankedMatch:
    rank: int
    assessment: MatchAssessment

    def __post_init__(self) -> None:
        if self.rank < 1:
            raise ValueError("rank must be at least 1")

# tests/test_core_contracts.py
import pytest

from hunter8_core import (
    CompanyRecommendation,
    CompanyRecommender,
    CompanySource,
    CompanyThesis,
    ConfirmedProfile,
    ConstraintResult,
    EvidenceItem,
    EvidenceRanker,
    JobPosting,
    MatchAssessment,
    ProfileDraft,
    ProfileQuestion,
    QuestionPlanner,
    RankedMatch,
    ResumeToProfile,
    ShortlistRanker,
    SourceConfig,
    WatchedCompany,
)


def _evidence(state: str = "confirmed") -> EvidenceItem:
    return EvidenceItem(
        evidence_id="ev-1",
        claim="Built production agent systems.",
        category="experience",
        source_excerpt="Built production agent systems",
        source_locator="page 1, Vanguard",
        source_hash="sha256:abc",
        confidence=0.95,
        state=state,
    )


def _profile() -> ConfirmedProfile:
    return ConfirmedProfile(
        profile_id="profile-1",
        version=1,
        target_role_shapes=("agent infrastructure",),
        hard_constraints=("New York or remote",),
        preferred_work=("production ML",),
        excluded_work=("pure dashboarding",),
        evidence=(_evidence(),),
        known_gaps=("buy-side experience",),
        employer_thesis="AI systems roles near investment decisions.",
    )


def test_profile_draft_keeps_uncertainty_explicit():
    draft = ProfileDraft(
        target_role_shapes=("agent infrastructure",),
        hard_constraints=(),
        preferred_work=("production ML",),
        excluded_work=(),
        evidence=(_evidence("draft"),),
        known_gaps=("work authorization",),
        employer_thesis="",
    )
    assert draft.known_gaps == ("work authorization",)
    assert draft.evidence[0].state == "draft"


def test_confirmed_profile_requires_positive_version():
    with pytest.raises(ValueError, match="version"):
        ConfirmedProfile(
            profile_id="profile-1",
            version=0,
            target_role_shapes=(),
            hard_constraints=(),
            preferred_work=(),
            excluded_work=(),
            evidence=(),
            known_gaps=(),
            employer_thesis="",
        )


def test_confirmed_profile_rejects_unconfirmed_evidence():
    with pytest.raises(ValueError, match="confirmed evidence"):
        ConfirmedProfile(
            profile_id="profile-1",
            version=1,
            target_role_shapes=(),
            hard_constraints=(),
            preferred_work=(),
            excluded_work=(),
            evidence=(_evidence("draft"),),
            known_gaps=(),
            employer_thesis="",
        )


def test_company_thesis_links_reasons_to_evidence():
    thesis = CompanyThesis(
        profile_id="profile-1",
        profile_version=1,
        recommendations=(
            CompanyRecommendation(
                name="Acme Capital",
                tier="core",
                reason="Agent infrastructure maps to the candidate's work.",
                evidence_ids=("ev-1",),
                official_careers_url="https://acme.example/careers",
                verification_status="verified",
            ),
        ),
    )
    assert thesis.recommendations[0].evidence_ids == ("ev-1",)


def test_watched_company_requires_a_verified_source_config():
    company = WatchedCompany(
        name="Acme Capital",
        tier="core",
        careers_url="https://acme.example/careers",
        source=SourceConfig(
            ats="greenhouse", board="acme", company="Acme Capital"
        ),
        evidence_ids=("ev-1",),
    )
    assert company.source.board == "acme"


def test_match_assessment_exposes_constraint_precedence():
    assessment = MatchAssessment(
        posting_url="https://x/1",
        profile_id="profile-1",
        profile_version=1,
        constraint_results=(
            ConstraintResult(
                constraint="New York or remote",
                status="unknown",
                explanation="Location is not stated.",
            ),
            ConstraintResult(
                constraint="No sponsorship required",
                status="fail",
                explanation="Posting requires unrestricted authorization.",
            ),
        ),
        score=72,
        explanation="Strong role fit with a hard-constraint failure.",
        evidence_ids=("ev-1",),
        tradeoffs=("Industry transition",),
        uncertainties=("Compensation missing",),
        provider="ai-gateway",
        model="configured-model",
    )
    assert assessment.constraint_status == "fail"


def test_match_assessment_rejects_unbounded_score():
    with pytest.raises(ValueError, match="score"):
        MatchAssessment(
            posting_url="https://x/1",
            profile_id="profile-1",
            profile_version=1,
            constraint_results=(),
            score=101,
            explanation="",
            evidence_ids=(),
            tradeoffs=(),
            uncertainties=(),
            provider="ai-gateway",
            model="configured-model",
        )


def test_ranked_match_requires_one_based_rank():
    assessment = MatchAssessment(
        posting_url="https://x/1",
        profile_id="profile-1",
        profile_version=1,
        constraint_results=(),
        score=90,
        explanation="Strong fit.",
        evidence_ids=("ev-1",),
        tradeoffs=(),
        uncertainties=(),
        provider="ai-gateway",
        model="configured-model",
    )
    with pytest.raises(ValueError, match="rank"):
        RankedMatch(rank=0, assessment=assessment)


def test_question_and_posting_contracts_are_plain_values():
    question = ProfileQuestion(
        key="location",
        prompt="Which locations are acceptable?",
        reason="Location changes hard-constraint evaluation.",
    )
    posting = JobPosting(
        url="https://x/1",
        canonical_url="https://x/1",
        company="Acme",
        title="AI Engineer",
        location="New York",
        source="ats:greenhouse",
        fetched_at="2026-08-01T00:00:00+00:00",
    )
    assert question.key == "location"
    assert posting.canonical_url == posting.url


@pytest.mark.parametrize(
    ("protocol", "method_name"),
    [
        (ResumeToProfile, "extract"),
        (QuestionPlanner, "plan"),
        (CompanyRecommender, "recommend"),
        (CompanySource, "fetch"),
        (EvidenceRanker, "assess"),
        (ShortlistRanker, "order"),
    ],
)
def test_adapter_protocol_exports_have_locked_method_names(
    protocol, method_name
):
    assert callable(getattr(protocol, method_name))

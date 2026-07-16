# score.py
from __future__ import annotations

import re
from dataclasses import dataclass

from db import Job

_TITLE_INCLUDE = re.compile(
    r"\b("
    r"machine learning|ml|ai|artificial intelligence|applied scientist|"
    r"research engineer|applied research|mle|"
    r"agent|agentic|llm|nlp|deep learning|data scientist"
    r")\b",
    re.I,
)
_TITLE_EXCLUDE = re.compile(
    r"\b(intern|internship|sales|recruiter|marketing|account executive|"
    r"low-latency|hft|c\+\+ core)\b",
    re.I,
)
# US-remote or a US location; reject obviously non-US postings.
_US_LOCATION = re.compile(
    r"\b(remote|united states|usa|us\b|new york|nyc|san francisco|sf\b|"
    r"boston|austin|seattle|chicago|los angeles|philadelphia|washington|"
    r", ?(?:AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|"
    r"MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|"
    r"SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)\b)",
    re.I,
)
_NON_US = re.compile(
    r"\b(london|uk|united kingdom|canada|toronto|india|bangalore|singapore|"
    r"germany|berlin|france|paris|remote - emea|remote \(emea\))\b",
    re.I,
)


@dataclass
class Verdict:
    grade: str
    reasoning: str
    archetype: str
    comp_signal: str
    red_flags: list[str]


def passes_rules(job: Job) -> tuple[bool, str]:
    """Cheap deterministic pre-filter. Returns (survives, reason-if-dropped)."""
    title = job.title or ""
    if _TITLE_EXCLUDE.search(title):
        return False, f"title excluded: {title!r}"
    if not _TITLE_INCLUDE.search(title):
        return False, f"title not a target role: {title!r}"
    loc = job.location or ""
    if loc and _NON_US.search(loc) and not _US_LOCATION.search(loc):
        return False, f"location not US: {loc!r}"
    return True, ""

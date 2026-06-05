# profile.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import openpyxl


@dataclass
class CandidateProfile:
    full_name: str
    email: str
    phone: str
    linkedin: str
    github: str
    location_city: str
    work_authorized: str
    requires_sponsorship: str
    sponsorship_type: str
    gc_timeline: str
    years_experience: int
    highest_degree: str
    degree_field: str
    university: str
    grad_year: int
    salary_min: int
    willing_to_relocate: str

    @property
    def first_name(self) -> str:
        return self.full_name.split()[0]

    @property
    def last_name(self) -> str:
        return " ".join(self.full_name.split()[1:])


def load_profile(tracker_path: Path) -> CandidateProfile:
    wb = openpyxl.load_workbook(tracker_path)
    ws = wb["Profile"]
    data: dict[str, str | int] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] and row[1] is not None:
            data[str(row[0])] = row[1]
    return CandidateProfile(
        full_name=str(data.get("full_name", "")),
        email=str(data.get("email", "")),
        phone=str(data.get("phone", "")),
        linkedin=str(data.get("linkedin", "")),
        github=str(data.get("github", "")),
        location_city=str(data.get("location_city", "")),
        work_authorized=str(data.get("work_authorized", "Yes")),
        requires_sponsorship=str(data.get("requires_sponsorship", "Yes")),
        sponsorship_type=str(data.get("sponsorship_type", "")),
        gc_timeline=str(data.get("gc_timeline", "")),
        years_experience=int(data.get("years_experience", 0)),
        highest_degree=str(data.get("highest_degree", "")),
        degree_field=str(data.get("degree_field", "")),
        university=str(data.get("university", "")),
        grad_year=int(data.get("grad_year", 0)),
        salary_min=int(data.get("salary_min", 0)),
        willing_to_relocate=str(data.get("willing_to_relocate", "Yes")),
    )

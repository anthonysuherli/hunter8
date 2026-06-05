# tests/test_profile.py
from pathlib import Path
import pytest
from profile import CandidateProfile, load_profile


def test_load_profile_returns_dataclass(tmp_tracker):
    profile = load_profile(tmp_tracker)
    assert isinstance(profile, CandidateProfile)


def test_first_last_name_split(tmp_tracker):
    profile = load_profile(tmp_tracker)
    assert profile.first_name == "Anthony"
    assert profile.last_name == "Suherli"


def test_sponsorship_defaults_to_yes(tmp_tracker):
    profile = load_profile(tmp_tracker)
    assert profile.requires_sponsorship == "Yes"


@pytest.fixture
def tmp_tracker(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.create_sheet("Profile")
    wb.remove(wb.active)
    rows = [
        ("full_name", "Anthony Suherli"),
        ("email", "anthonysuherli@gmail.com"),
        ("phone", "+1 737-710-8210"),
        ("linkedin", "linkedin.com/in/suherli"),
        ("github", "github.com/anthonysuherli"),
        ("location_city", "Greater Philadelphia, PA"),
        ("work_authorized", "Yes"),
        ("requires_sponsorship", "Yes"),
        ("sponsorship_type", "H-1B transfer (non-cap)"),
        ("gc_timeline", "Green card pending ~mid-2027"),
        ("years_experience", 4),
        ("highest_degree", "Master's"),
        ("degree_field", "Financial Engineering"),
        ("university", "University of Southern California"),
        ("grad_year", 2019),
        ("salary_min", 150000),
        ("willing_to_relocate", "Yes"),
    ]
    ws.append(["key", "value"])
    for r in rows:
        ws.append(r)
    path = tmp_path / "tracker.xlsx"
    wb.save(path)
    return path

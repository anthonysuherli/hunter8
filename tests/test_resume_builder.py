# tests/test_resume_builder.py
from resume_builder import build_resume_pdf


def test_build_creates_pdf(tmp_path):
    md = tmp_path / "resume-tailored.md"
    md.write_text("# Anthony Suherli\n\n## Summary\n\nML Engineer.\n\n## Skills\n\n- Python\n")
    out = build_resume_pdf(md, tmp_path / "output")
    assert out.exists()
    assert out.suffix == ".pdf"
    assert out.stat().st_size > 1000


def test_build_uses_stem_as_filename(tmp_path):
    md = tmp_path / "resume-tailored.md"
    md.write_text("# Anthony\n")
    out = build_resume_pdf(md, tmp_path / "output")
    assert out.name == "resume-tailored.pdf"

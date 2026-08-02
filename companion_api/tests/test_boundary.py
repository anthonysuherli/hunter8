import ast
import re
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent

FORBIDDEN = {
    "db", "sources", "watchlist", "screen", "score", "discover", "analyze",
    "apply", "tracker", "triage", "calibrate", "handlers", "resume_builder",
    "sync_intent", "rubric", "claude_agent", "local_agent", "candidate_profile",
}


def _sources() -> list[Path]:
    files = [p for p in PKG.rglob("*.py") if ".venv" not in p.parts and "test_" not in p.name]
    assert files, "no source files found"
    return files


def test_never_imports_the_personal_runtime():
    for path in _sources():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                roots = {(node.module or "").split(".")[0]}
            else:
                continue
            assert not (roots & FORBIDDEN), (path, roots & FORBIDDEN)


def test_never_names_a_personal_artifact():
    pattern = re.compile(r"intent\.md|rubric\.md|brief\.md|hunter8\.db|watchlist\.yaml|resumes/")
    for path in _sources():
        assert not pattern.search(path.read_text()), path


def test_jwt_verification_is_delegated_not_reimplemented():
    """Re-implementing token verification is the one duplication we refuse."""
    auth = (PKG / "auth.py").read_text()
    assert "from delapan.api.auth import verify_bearer" in auth
    for banned in ("jwt.decode", "PyJWKClient", "HS256", "ES256"):
        assert banned not in auth, f"{banned} suggests a re-implementation"

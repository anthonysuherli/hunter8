import inspect

from companion_api import db


TOKEN_SCOPED = {"invite_by_token", "mark_invite_redeemed", "release_invite"}
UNSCOPED_BY_DESIGN = {"issue_invite"}


def test_every_helper_takes_an_explicit_user_or_token():
    """The service client bypasses RLS, so each helper must scope itself."""
    for name, fn in vars(db).items():
        if name.startswith("_") or not inspect.isfunction(fn):
            continue
        if getattr(fn, "__module__", None) != db.__name__ or name in UNSCOPED_BY_DESIGN:
            continue
        first = list(inspect.signature(fn).parameters)[0]
        expected = "token" if name in TOKEN_SCOPED else "user_id"
        assert first == expected, (name, first, expected)


def test_service_client_is_confined_to_this_module():
    from pathlib import Path

    pkg = Path(db.__file__).resolve().parent
    self_path = Path(__file__).resolve()
    for path in pkg.rglob("*.py"):
        if path.name == "db.py" or ".venv" in path.parts or path == self_path:
            continue
        assert "service_client" not in path.read_text(), path

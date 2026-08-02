import inspect

from companion_api import db


def test_every_helper_takes_an_explicit_user_or_token():
    """The service client bypasses RLS, so each helper must scope itself."""
    scoped = {"membership_for", "create_membership", "dossier_state"}
    for name in scoped:
        params = list(inspect.signature(getattr(db, name)).parameters)
        assert params and params[0] == "user_id", (name, params)


def test_service_client_is_confined_to_this_module():
    from pathlib import Path

    pkg = Path(db.__file__).resolve().parent
    self_path = Path(__file__).resolve()
    for path in pkg.rglob("*.py"):
        if path.name == "db.py" or ".venv" in path.parts or path == self_path:
            continue
        assert "service_client" not in path.read_text(), path

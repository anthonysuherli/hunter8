# companion_api/tests/test_deletion.py
from companion_api import deletion


def test_storage_is_cleared_before_the_auth_user():
    steps = deletion.deletion_plan("user-1")
    assert steps.index("storage") < steps.index("auth_user")
    assert steps.index("membership") < steps.index("auth_user")
    assert steps[-1] == "auth_user"


def test_domain_rows_are_deleted_before_membership():
    steps = deletion.deletion_plan("user-1")
    assert steps.index("domain_rows") < steps.index("membership")


def test_success_marks_done_and_reports_done(monkeypatch):
    marks: list[tuple[str, str]] = []
    monkeypatch.setattr(deletion, "_mark", lambda u, s, d=None: marks.append((u, s)))
    monkeypatch.setattr(deletion, "_run_step", lambda step, user_id: None)
    assert deletion.delete_everything("user-1") == "done"
    assert marks[0][1] == "delete_pending"
    assert marks[-1][1] == "done"


def test_a_failed_step_reports_delete_error_and_never_reports_done(monkeypatch):
    marks: list[tuple[str, str]] = []
    monkeypatch.setattr(deletion, "_mark", lambda u, s, d=None: marks.append((u, s)))

    def boom(step: str, user_id: str) -> None:
        if step == "domain_rows":
            raise RuntimeError("db unreachable")

    monkeypatch.setattr(deletion, "_run_step", boom)
    assert deletion.delete_everything("user-1") == "delete_error"
    assert [s for _, s in marks] == ["delete_pending", "delete_error"]
    assert "done" not in [s for _, s in marks]


def test_a_later_step_never_runs_after_a_failure(monkeypatch):
    ran: list[str] = []
    monkeypatch.setattr(deletion, "_mark", lambda u, s, d=None: None)

    def boom(step: str, user_id: str) -> None:
        ran.append(step)
        if step == "storage":
            raise RuntimeError("storage down")

    monkeypatch.setattr(deletion, "_run_step", boom)
    deletion.delete_everything("user-1")
    assert ran == ["storage"]


def test_rerunning_after_success_is_a_clean_no_op(monkeypatch):
    """Idempotence: every step is a delete-where-exists, so a second pass is safe."""
    monkeypatch.setattr(deletion, "_mark", lambda u, s, d=None: None)
    monkeypatch.setattr(deletion, "_run_step", lambda step, user_id: None)
    assert deletion.delete_everything("user-1") == "done"
    assert deletion.delete_everything("user-1") == "done"

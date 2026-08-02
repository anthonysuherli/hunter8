# companion_api/tests/test_deletion.py
from companion_api import db, deletion


def test_storage_is_cleared_before_the_auth_user():
    steps = deletion.deletion_plan("user-1")
    assert steps.index("storage") < steps.index("auth_user")
    assert steps.index("membership") < steps.index("auth_user")
    assert steps[-1] == "auth_user"


def test_domain_rows_are_deleted_before_membership():
    steps = deletion.deletion_plan("user-1")
    assert steps.index("domain_rows") < steps.index("membership")


def test_invites_are_deleted_after_membership_and_before_auth_user():
    """product_memberships.invite_token references invites(token) with no ON
    DELETE action, so invites must not be removed while a membership still
    points at them — and they must go before the auth user, since a redeemed
    invite's redeemed_by/redeemed_at CHECK collides with the auth-user delete."""
    steps = deletion.deletion_plan("user-1")
    assert steps.index("membership") < steps.index("invites") < steps.index("auth_user")


def test_success_marks_done_and_reports_done(monkeypatch):
    marks: list[tuple[str, str]] = []
    monkeypatch.setattr(deletion, "_mark", lambda u, s, d=None: marks.append((u, s)))
    monkeypatch.setattr(db, "mark_membership_deleting", lambda u: None)
    monkeypatch.setattr(deletion, "_run_step", lambda step, user_id: None)
    assert deletion.delete_everything("user-1") == "done"
    assert marks[0][1] == "delete_pending"
    assert marks[-1][1] == "done"


def test_a_failed_step_reports_delete_error_and_never_reports_done(monkeypatch):
    marks: list[tuple[str, str]] = []
    monkeypatch.setattr(deletion, "_mark", lambda u, s, d=None: marks.append((u, s)))
    monkeypatch.setattr(db, "mark_membership_deleting", lambda u: None)

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
    monkeypatch.setattr(db, "mark_membership_deleting", lambda u: None)

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
    monkeypatch.setattr(db, "mark_membership_deleting", lambda u: None)
    monkeypatch.setattr(deletion, "_run_step", lambda step, user_id: None)
    assert deletion.delete_everything("user-1") == "done"
    assert deletion.delete_everything("user-1") == "done"


def test_the_gate_failing_reports_delete_error_and_never_runs_a_step(monkeypatch):
    """F4: closing the upload gate happens before any destructive step. If it
    fails, the run must stop there rather than continue deleting."""
    marks: list[tuple[str, str]] = []
    ran: list[str] = []
    monkeypatch.setattr(deletion, "_mark", lambda u, s, d=None: marks.append((u, s)))

    def boom(u: str) -> None:
        raise RuntimeError("gate write failed")

    monkeypatch.setattr(db, "mark_membership_deleting", boom)
    monkeypatch.setattr(deletion, "_run_step", lambda step, user_id: ran.append(step))
    assert deletion.delete_everything("user-1") == "delete_error"
    assert [s for _, s in marks] == ["delete_pending", "delete_error"]
    assert ran == []


def test_exception_text_never_reaches_the_persisted_detail(monkeypatch):
    """F5: Postgres errors routinely embed row values, and detail is a
    permanent audit column — only the exception type name may be persisted."""
    details: list[str | None] = []
    monkeypatch.setattr(
        deletion, "_mark", lambda u, s, d=None: details.append(d)
    )
    monkeypatch.setattr(db, "mark_membership_deleting", lambda u: None)

    def boom(step: str, user_id: str) -> None:
        raise RuntimeError("Key (user_id)=(super-secret-row-value) already exists")

    monkeypatch.setattr(deletion, "_run_step", boom)
    deletion.delete_everything("user-1")
    assert all(d is None or "super-secret-row-value" not in d for d in details)
    assert details[-1] == "storage: RuntimeError"


def test_step_dispatch_calls_the_right_helper_in_plan_order(monkeypatch):
    """F7: every prior test monkeypatches _run_step away, so a mis-wired
    dispatch branch (e.g. calling the wrong db helper, or one step calling
    another's helper) would pass silently. Patch the six db functions
    deletion.py actually dispatches to and assert the call sequence matches
    the plan order exactly."""
    calls: list[str] = []
    monkeypatch.setattr(deletion, "_mark", lambda u, s, d=None: None)
    monkeypatch.setattr(db, "mark_membership_deleting", lambda u: calls.append("gate"))
    monkeypatch.setattr(db, "clear_storage_objects", lambda u: calls.append("storage"))
    monkeypatch.setattr(db, "delete_domain_rows", lambda u: calls.append("domain_rows"))
    monkeypatch.setattr(db, "delete_membership", lambda u: calls.append("membership"))
    monkeypatch.setattr(db, "delete_invites_for", lambda u: calls.append("invites"))
    monkeypatch.setattr(db, "delete_auth_user", lambda u: calls.append("auth_user"))

    assert deletion.delete_everything("user-1") == "done"
    assert calls == ["gate", *deletion.deletion_plan("user-1")]

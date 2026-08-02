from __future__ import annotations

from fastapi import APIRouter, Depends

from companion_api.auth import require_membership
from companion_api.deletion import delete_everything

router = APIRouter()


@router.delete("/account")
def delete_account(user_id: str = Depends(require_membership)):
    """One action. Returns the terminal state; a delete_error is retryable and
    is never reported as done."""
    return {"state": delete_everything(user_id)}

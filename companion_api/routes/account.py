from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from companion_api.auth import require_membership_or_deleting
from companion_api.deletion import delete_everything

router = APIRouter()


@router.delete("/account")
def delete_account(user_id: str = Depends(require_membership_or_deleting)):
    """One action. The body carries the terminal state either way; the status
    distinguishes them so a client checking only the code cannot read a failed
    erasure as success. 503 because a delete_error is retryable."""
    state = delete_everything(user_id)
    return JSONResponse(
        status_code=200 if state == "done" else 503, content={"state": state}
    )

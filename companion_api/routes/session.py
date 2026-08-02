from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from companion_api import auth

router = APIRouter()


class RedeemBody(BaseModel):
    token: str


@router.get("/session")
def read_session(request: Request, user_id: str = Depends(auth.require_membership)):
    row = auth.membership_for(user_id) or {}
    return {"user_id": user_id, "email": row.get("email"), "state": row.get("state")}


@router.post("/session/redeem")
def redeem(body: RedeemBody, request: Request):
    """The one route a member-less identity may call. Invite checks run inside
    redeem_invite BEFORE any product row exists."""
    user_id = auth.current_user(request)
    auth.redeem_invite(body.token, user_id)
    return {"state": "active"}

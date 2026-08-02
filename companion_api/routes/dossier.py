from __future__ import annotations

from fastapi import APIRouter, Depends

from companion_api.auth import require_membership
from companion_api.db import dossier_state

router = APIRouter()


@router.get("/dossier")
def read_dossier(user_id: str = Depends(require_membership)):
    """Persisted progress for the caller only. The pipeline that fills these
    rows is child plans 3-4; this returns whatever exists."""
    return dossier_state(user_id)

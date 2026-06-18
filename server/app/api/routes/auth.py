"""
Authentication endpoints — the frontend's Auth.js calls these to register and
verify users. The frontend has no database; this server owns all user state.
"""
from fastapi import APIRouter, HTTPException

from app.auth.users import (
    EmailAlreadyExists,
    create_user,
    verify_credentials,
)
from app.models.schemas import (
    RegisterAuthRequest,
    UserPublic,
    VerifyAuthRequest,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserPublic, status_code=201)
def register(req: RegisterAuthRequest) -> dict:
    """Create a new account. Returns the public user info (no password hash)."""
    from app.models.schemas import Role
    try:
        return create_user(
            email=req.email,
            name=req.name,
            password=req.password,
            role=Role(req.role),
        )
    except EmailAlreadyExists:
        raise HTTPException(status_code=409, detail="An account with that email already exists.")


@router.post("/verify", response_model=UserPublic | None)
def verify(req: VerifyAuthRequest) -> dict | None:
    """Credential check. Returns the public user info on success, null on
    failure. Auth.js uses this from its credentials provider's authorize()."""
    return verify_credentials(req.email, req.password)

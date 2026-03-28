"""Authentication endpoints — register, login, me, logout."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.auth.jwt_handler import create_access_token, decode_access_token, oauth2_scheme
from app.auth.password import hash_password, verify_password
from app.db.token_blocklist import TokenBlocklist
from app.db.user_store import UserStore
from app.dependencies import get_current_user, get_token_blocklist, get_user_store
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserMeResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    body: RegisterRequest,
    store: UserStore = Depends(get_user_store),
):
    existing = await store.get_by_email(body.email)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.")
    user = await store.create_user(body.email, hash_password(body.password))
    token = create_access_token(user.user_id, user.email)
    return TokenResponse(access_token=token, user_id=user.user_id, email=user.email)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    store: UserStore = Depends(get_user_store),
):
    user = await store.get_by_email(body.email)
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(user.user_id, user.email)
    return TokenResponse(access_token=token, user_id=user.user_id, email=user.email)


@router.get("/me", response_model=UserMeResponse)
async def me(current_user: User = Depends(get_current_user)):
    return UserMeResponse(user_id=current_user.user_id, email=current_user.email)


@router.post("/logout", status_code=204)
async def logout(
    token: str = Depends(oauth2_scheme),
    blocklist: TokenBlocklist = Depends(get_token_blocklist),
):
    """Revoke the current JWT so it can no longer be used even before it expires."""
    from jose import JWTError
    try:
        payload = decode_access_token(token)
        jti: str = payload.get("jti", "")
        exp: int | None = payload.get("exp")
        if jti and exp:
            expires_at = datetime.utcfromtimestamp(exp)
            await blocklist.block(jti, expires_at)
    except JWTError:
        pass  # already invalid — nothing to revoke

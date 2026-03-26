"""Authentication endpoints — register, login, me."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.jwt_handler import create_access_token
from app.auth.password import hash_password, verify_password
from app.db.user_store import UserStore
from app.dependencies import get_current_user, get_user_store
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

"""Authentication, token rotation, user profile, and cold-start onboarding routes."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from typing import Any, Literal, cast

import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.deps import get_current_user
from app.models import RefreshToken, User
from app.schemas.api import (
    AuthResponse,
    GoogleAuthRequest,
    LoginRequest,
    OnboardingRequest,
    RegisterRequest,
    UserOut,
)
from app.security import (
    REFRESH_COOKIE_NAME,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    hash_token,
    limiter,
    verify_password,
)
from app.services.recommender_service import recommender_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _split_csv(val: str) -> list[str]:
    return [x.strip() for x in (val or "").split(",") if x.strip()]


def _to_user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        username=user.username,
        role=user.role,
        avatar_url=user.avatar_url,
        auth_provider=user.auth_provider,
        preferred_genres=_split_csv(user.preferred_genres),
        preferred_industries=_split_csv(user.preferred_industries),
        onboarding_completed=user.onboarding_completed,
        created_at=user.created_at,
    )


def _sanitize_avatar_url(raw_url: Any) -> str | None:
    if not isinstance(raw_url, str):
        return None
    cleaned = raw_url.strip()
    if cleaned.startswith("https://") and len(cleaned) <= 500:
        return cleaned
    return None


def _allocate_unique_username(db: Session, raw_name: str, email: str) -> str:
    seed = re.sub(r"[^a-zA-Z0-9_.-]+", "_", (raw_name or email.split("@")[0]).strip())
    seed = seed.strip("._-")
    if len(seed) < 3:
        seed = f"viewer_{seed}" if seed else "cinema_viewer"
    base = seed[:30]
    candidate = base
    for _ in range(10):
        exists = db.scalar(select(User.id).where(User.username == candidate))
        if exists is None:
            return candidate
        candidate = f"{base[:24]}_{secrets.token_hex(2)}"
    return f"viewer_{secrets.token_hex(4)}"


def verify_google_id_token(credential: str, audience: str) -> dict[str, Any]:
    """Verify Google OAuth ID token signature, issuer, expiry, and audience."""
    return cast(
        dict[str, Any],
        id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            audience=audience,
        ),
    )


def _revoke_cookie_refresh_token(ac_refresh_token: str | None, db: Session) -> None:
    if not ac_refresh_token:
        return
    try:
        payload = decode_refresh_token(ac_refresh_token)
        jti = str(payload.get("jti", ""))
    except jwt.PyJWTError:
        return
    if jti:
        stored = db.scalar(select(RefreshToken).where(RefreshToken.jti == jti))
        if stored and not stored.revoked:
            stored.revoked = True
            db.flush()


def _issue_tokens(user: User, db: Session, response: Response) -> AuthResponse:
    settings = get_settings()
    access = create_access_token(user.id, user.role)
    raw_refresh, jti, expires_at = create_refresh_token(user.id)

    db.add(
        RefreshToken(
            user_id=user.id,
            jti=jti,
            token_hash=hash_token(raw_refresh),
            revoked=False,
            expires_at=expires_at,
        )
    )
    db.commit()

    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw_refresh,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=cast(Literal["lax", "strict", "none"], settings.cookie_samesite),
        max_age=settings.refresh_token_expire_days * 86400,
        path="/api/auth",
    )
    return AuthResponse(
        access_token=access,
        expires_in=settings.access_token_expire_minutes * 60,
        user=_to_user_out(user),
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
def register(
    request: Request,
    payload: RegisterRequest,
    response: Response,
    db: Session = Depends(get_db),
    ac_refresh_token: str | None = Cookie(default=None),
) -> AuthResponse:
    email_norm = payload.email.strip().lower()
    username_norm = payload.username.strip()

    existing_email = db.scalar(select(User).where(User.email == email_norm))
    existing_username = db.scalar(select(User).where(User.username == username_norm))
    if existing_email or existing_username:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with these details already exists",
        )

    _revoke_cookie_refresh_token(ac_refresh_token, db)
    user = User(
        email=email_norm,
        username=username_norm,
        password_hash=hash_password(payload.password),
        role="user",
        is_active=True,
        onboarding_completed=False,
    )
    db.add(user)
    db.flush()
    return _issue_tokens(user, db, response)


@router.post("/login", response_model=AuthResponse)
@limiter.limit("15/minute")
def login(
    request: Request,
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
    ac_refresh_token: str | None = Cookie(default=None),
) -> AuthResponse:
    email_norm = payload.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email_norm))
    if user is None or not user.is_active or user.role == "historical":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if user.password_hash is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account uses Google Sign-In. Please click Continue with Google.",
        )
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    _revoke_cookie_refresh_token(ac_refresh_token, db)
    return _issue_tokens(user, db, response)


@router.post("/google", response_model=AuthResponse)
@limiter.limit("15/minute")
def google_sign_in(
    request: Request,
    payload: GoogleAuthRequest,
    response: Response,
    db: Session = Depends(get_db),
    ac_refresh_token: str | None = Cookie(default=None),
) -> AuthResponse:
    settings = get_settings()
    if not settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google authentication is not configured",
        )

    try:
        info = verify_google_id_token(payload.credential, settings.google_client_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired Google credential",
        ) from exc

    issuer = str(info.get("iss") or "")
    audience = str(info.get("aud") or "")
    sub = str(info.get("sub") or "").strip()
    email_raw = str(info.get("email") or "").strip().lower()
    email_verified = info.get("email_verified") is True

    if (
        issuer not in {"accounts.google.com", "https://accounts.google.com"}
        or audience != settings.google_client_id
        or not email_verified
        or not sub
        or not email_raw
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google account verification failed",
        )

    safe_avatar = _sanitize_avatar_url(info.get("picture"))
    display_name = str(info.get("name") or "")
    _revoke_cookie_refresh_token(ac_refresh_token, db)

    user = db.scalar(select(User).where(User.google_sub == sub))
    if user is not None:
        if not user.is_active or user.role == "historical":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired Google credential",
            )
        if safe_avatar and user.avatar_url != safe_avatar:
            user.avatar_url = safe_avatar
        return _issue_tokens(user, db, response)

    existing_email = db.scalar(select(User).where(User.email == email_raw))
    if existing_email is not None:
        if not existing_email.is_active or existing_email.role == "historical":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired Google credential",
            )
        if existing_email.google_sub and existing_email.google_sub != sub:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This email is already associated with another Google account",
            )
        existing_email.google_sub = sub
        existing_email.auth_provider = "both" if existing_email.password_hash else "google"
        if safe_avatar and not existing_email.avatar_url:
            existing_email.avatar_url = safe_avatar
        return _issue_tokens(existing_email, db, response)

    username = _allocate_unique_username(db, display_name, email_raw)
    new_user = User(
        email=email_raw,
        username=username,
        password_hash=None,
        google_sub=sub,
        avatar_url=safe_avatar,
        auth_provider="google",
        role="user",
        is_active=True,
        onboarding_completed=False,
    )
    db.add(new_user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Account conflict during Google sign-in",
        ) from exc
    return _issue_tokens(new_user, db, response)


@router.get("/session")
def check_session(
    db: Session = Depends(get_db),
    ac_refresh_token: str | None = Cookie(default=None),
) -> dict[str, bool]:
    if not ac_refresh_token:
        return {"has_session": False}
    try:
        payload = decode_refresh_token(ac_refresh_token)
        jti = str(payload["jti"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return {"has_session": False}

    stored = db.scalar(select(RefreshToken).where(RefreshToken.jti == jti))
    if stored is None or stored.revoked or stored.token_hash != hash_token(ac_refresh_token):
        return {"has_session": False}
    exp = stored.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return {"has_session": exp >= datetime.now(timezone.utc)}


@router.post("/refresh", response_model=AuthResponse)
@limiter.limit("30/minute")
def refresh_session(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    ac_refresh_token: str | None = Cookie(default=None),
) -> AuthResponse:
    if not ac_refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    try:
        payload = decode_refresh_token(ac_refresh_token)
        user_id = int(payload["sub"])
        jti = str(payload["jti"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session") from exc

    stored = db.scalar(select(RefreshToken).where(RefreshToken.jti == jti))
    if stored is None or stored.token_hash != hash_token(ac_refresh_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")

    # Reuse detection: revoke all refresh tokens for this user if an already-revoked token is replayed
    if stored.revoked:
        db.query(RefreshToken).filter(RefreshToken.user_id == user_id).update({"revoked": True})
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session revoked")

    exp = stored.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < datetime.now(timezone.utc):
        stored.revoked = True
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")

    user = db.get(User, user_id)
    if user is None or not user.is_active or user.role == "historical":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")

    # Rotate: revoke current token and issue a fresh pair
    stored.revoked = True
    return _issue_tokens(user, db, response)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    db: Session = Depends(get_db),
    ac_refresh_token: str | None = Cookie(default=None),
) -> None:
    settings = get_settings()
    if ac_refresh_token:
        try:
            payload = decode_refresh_token(ac_refresh_token)
            jti = str(payload.get("jti", ""))
            if jti:
                stored = db.scalar(select(RefreshToken).where(RefreshToken.jti == jti))
                if stored:
                    stored.revoked = True
                    db.commit()
        except jwt.PyJWTError:
            pass
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path="/api/auth",
        httponly=True,
        secure=settings.cookie_secure,
        samesite=cast(Literal["lax", "strict", "none"], settings.cookie_samesite),
    )


@router.get("/me", response_model=UserOut)
def get_me(user: User = Depends(get_current_user)) -> UserOut:
    return _to_user_out(user)


@router.put("/onboarding", response_model=UserOut)
def update_onboarding(
    payload: OnboardingRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserOut:
    user.preferred_genres = ",".join(dict.fromkeys(g.strip() for g in payload.preferred_genres if g.strip()))
    user.preferred_industries = ",".join(payload.preferred_industries)
    user.onboarding_completed = True
    db.commit()
    db.refresh(user)
    recommender_service.invalidate_user_cache(user.id)
    return _to_user_out(user)

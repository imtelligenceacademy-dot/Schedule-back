from datetime import timedelta, timezone
import hashlib
import secrets
from threading import BoundedSemaphore

import jwt
from fastapi import Depends, HTTPException, Request
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import AuthSession, User, utcnow

password_hasher = PasswordHash.recommended()
dummy_hash = password_hasher.hash(secrets.token_urlsafe(32))
password_slots = BoundedSemaphore(2)


def hash_password(password):
    # Bound concurrent Argon2 memory usage for the Render Free instance.
    with password_slots:
        return password_hasher.hash(password)


def verify_password(password, hashed):
    with password_slots:
        return password_hasher.verify(password, hashed)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def create_token(db, user):
    settings = get_settings()
    now = utcnow()
    expires = now + timedelta(hours=settings.session_hours)
    session_id = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    db.add(AuthSession(id=session_id, user_id=user.id, expires_at=expires))
    token = jwt.encode(
        {
            "sub": str(user.id),
            "jti": session_id,
            "csrf": csrf,
            "ver": user.token_version,
            "iat": now,
            "exp": expires,
            "iss": "im-telligence-schedule",
            "aud": "schedule-users",
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    return token, csrf


def authenticated_user(request: Request, db: Session = Depends(get_db)):
    authorization = request.headers.get("Authorization", "")
    bearer = authorization.startswith("Bearer ")
    token = authorization[7:] if bearer else request.cookies.get("schedule_session")
    if not token:
        raise HTTPException(401, "Please sign in to continue.")
    try:
        claims = jwt.decode(
            token,
            get_settings().jwt_secret,
            algorithms=["HS256"],
            issuer="im-telligence-schedule",
            audience="schedule-users",
            options={"require": ["exp", "sub", "jti", "csrf", "ver"]},
        )
        user = db.get(User, int(claims["sub"]))
        session = db.get(AuthSession, claims["jti"])
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise HTTPException(401, "Your session has expired. Please sign in again.")
    if (
        not user
        or not user.active
        or user.token_version != claims["ver"]
        or not session
        or session.revoked
        or session.user_id != user.id
        or aware(session.expires_at) <= utcnow()
    ):
        raise HTTPException(401, "Your session is no longer valid. Please sign in again.")
    if not bearer and request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf = request.headers.get("X-CSRF-Token", "")
        if not secrets.compare_digest(csrf, claims["csrf"]):
            raise HTTPException(403, "Invalid security token. Refresh and try again.")
    request.state.claims = claims
    return user


def current_user(user: User = Depends(authenticated_user)):
    if user.must_change_password:
        raise HTTPException(403, "Change your temporary password before continuing.")
    return user


def editor(user: User = Depends(current_user)):
    if user.role not in {"ADMIN", "SUPER_ADMIN"}:
        raise HTTPException(403, "Your account has view-only access.")
    return user


def super_admin(user: User = Depends(current_user)):
    if user.role != "SUPER_ADMIN":
        raise HTTPException(403, "Only a Super Admin can perform this action.")
    return user


def exporter(user: User = Depends(current_user)):
    if user.role == "VIEWER" and not user.export_allowed:
        raise HTTPException(403, "Export is not enabled for your account.")
    return user


def throttle_key(value):
    return hashlib.sha256(value.encode()).hexdigest()

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuthSession, LoginThrottle, User, utcnow
from ..schemas import LoginInput, PasswordInput
from ..security import authenticated_user, aware, create_token, dummy_hash, hash_password, throttle_key, verify_password
from ..services import audit, commit, snapshot
from .common import set_session_cookie, settings, user_view

# Public: sign-in must work without a session; the other routes authenticate individually.
router = APIRouter(prefix="/api/auth")


@router.post("/login")
def login(data: LoginInput, response: Response, db: Session = Depends(get_db)):
    email = str(data.email).strip().lower()
    key = throttle_key(email)
    now = utcnow()
    row = db.get(LoginThrottle, key)
    if row is None:
        db.add(LoginThrottle(key=key, attempts=0, window_start=now))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    row = db.scalar(select(LoginThrottle).where(LoginThrottle.key == key).with_for_update())
    if aware(row.window_start) < now - timedelta(minutes=15):
        row.attempts = 0
        row.window_start = now
    if row.attempts >= 10:
        raise HTTPException(429, "Too many sign-in attempts. Try again in 15 minutes.")
    row.attempts += 1
    db.commit()
    user = db.scalar(select(User).where(User.email == email))
    valid = verify_password(data.password, user.password_hash if user else dummy_hash)
    if not user or not valid or not user.active:
        raise HTTPException(401, "Email or password is incorrect.")
    db.execute(update(LoginThrottle).where(LoginThrottle.key == key).values(attempts=0))
    user.last_login = now
    token, csrf = create_token(db, user)
    audit(db, user, "sign_in", user)
    commit(db)
    set_session_cookie(response, token)
    return {"user": user_view(user), "csrf_token": csrf, "access_token": token}


@router.get("/me")
def me(request: Request, user: User = Depends(authenticated_user)):
    return {"user": user_view(user), "csrf_token": request.state.claims["csrf"]}


@router.post("/logout")
def logout(
    request: Request, response: Response, user: User = Depends(authenticated_user), db: Session = Depends(get_db)
):
    row = db.get(AuthSession, request.state.claims["jti"])
    row.revoked = True
    commit(db)
    response.delete_cookie("schedule_session", path="/api", secure=settings.production, httponly=True, samesite="lax")
    return {"message": "Signed out."}


@router.post("/password")
def change_password(
    data: PasswordInput, response: Response, user: User = Depends(authenticated_user), db: Session = Depends(get_db)
):
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(422, "Current password is incorrect.")
    if data.current_password == data.new_password:
        raise HTTPException(422, "Choose a different password.")
    old = snapshot(user)
    user.password_hash = hash_password(data.new_password)
    user.must_change_password = False
    user.token_version += 1
    token, csrf = create_token(db, user)
    audit(db, user, "password_changed", user, old)
    commit(db)
    set_session_cookie(response, token)
    return {"user": user_view(user), "csrf_token": csrf, "access_token": token}

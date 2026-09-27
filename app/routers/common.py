from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ..config import get_settings
from ..security import current_user
from ..services import snapshot

settings = get_settings()


def protected_router():
    """Router for data routes; every route requires an authenticated user."""
    return APIRouter(prefix="/api", dependencies=[Depends(current_user)])


def user_view(user):
    return {key: value for key, value in snapshot(user).items() if key != "password_hash"}


def set_session_cookie(response: Response, token: str):
    response.set_cookie(
        "schedule_session",
        token,
        httponly=True,
        secure=settings.production,
        samesite="lax",
        max_age=settings.session_hours * 3600,
        path="/api",
    )


def filters(
    academic_year_id: int | None = None,
    # Each list filter accepts repeated values (?teacher_id=1&teacher_id=2) and matches any of them.
    school_id: list[int] | None = Query(None, max_length=100),
    teacher_id: list[int] | None = Query(None, max_length=100),
    day: list[int] | None = Query(None, max_length=7),
    grade: list[str] | None = Query(None, max_length=100),
    class_id: list[int] | None = Query(None, max_length=200),
    search: str | None = Query(None, max_length=150),
):
    if day and any(not 0 <= x <= 6 for x in day):
        raise HTTPException(422, "Days must be between 0 (Monday) and 6 (Sunday).")
    return dict(
        academic_year_id=academic_year_id,
        school_id=school_id,
        teacher_id=teacher_id,
        day=day,
        grade=grade,
        class_id=class_id,
        search=search,
    )

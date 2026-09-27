from fastapi import APIRouter, Depends, Query, Response

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
    school_id: int | None = None,
    teacher_id: int | None = None,
    day: int | None = Query(None, ge=0, le=6),
    grade: str | None = None,
    class_id: int | None = None,
    search: str | None = Query(None, max_length=150),
):
    return dict(
        academic_year_id=academic_year_id,
        school_id=school_id,
        teacher_id=teacher_id,
        day=day,
        grade=grade,
        class_id=class_id,
        search=search,
    )

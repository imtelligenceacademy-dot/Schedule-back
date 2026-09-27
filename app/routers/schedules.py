from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AcademicYear, ScheduleEntry, School, Teacher, User, utcnow
from ..schemas import SessionInput, SessionUpdate
from ..security import editor, super_admin
from ..services import audit, commit, conflicts, find, minutes, sessions, snapshot, validate_session, writable_year
from .common import filters, protected_router, settings

router = protected_router()


@router.get("/sessions")
@router.get("/schedules")
def list_sessions(params: dict = Depends(filters), db: Session = Depends(get_db)):
    return sessions(db, **params)


@router.get("/sessions/{session_id}")
@router.get("/schedules/{session_id}")
def get_session(session_id: int, db: Session = Depends(get_db)):
    row = find(db, ScheduleEntry, session_id)
    return next(x for x in sessions(db, academic_year_id=row.academic_year_id) if x["id"] == session_id)


@router.post("/sessions", status_code=201)
@router.post("/schedules", status_code=201)
def create_session(data: SessionInput, user: User = Depends(editor), db: Session = Depends(get_db)):
    validate_session(db, data)
    row = ScheduleEntry(**data.model_dump(), created_by=user.id, updated_by=user.id)
    db.add(row)
    audit(db, user, "create", row)
    commit(db)
    return get_session(row.id, db)


@router.put("/sessions/{session_id}")
@router.put("/schedules/{session_id}")
def update_session(session_id: int, data: SessionUpdate, user: User = Depends(editor), db: Session = Depends(get_db)):
    row = find(db, ScheduleEntry, session_id)
    writable_year(db, row.academic_year_id)
    if row.version != data.expected_version:
        raise HTTPException(409, "This schedule entry was modified by another user. Refresh before saving.")
    validate_session(db, data)
    old = snapshot(row)
    for key, value in data.model_dump(exclude={"expected_version"}).items():
        setattr(row, key, value)
    row.updated_by = user.id
    # Force a versioned UPDATE even when another user submits identical values.
    row.updated_at = utcnow()
    audit(db, user, "update", row, old)
    commit(db)
    return get_session(row.id, db)


@router.delete("/sessions/{session_id}")
@router.delete("/schedules/{session_id}")
def delete_session(
    session_id: int,
    expected_version: int = Query(gt=0),
    user: User = Depends(super_admin),
    db: Session = Depends(get_db),
):
    row = find(db, ScheduleEntry, session_id)
    writable_year(db, row.academic_year_id)
    if row.version != expected_version:
        raise HTTPException(409, "This schedule entry was modified by another user. Refresh before deleting.")
    audit(db, user, "delete", row, snapshot(row))
    db.delete(row)
    commit(db)
    return {"message": "Session deleted."}


@router.get("/conflicts")
def list_conflicts(academic_year_id: int | None = None, db: Session = Depends(get_db)):
    return conflicts(sessions(db, academic_year_id=academic_year_id))


@router.get("/dashboard")
@router.get("/dashboard/stats")
def dashboard(academic_year_id: int, db: Session = Depends(get_db)):
    year = find(db, AcademicYear, academic_year_id)
    entries = sessions(db, academic_year_id=year.id)
    now = datetime.now(ZoneInfo(settings.timezone))
    active_date = year.start_date <= now.date() <= year.end_date
    today = [x for x in entries if active_date and x["day"] == now.weekday()]
    upcoming = []
    for entry in entries:
        distance = (entry["day"] - now.weekday()) % 7
        if distance == 0 and entry["start_time"] <= now.strftime("%H:%M"):
            distance = 7
        next_date = now.date() + timedelta(days=distance)
        while next_date < year.start_date:
            next_date += timedelta(days=7)
        if year.start_date <= next_date <= year.end_date:
            upcoming.append({**entry, "next_date": next_date.isoformat()})
    school_groups, teacher_groups = {}, {}
    for entry in entries:
        for groups, name, color in [
            (school_groups, entry["school_name"], entry["school_color"]),
            (teacher_groups, entry["teacher_name"], entry["school_color"]),
        ]:
            # IDs prevent teachers with identical names from being combined.
            key = entry["school_id"] if groups is school_groups else entry["teacher_id"]
            group = groups.setdefault(key, {"id": key, "name": name, "color": color, "sessions": 0, "minutes": 0})
            group["sessions"] += 1
            group["minutes"] += minutes(entry["end_time"]) - minutes(entry["start_time"])
    return {
        "active_schools": db.scalar(select(func.count()).select_from(School).where(School.active)),
        "teachers": db.scalar(select(func.count()).select_from(Teacher).where(Teacher.active)),
        "weekly_sessions": len(entries),
        "weekly_hours": round(sum(minutes(x["end_time"]) - minutes(x["start_time"]) for x in entries) / 60, 1),
        "conflicts": len(conflicts(entries)),
        "today": today,
        "upcoming": sorted(upcoming, key=lambda x: (x["next_date"], x["start_time"]))[:12],
        "by_school": list(school_groups.values()),
        "by_teacher": list(teacher_groups.values()),
        "date": now.date().isoformat(),
        "timezone": settings.timezone,
    }

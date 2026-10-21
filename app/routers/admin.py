import secrets

from fastapi import Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AcademicYear, AuditLog, AuthSession, User, utcnow
from ..schemas import ResetPassword, UserCreate, UserUpdate, YearInput, YearUpdate
from ..security import hash_password, super_admin
from ..services import audit, commit, snapshot, user_label, writable_year
from .common import protected_router, user_view

router = protected_router()


@router.post("/years", status_code=201)
def add_year(data: YearInput, user: User = Depends(super_admin), db: Session = Depends(get_db)):
    row = AcademicYear(**data.model_dump(), active=False, archived=False)
    db.add(row)
    audit(db, user, "create", row)
    commit(db)
    return snapshot(row)


@router.post("/years/{year_id}/activate")
def activate_year(year_id: int, user: User = Depends(super_admin), db: Session = Depends(get_db)):
    row = writable_year(db, year_id)
    for old_year in db.scalars(select(AcademicYear).where(AcademicYear.active)):
        old = snapshot(old_year)
        old_year.active = False
        old_year.active_slot = None
        audit(db, user, "deactivate", old_year, old)
    db.flush()
    old = snapshot(row)
    row.active = True
    row.active_slot = 1
    audit(db, user, "activate", row, old)
    commit(db)
    return snapshot(row)


@router.put("/years/{year_id}")
def archive_year(year_id: int, data: YearUpdate, user: User = Depends(super_admin), db: Session = Depends(get_db)):
    row = db.scalar(select(AcademicYear).where(AcademicYear.id == year_id).with_for_update())
    if not row:
        raise HTTPException(404, "Academic year not found.")
    if data.archived and row.active:
        raise HTTPException(409, "Activate another academic year before archiving the current year.")
    old = snapshot(row)
    row.archived = data.archived
    audit(db, user, "archive" if data.archived else "restore", row, old)
    commit(db)
    return snapshot(row)


def live_user(db, user_id):
    row = db.get(User, user_id)
    if not row or row.deleted_at:
        raise HTTPException(404, "User not found.")
    return row


@router.get("/users")
def list_users(user: User = Depends(super_admin), db: Session = Depends(get_db)):
    return [
        user_view(row) for row in db.scalars(select(User).where(User.deleted_at.is_(None)).order_by(User.full_name))
    ]


@router.post("/users", status_code=201)
def add_user(data: UserCreate, user: User = Depends(super_admin), db: Session = Depends(get_db)):
    row = User(
        full_name=data.full_name,
        email=str(data.email).lower(),
        role=data.role,
        export_allowed=data.export_allowed,
        password_hash=hash_password(data.temporary_password),
        must_change_password=True,
    )
    db.add(row)
    audit(db, user, "create", row)
    commit(db)
    return user_view(row)


@router.put("/users/{user_id}")
def edit_user(user_id: int, data: UserUpdate, user: User = Depends(super_admin), db: Session = Depends(get_db)):
    row = live_user(db, user_id)
    if row.id == user.id and (not data.active or data.role != "SUPER_ADMIN"):
        raise HTTPException(409, "You cannot disable or demote your own Super Admin account.")
    old = snapshot(row)
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    if old["role"] != row.role or old["active"] != row.active:
        row.token_version += 1
    audit(db, user, "update", row, old)
    commit(db)
    return user_view(row)


@router.post("/users/{user_id}/reset-password")
def reset_user_password(
    user_id: int, data: ResetPassword, user: User = Depends(super_admin), db: Session = Depends(get_db)
):
    row = live_user(db, user_id)
    if row.id == user.id:
        raise HTTPException(422, "Use Change password for your own account.")
    old = snapshot(row)
    row.password_hash = hash_password(data.temporary_password)
    row.must_change_password = True
    row.token_version += 1
    audit(db, user, "password_reset", row, old)
    commit(db)
    return {"message": "Temporary password set. Existing sessions have been revoked."}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, user: User = Depends(super_admin), db: Session = Depends(get_db)):
    row = live_user(db, user_id)
    if row.id == user.id:
        raise HTTPException(409, "You cannot delete your own account.")
    old = snapshot(row)
    # Keep the row (and name) for history, but make the account unusable and free its email.
    row.deleted_at = utcnow()
    row.active = False
    row.export_allowed = False
    row.email = f"deleted-{row.id}@deleted.invalid"
    row.password_hash = hash_password(secrets.token_urlsafe(32))
    row.token_version += 1
    db.execute(update(AuthSession).where(AuthSession.user_id == row.id).values(revoked=True))
    audit(db, user, "delete", row, old)
    commit(db)
    return {"message": "User deleted."}


@router.get("/audit")
def list_audit(
    user: User = Depends(super_admin),
    db: Session = Depends(get_db),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    q = (
        select(AuditLog, User.full_name, User.deleted_at)
        .join(User)
        .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
    )
    return {
        "items": [
            {**snapshot(row), "user_name": user_label(name, deleted_at)}
            for row, name, deleted_at in db.execute(q.offset(offset).limit(limit))
        ],
        "total": db.scalar(select(func.count()).select_from(AuditLog)),
    }

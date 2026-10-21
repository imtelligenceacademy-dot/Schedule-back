from datetime import date, datetime
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from .models import AcademicYear, AuditLog, School, SchoolClass, ScheduleEntry, Teacher, TeacherSchoolAssignment, User

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def snapshot(row):
    result = {}
    for col in row.__table__.columns:
        if col.name in {"password_hash", "token_version"}:
            continue
        value = getattr(row, col.name)
        result[col.name] = value.isoformat() if isinstance(value, (date, datetime)) else value
    return result


def audit(db, user, action, row, old=None):
    db.flush()
    db.add(
        AuditLog(
            user_id=user.id,
            action=action,
            entity_type=row.__tablename__,
            entity_id=row.id,
            old_value=old,
            new_value=None if action == "delete" else snapshot(row),
        )
    )


def commit(db):
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        raise HTTPException(409, "This schedule entry was modified by another user. Refresh before saving.")
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409,
            "This change conflicts with an existing record or a teacher/school assignment. Refresh and check your data.",
        )


def find(db, model, entity_id):
    row = db.get(model, entity_id)
    if not row:
        raise HTTPException(404, "Record not found.")
    return row


def writable_year(db, entity_id):
    row = db.scalar(select(AcademicYear).where(AcademicYear.id == entity_id).with_for_update())
    if not row:
        raise HTTPException(404, "Academic year not found.")
    if row.archived:
        raise HTTPException(409, "This academic year is archived and is read-only.")
    return row


def validate_session(db, data):
    writable_year(db, data.academic_year_id)
    school = find(db, School, data.school_id)
    teacher = find(db, Teacher, data.teacher_id)
    school_class = find(db, SchoolClass, data.class_id)
    if not school.active or not teacher.active:
        raise HTTPException(422, "Select an active school and teacher.")
    if school_class.school_id != school.id:
        raise HTTPException(422, "The selected class does not belong to this school.")
    assignment = db.scalar(
        select(TeacherSchoolAssignment).where(
            TeacherSchoolAssignment.teacher_id == teacher.id,
            TeacherSchoolAssignment.academic_year_id == data.academic_year_id,
        )
    )
    if not assignment or assignment.school_id != school.id:
        raise HTTPException(
            422,
            "This teacher must be assigned to this school for the selected academic year. One teacher can only have one school per year.",
        )


def user_label(full_name, deleted_at):
    """Name shown in history; deleted accounts keep their name with a marker."""
    return f"{full_name} (deleted)" if deleted_at else full_name


def session_query(
    academic_year_id=None, school_id=None, teacher_id=None, day=None, grade=None, class_id=None, search=None
):
    q = (
        select(ScheduleEntry, School, Teacher, SchoolClass, User.full_name, User.deleted_at)
        .join(School, ScheduleEntry.school_id == School.id)
        .join(Teacher, ScheduleEntry.teacher_id == Teacher.id)
        .join(SchoolClass, ScheduleEntry.class_id == SchoolClass.id)
        .join(User, ScheduleEntry.updated_by == User.id)
    )
    for field, value in [
        (ScheduleEntry.academic_year_id, academic_year_id),
        (ScheduleEntry.school_id, school_id),
        (ScheduleEntry.teacher_id, teacher_id),
        (ScheduleEntry.day, day),
        (SchoolClass.grade, grade),
        (ScheduleEntry.class_id, class_id),
    ]:
        if isinstance(value, list):
            values = [x for x in value if x != ""]
            if values:
                q = q.where(field.in_(values))
        elif value is not None and value != "":
            q = q.where(field == value)
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        term = f"%{escaped}%"
        q = q.where(
            School.name.ilike(term, escape="\\")
            | Teacher.full_name.ilike(term, escape="\\")
            | SchoolClass.name.ilike(term, escape="\\")
            | SchoolClass.grade.ilike(term, escape="\\")
            | ScheduleEntry.notes.ilike(term, escape="\\")
        )
    return q.order_by(ScheduleEntry.day, ScheduleEntry.start_time, School.name, Teacher.full_name, ScheduleEntry.id)


def sessions(db, **filters):
    result = []
    for entry, school, teacher, school_class, updated_by, deleted_at in db.execute(session_query(**filters)):
        result.append(
            {
                **snapshot(entry),
                "school_name": school.name,
                "school_color": school.color,
                "teacher_name": teacher.full_name,
                "grade": school_class.grade,
                "class_name": school_class.name,
                "updated_by_name": user_label(updated_by, deleted_at),
            }
        )
    return result


def conflicts(entries):
    result = []
    buckets = {}
    for entry in entries:
        buckets.setdefault((entry["academic_year_id"], entry["day"]), []).append(entry)
    for group in buckets.values():
        ordered = sorted(group, key=lambda x: x["start_time"])
        for i, first in enumerate(ordered):
            for second in ordered[i + 1 :]:
                if second["start_time"] >= first["end_time"]:
                    break
                kinds = []
                if first["teacher_id"] == second["teacher_id"]:
                    kinds.append("Teacher overlap")
                if first["class_id"] == second["class_id"]:
                    kinds.append("Class overlap")
                if kinds:
                    result.append(
                        {"id": f"{first['id']}-{second['id']}", "types": kinds, "first": first, "second": second}
                    )
    return result


def minutes(time):
    hours, mins = map(int, time.split(":"))
    return hours * 60 + mins


def safe_cell(value):
    value = str(value or "")
    if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value

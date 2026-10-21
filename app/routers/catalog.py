from fastapi import Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AcademicYear, ScheduleEntry, School, SchoolClass, Teacher, TeacherSchoolAssignment, User
from ..schemas import AssignmentInput, ClassInput, SchoolInput, TeacherInput
from ..security import editor, super_admin
from ..services import audit, commit, find, snapshot, writable_year
from .common import protected_router

router = protected_router()


@router.get("/catalog")
def catalog(db: Session = Depends(get_db)):
    return {
        key: [snapshot(row) for row in db.scalars(select(model).order_by(model.id))]
        for key, model in [
            ("schools", School),
            ("teachers", Teacher),
            ("classes", SchoolClass),
            ("assignments", TeacherSchoolAssignment),
            ("academic_years", AcademicYear),
        ]
    }


@router.get("/schools")
def list_schools(db: Session = Depends(get_db)):
    return [snapshot(row) for row in db.scalars(select(School).order_by(School.name))]


@router.get("/teachers")
def list_teachers(db: Session = Depends(get_db)):
    return [snapshot(row) for row in db.scalars(select(Teacher).order_by(Teacher.full_name))]


@router.post("/schools", status_code=201)
def add_school(data: SchoolInput, user: User = Depends(super_admin), db: Session = Depends(get_db)):
    row = School(**data.model_dump())
    db.add(row)
    audit(db, user, "create", row)
    commit(db)
    return snapshot(row)


@router.put("/schools/{school_id}")
def edit_school(school_id: int, data: SchoolInput, user: User = Depends(super_admin), db: Session = Depends(get_db)):
    row = find(db, School, school_id)
    old = snapshot(row)
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    audit(db, user, "update", row, old)
    commit(db)
    return snapshot(row)


LINKED = {
    # Order matters: sessions reference assignments and classes, so they are removed first.
    "school_id": [("sessions", ScheduleEntry), ("assignments", TeacherSchoolAssignment), ("classes", SchoolClass)],
    "teacher_id": [("sessions", ScheduleEntry), ("assignments", TeacherSchoolAssignment)],
}


def linked_records(db, field, value):
    """Records that deleting a school or teacher would remove."""
    return {key: db.scalars(select(model).where(getattr(model, field) == value)).all() for key, model in LINKED[field]}


def impact(db, linked):
    archived = {x.id for x in db.scalars(select(AcademicYear).where(AcademicYear.archived))}
    return {
        **{key: len(rows) for key, rows in linked.items()},
        "archived_sessions": sum(x.academic_year_id in archived for x in linked["sessions"]),
    }


def delete_with_links(db, user, row, field):
    linked = linked_records(db, field, row.id)
    # The audit entry keeps a copy of everything removed, so it can be restored by hand.
    audit(
        db, user, "delete", row, {**snapshot(row), "removed": {k: [snapshot(x) for x in v] for k, v in linked.items()}}
    )
    for key, model in LINKED[field]:
        ids = [x.id for x in linked[key]]
        if ids:
            db.execute(delete(model).where(model.id.in_(ids)))
    db.delete(row)
    commit(db)
    return {key: len(rows) for key, rows in linked.items()}


@router.get("/schools/{school_id}/impact")
def school_delete_impact(school_id: int, user: User = Depends(super_admin), db: Session = Depends(get_db)):
    return impact(db, linked_records(db, "school_id", find(db, School, school_id).id))


@router.delete("/schools/{school_id}")
def delete_school(school_id: int, user: User = Depends(super_admin), db: Session = Depends(get_db)):
    school = find(db, School, school_id)
    return {"message": "School deleted.", "removed": delete_with_links(db, user, school, "school_id")}


@router.get("/teachers/{teacher_id}/impact")
def teacher_delete_impact(teacher_id: int, user: User = Depends(super_admin), db: Session = Depends(get_db)):
    return impact(db, linked_records(db, "teacher_id", find(db, Teacher, teacher_id).id))


@router.delete("/teachers/{teacher_id}")
def delete_teacher(teacher_id: int, user: User = Depends(super_admin), db: Session = Depends(get_db)):
    teacher = find(db, Teacher, teacher_id)
    return {"message": "Teacher deleted.", "removed": delete_with_links(db, user, teacher, "teacher_id")}


@router.post("/teachers", status_code=201)
def add_teacher(data: TeacherInput, user: User = Depends(super_admin), db: Session = Depends(get_db)):
    row = Teacher(**data.model_dump())
    db.add(row)
    audit(db, user, "create", row)
    commit(db)
    return snapshot(row)


@router.put("/teachers/{teacher_id}")
def edit_teacher(teacher_id: int, data: TeacherInput, user: User = Depends(super_admin), db: Session = Depends(get_db)):
    row = find(db, Teacher, teacher_id)
    old = snapshot(row)
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    audit(db, user, "update", row, old)
    commit(db)
    return snapshot(row)


@router.post("/classes", status_code=201)
def add_class(data: ClassInput, user: User = Depends(editor), db: Session = Depends(get_db)):
    school = find(db, School, data.school_id)
    if not school.active:
        raise HTTPException(422, "Select an active school.")
    row = SchoolClass(**data.model_dump())
    db.add(row)
    audit(db, user, "create", row)
    commit(db)
    return snapshot(row)


@router.post("/assignments", status_code=201)
def assign_teacher(data: AssignmentInput, user: User = Depends(super_admin), db: Session = Depends(get_db)):
    writable_year(db, data.academic_year_id)
    teacher = find(db, Teacher, data.teacher_id)
    school = find(db, School, data.school_id)
    if not teacher.active or not school.active:
        raise HTTPException(422, "Select an active school and teacher.")
    existing = db.scalar(
        select(TeacherSchoolAssignment).where(
            TeacherSchoolAssignment.teacher_id == data.teacher_id,
            TeacherSchoolAssignment.academic_year_id == data.academic_year_id,
        )
    )
    if existing:
        if existing.school_id == data.school_id:
            return snapshot(existing)
        raise HTTPException(
            409,
            "This teacher is already assigned to another school for this academic year. Remove the assignment before reassigning.",
        )
    row = TeacherSchoolAssignment(**data.model_dump())
    db.add(row)
    audit(db, user, "create", row)
    commit(db)
    return snapshot(row)


@router.delete("/assignments/{assignment_id}")
def remove_assignment(assignment_id: int, user: User = Depends(super_admin), db: Session = Depends(get_db)):
    row = find(db, TeacherSchoolAssignment, assignment_id)
    writable_year(db, row.academic_year_id)
    if db.scalar(
        select(ScheduleEntry.id)
        .where(ScheduleEntry.teacher_id == row.teacher_id, ScheduleEntry.academic_year_id == row.academic_year_id)
        .limit(1)
    ):
        raise HTTPException(
            409, "This teacher has sessions in this academic year. Remove those sessions before reassigning."
        )
    audit(db, user, "delete", row, snapshot(row))
    db.delete(row)
    commit(db)
    return {"message": "Assignment removed."}

"""Plan an import in memory, then persist each group of records in a batch."""

import hashlib

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from .models import AuditLog, School, SchoolClass, Teacher, TeacherSchoolAssignment, ScheduleEntry, utcnow
from .schemas import ClassInput, SchoolInput, SessionInput, TeacherInput
from .services import DAYS, commit, conflicts, sessions, snapshot


def import_rows(db, user, year_id, raw, headers, *, create_missing, dry_run):
    empty_records = {"schools": [], "teachers": [], "assignments": [], "classes": 0}
    can_create = create_missing and user.role == "SUPER_ADMIN"

    def missing(message):
        if user.role == "SUPER_ADMIN":
            raise ValueError(message + " Enable creation of missing records or add this record first.")
        raise ValueError(message + " Ask a Super Admin to create and assign the missing records.")

    # These reads replace the per-row school/class/assignment/duplicate queries.
    school_rows = list(db.scalars(select(School)))
    schools = {x.name.casefold(): x for x in school_rows}
    schools_by_id = {x.id: x for x in school_rows}
    teachers = {}
    for teacher in db.scalars(select(Teacher)):
        teachers.setdefault(teacher.full_name.casefold(), []).append(teacher)
    assignments = {
        x.teacher_id: x
        for x in db.scalars(select(TeacherSchoolAssignment).where(TeacherSchoolAssignment.academic_year_id == year_id))
    }
    classes = {
        (schools_by_id[x.school_id].name.casefold(), x.grade, x.name): x for x in db.scalars(select(SchoolClass))
    }
    existing = sessions(db, academic_year_id=year_id)
    duplicates = {
        (
            x["school_name"].casefold(),
            x["teacher_name"].casefold(),
            x["grade"],
            x["class_name"],
            x["day"],
            x["start_time"],
            x["end_time"],
        )
        for x in existing
    }
    planned_schools, planned_teachers, planned_assignments, planned_classes = {}, {}, {}, {}
    accepted, errors = [], []
    palette = ["#315FAA", "#288478", "#AC5A33", "#8D5CA6", "#AD8430", "#52738A"]

    for line, values in enumerate(raw[1:], 2):
        if not any(x is not None and str(x).strip() for x in values):
            continue
        row = {
            name: str(values[i]).strip() if i < len(values) and values[i] is not None else ""
            for i, name in enumerate(headers)
        }
        try:
            color_index = int(hashlib.sha256(row["school"].casefold().encode()).hexdigest()[:8], 16)
            school_data = SchoolInput(name=row["school"], color=palette[color_index % len(palette)])
            teacher_data = TeacherInput(full_name=row["teacher"])
            class_data = ClassInput(school_id=1, grade=row["grade"], name=row["class"])
            day = next(
                (
                    i
                    for i, value in enumerate(DAYS)
                    if row["day"].casefold() in {value.casefold(), value[:3].casefold()}
                ),
                None,
            )
            if day is None:
                raise ValueError("Use a weekday name such as Monday.")
            for key in ("start_time", "end_time"):
                if len(row[key]) == 8 and row[key].endswith(":00"):
                    row[key] = row[key][:5]
            data = SessionInput(
                school_id=1,
                teacher_id=1,
                class_id=1,
                academic_year_id=year_id,
                day=day,
                start_time=row["start_time"],
                end_time=row["end_time"],
                notes=row.get("notes", ""),
            )
            school_key, teacher_key = school_data.name.casefold(), teacher_data.full_name.casefold()
            school = schools.get(school_key)
            if school is None and not can_create:
                missing(f"School '{school_data.name}' was not found.")
            candidates = teachers.get(teacher_key, [])
            if len(candidates) > 1:
                raise ValueError(
                    f"More than one teacher is named '{teacher_data.full_name}'. Use a unique teacher name."
                )
            teacher = candidates[0] if candidates else None
            if teacher is None and not can_create:
                missing(f"Teacher '{teacher_data.full_name}' was not found.")
            if (school is not None and not school.active) or (teacher is not None and not teacher.active):
                raise ValueError("School and teacher must be active.")

            assignment = assignments.get(teacher.id) if teacher is not None else None
            target = schools_by_id[assignment.school_id].name if assignment else planned_assignments.get(teacher_key)
            if target and target.casefold() != school_key:
                raise ValueError(
                    f"Teacher '{teacher_data.full_name}' is already assigned to '{target}' for this year. "
                    "One teacher can only belong to one school per academic year."
                )
            if assignment is None and not can_create:
                missing(f"Teacher '{teacher_data.full_name}' is not assigned to '{school_data.name}' for this year.")
            duplicate_key = (
                school_key,
                teacher_key,
                class_data.grade,
                class_data.name,
                data.day,
                data.start_time,
                data.end_time,
            )
            if duplicate_key in duplicates:
                raise ValueError("This session is already present or duplicated within the file.")

            # Only fully valid rows contribute to the import plan.
            if school is None:
                planned_schools.setdefault(school_key, school_data)
            if teacher is None:
                planned_teachers.setdefault(teacher_key, teacher_data)
            if assignment is None:
                name = school.name if school is not None else planned_schools[school_key].name
                planned_assignments.setdefault(teacher_key, name)
            class_key = (school_key, class_data.grade, class_data.name)
            if class_key not in classes:
                planned_classes.setdefault(class_key, class_data)
            duplicates.add(duplicate_key)
            accepted.append((school_key, teacher_key, class_key, data))
        except (ValueError, ValidationError) as exc:
            errors.append({"row": line, "message": str(exc)})

    def result(new_records, warnings=None, imported=0):
        return {
            "dry_run": dry_run,
            "valid_rows": len(accepted),
            "errors": errors,
            "conflicts": warnings or [],
            "imported": imported,
            "new_records": new_records,
        }

    if errors:
        db.rollback()
        return result(empty_records)
    new_records = {
        "schools": [x.name for x in planned_schools.values()],
        "teachers": [x.full_name for x in planned_teachers.values()],
        "assignments": [
            {
                "teacher": teachers[key][0].full_name if key in teachers else planned_teachers[key].full_name,
                "school": name,
            }
            for key, name in planned_assignments.items()
        ],
        "classes": len(planned_classes),
    }

    if dry_run:
        # Negative IDs identify preview-only records; no INSERTs are needed to validate.
        school_ids = {key: x.id for key, x in schools.items()}
        school_ids.update({key: -i for i, key in enumerate(planned_schools, 1)})
        teacher_ids = {key: items[0].id for key, items in teachers.items() if len(items) == 1}
        teacher_ids.update({key: -i for i, key in enumerate(planned_teachers, 1)})
        class_ids = {key: x.id for key, x in classes.items()}
        class_ids.update({key: -i for i, key in enumerate(planned_classes, 1)})
        previews = []
        now = utcnow().isoformat()
        for i, (school_key, teacher_key, class_key, data) in enumerate(accepted, 1):
            school = schools.get(school_key) or planned_schools[school_key]
            teacher = teachers[teacher_key][0] if teacher_key in teachers else planned_teachers[teacher_key]
            previews.append(
                {
                    **data.model_dump(),
                    "id": -i,
                    "school_id": school_ids[school_key],
                    "teacher_id": teacher_ids[teacher_key],
                    "class_id": class_ids[class_key],
                    "school_name": school.name,
                    "school_color": school.color,
                    "teacher_name": teacher.full_name,
                    "grade": class_key[1],
                    "class_name": class_key[2],
                    "version": 1,
                    "created_by": user.id,
                    "updated_by": user.id,
                    "updated_by_name": user.full_name,
                    "created_at": now,
                    "updated_at": now,
                }
            )
        warnings = [x for x in conflicts(existing + previews) if x["first"]["id"] < 0 or x["second"]["id"] < 0]
        db.rollback()
        return result(new_records, warnings)

    if not accepted:
        raise HTTPException(422, "No schedule rows found.")
    audit_rows = []

    def add_batch(objects, action):
        if not objects:
            return
        db.add_all(objects)
        db.flush()
        audit_rows.extend((action, obj) for obj in objects)

    new_schools = {key: School(**data.model_dump()) for key, data in planned_schools.items()}
    new_teachers = {key: Teacher(**data.model_dump()) for key, data in planned_teachers.items()}
    add_batch([*new_schools.values(), *new_teachers.values()], "create")
    schools.update(new_schools)
    teachers.update({key: [teacher] for key, teacher in new_teachers.items()})
    new_assignments = [
        TeacherSchoolAssignment(
            teacher_id=teachers[key][0].id, school_id=schools[name.casefold()].id, academic_year_id=year_id
        )
        for key, name in planned_assignments.items()
    ]
    new_classes = {
        key: SchoolClass(school_id=schools[key[0]].id, grade=data.grade, name=data.name)
        for key, data in planned_classes.items()
    }
    add_batch([*new_assignments, *new_classes.values()], "create")
    classes.update(new_classes)
    entries = []
    for school_key, teacher_key, class_key, data in accepted:
        entries.append(
            ScheduleEntry(
                **{
                    **data.model_dump(),
                    "school_id": schools[school_key].id,
                    "teacher_id": teachers[teacher_key][0].id,
                    "class_id": classes[class_key].id,
                },
                created_by=user.id,
                updated_by=user.id,
            )
        )
    add_batch(entries, "import")
    imported_ids = {entry.id for entry in entries}
    warnings = [
        x
        for x in conflicts(sessions(db, academic_year_id=year_id))
        if x["first"]["id"] in imported_ids or x["second"]["id"] in imported_ids
    ]
    db.add_all(
        [
            AuditLog(
                user_id=user.id, action=action, entity_type=obj.__tablename__, entity_id=obj.id, new_value=snapshot(obj)
            )
            for action, obj in audit_rows
        ]
    )
    commit(db)
    return result(new_records, warnings, len(entries))

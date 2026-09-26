"""Run after Alembic: python -m app.cli bootstrap [--demo]."""

import argparse
from datetime import date
from getpass import getpass
from pydantic import TypeAdapter, EmailStr
from sqlalchemy import select
from .config import get_settings
from .database import SessionLocal
from .models import AcademicYear, School, SchoolClass, Teacher, TeacherSchoolAssignment, ScheduleEntry, User
from .security import hash_password
from .services import audit, commit


def bootstrap(demo=False, non_interactive=False):
    settings = get_settings()
    if demo and settings.production:
        raise SystemExit("Demo data is disabled in production.")
    with SessionLocal() as db:
        # Serializes bootstrap in PostgreSQL without retaining a global app lock.
        if db.bind.dialect.name == "postgresql":
            from sqlalchemy import text

            db.execute(text("SELECT pg_advisory_xact_lock(71826601)"))
        admin = db.scalar(select(User).where(User.role == "SUPER_ADMIN", User.active))
        if admin is None:
            if non_interactive and not all(
                [settings.bootstrap_email, settings.bootstrap_name, settings.bootstrap_password]
            ):
                raise SystemExit("Set BOOTSTRAP_EMAIL, BOOTSTRAP_NAME and BOOTSTRAP_PASSWORD for the first deployment.")
            email = settings.bootstrap_email or input("First admin email: ").strip()
            name = settings.bootstrap_name or input("Full name: ").strip()
            password = settings.bootstrap_password or getpass("Temporary password (at least 12 characters): ")
            email = str(TypeAdapter(EmailStr).validate_python(email)).lower()
            if not name or len(name) > 120 or not 12 <= len(password) <= 256:
                raise SystemExit("Name must be 1–120 characters; password must be 12–256 characters.")
            admin = User(
                full_name=name,
                email=email,
                password_hash=hash_password(password),
                role="SUPER_ADMIN",
                active=True,
                export_allowed=True,
                must_change_password=True,
            )
            db.add(admin)
            db.flush()
            audit(db, admin, "bootstrap", admin)
            print("First Super Admin created. Change the temporary password on first sign-in.")
        else:
            print("An active Super Admin already exists; bootstrap did not change any credentials.")
        year = db.scalar(select(AcademicYear).where(AcademicYear.active))
        if not db.scalar(select(AcademicYear.id).limit(1)):
            today = date.today()
            first = today.year if today.month >= 8 else today.year - 1
            year = AcademicYear(
                name=f"{first}/{first + 1}",
                start_date=date(first, 9, 1),
                end_date=date(first + 1, 7, 31),
                active=True,
                active_slot=1,
            )
            db.add(year)
            audit(db, admin, "create", year)
        if demo and year and not db.scalar(select(School.id).limit(1)):
            specs = [
                ("Example Cedar School", "#3e75d8", ["Example Huda", "Example Rami"]),
                ("Example Horizon School", "#d5704c", ["Example Jamal"]),
                ("Example Summit School", "#48a38d", ["Example Maya"]),
            ]
            for index, (name, color, names) in enumerate(specs):
                school = School(name=name, color=color)
                db.add(school)
                audit(db, admin, "create", school)
                for n, teacher_name in enumerate(names):
                    teacher = Teacher(full_name=teacher_name)
                    db.add(teacher)
                    audit(db, admin, "create", teacher)
                    db.add(
                        TeacherSchoolAssignment(teacher_id=teacher.id, school_id=school.id, academic_year_id=year.id)
                    )
                    school_class = SchoolClass(school_id=school.id, grade=f"Grade {4 + n}", name=chr(65 + n))
                    db.add(school_class)
                    db.flush()
                    for day in range(5):
                        start = f"{8 + index:02d}:00"
                        entry = ScheduleEntry(
                            school_id=school.id,
                            teacher_id=teacher.id,
                            class_id=school_class.id,
                            academic_year_id=year.id,
                            day=day,
                            start_time=start,
                            end_time=f"{8 + index:02d}:50",
                            notes="Synthetic development example",
                            created_by=admin.id,
                            updated_by=admin.id,
                        )
                        db.add(entry)
                        audit(db, admin, "create", entry)
            print("Synthetic example schedules created for development only.")
        commit(db)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["bootstrap"])
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")
    args = parser.parse_args()
    bootstrap(args.demo, args.non_interactive)


if __name__ == "__main__":
    main()

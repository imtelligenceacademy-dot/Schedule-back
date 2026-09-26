from datetime import datetime, timezone
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    role: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    export_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (CheckConstraint("role IN ('SUPER_ADMIN','ADMIN','VIEWER')", name="ck_user_role"),)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class LoginThrottle(Base):
    __tablename__ = "login_throttles"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AcademicYear(Base):
    __tablename__ = "academic_years"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True)
    start_date: Mapped[datetime] = mapped_column(Date)
    end_date: Mapped[datetime] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    # Only one active year, including during concurrent configuration changes.
    active_slot: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="ck_year_dates"),
        CheckConstraint(
            "(active = false AND active_slot IS NULL) OR (active = true AND active_slot = 1 AND archived = false)",
            name="ck_year_active",
        ),
    )


class School(Base):
    __tablename__ = "schools"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    color: Mapped[str] = mapped_column(String(7))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Teacher(Base):
    __tablename__ = "teachers"
    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class TeacherSchoolAssignment(Base):
    __tablename__ = "teacher_school_assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"))
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    academic_year_id: Mapped[int] = mapped_column(ForeignKey("academic_years.id"))
    __table_args__ = (
        UniqueConstraint("teacher_id", "academic_year_id", name="uq_teacher_year"),
        UniqueConstraint("teacher_id", "academic_year_id", "school_id", name="uq_assignment_link"),
    )


class SchoolClass(Base):
    __tablename__ = "classes"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    grade: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(50))
    __table_args__ = (
        UniqueConstraint("school_id", "grade", "name", name="uq_school_class"),
        UniqueConstraint("id", "school_id", name="uq_class_link"),
    )


class ScheduleEntry(Base):
    __tablename__ = "schedule_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"))
    academic_year_id: Mapped[int] = mapped_column(ForeignKey("academic_years.id"), index=True)
    day: Mapped[int] = mapped_column(Integer, index=True)
    start_time: Mapped[str] = mapped_column(String(5))
    end_time: Mapped[str] = mapped_column(String(5))
    notes: Mapped[str] = mapped_column(String(2000), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        ForeignKeyConstraint(
            ["teacher_id", "academic_year_id", "school_id"],
            [
                "teacher_school_assignments.teacher_id",
                "teacher_school_assignments.academic_year_id",
                "teacher_school_assignments.school_id",
            ],
            name="fk_session_assignment",
        ),
        ForeignKeyConstraint(["class_id", "school_id"], ["classes.id", "classes.school_id"], name="fk_session_class"),
        CheckConstraint("day >= 0 AND day <= 6", name="ck_session_day"),
        CheckConstraint("end_time > start_time", name="ck_session_times"),
        UniqueConstraint(
            "academic_year_id", "class_id", "teacher_id", "day", "start_time", "end_time", name="uq_exact_session"
        ),
    )
    __mapper_args__ = {"version_id_col": version}


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(40))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int] = mapped_column(Integer)
    old_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

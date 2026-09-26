import os
import tempfile
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

# Tests always use a disposable database, never DATABASE_URL from local/deployed .env.
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-only-" + "a" * 48
os.environ["FRONTEND_URL"] = "http://testserver,https://schedule-test.vercel.app"

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AcademicYear, School, SchoolClass, Teacher, TeacherSchoolAssignment, User  # noqa: E402
from app.security import hash_password  # noqa: E402

PASSWORD = "Testing-password-2026"


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as folder:
        postgres_url = os.environ.get("TEST_POSTGRES_URL")
        admin_engine = None
        if postgres_url:
            schema = "schedule_test_" + uuid4().hex
            admin_engine = create_engine(postgres_url)
            with admin_engine.begin() as connection:
                connection.exec_driver_sql(f"CREATE SCHEMA {schema}")
            engine = create_engine(
                postgres_url, connect_args={"options": f"-csearch_path={schema},public"}, pool_size=4, max_overflow=0
            )
        else:
            engine = create_engine(
                "sqlite:///" + str(Path(folder) / "test.db"), connect_args={"check_same_thread": False}
            )

            @event.listens_for(engine, "connect")
            def fk(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(engine)
        factory = sessionmaker(engine, expire_on_commit=False)
        with factory() as db:
            for index, role in enumerate(["SUPER_ADMIN", "ADMIN", "VIEWER"], 1):
                db.add(
                    User(
                        id=index,
                        full_name=role.title(),
                        email=role.lower() + "@example.com",
                        role=role,
                        password_hash=hash_password(PASSWORD),
                        active=True,
                        must_change_password=False,
                    )
                )
            db.add_all(
                [
                    AcademicYear(
                        id=1,
                        name="2026/2027",
                        start_date=date(2026, 9, 1),
                        end_date=date(2027, 7, 31),
                        active=True,
                        active_slot=1,
                    ),
                    AcademicYear(id=2, name="2027/2028", start_date=date(2027, 9, 1), end_date=date(2028, 7, 31)),
                ]
            )
            db.add_all([School(id=1, name="Cedar", color="#3366cc"), School(id=2, name="Horizon", color="#339966")])
            db.add_all([Teacher(id=1, full_name="Huda"), Teacher(id=2, full_name="Rami")])
            db.flush()
            db.add_all(
                [
                    TeacherSchoolAssignment(teacher_id=1, school_id=1, academic_year_id=1),
                    TeacherSchoolAssignment(teacher_id=2, school_id=1, academic_year_id=1),
                    TeacherSchoolAssignment(teacher_id=1, school_id=2, academic_year_id=2),
                ]
            )
            db.add_all(
                [
                    SchoolClass(id=1, school_id=1, grade="Grade 4", name="B"),
                    SchoolClass(id=2, school_id=1, grade="Grade 5", name="A"),
                    SchoolClass(id=3, school_id=2, grade="Grade 4", name="B"),
                ]
            )
            db.commit()
        if postgres_url:
            with engine.begin() as connection:
                for table in ("users", "schools", "teachers", "classes", "academic_years"):
                    connection.exec_driver_sql(
                        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT MAX(id) FROM {table}))"
                    )

        def override():
            with factory() as db:
                yield db

        app.dependency_overrides[get_db] = override
        try:
            yield factory
        finally:
            app.dependency_overrides.clear()
            engine.dispose()
            if admin_engine:
                with admin_engine.begin() as connection:
                    connection.exec_driver_sql(f"DROP SCHEMA {schema} CASCADE")
                admin_engine.dispose()


@pytest.fixture
def clients(store):
    items = {}
    for role in ["SUPER_ADMIN", "ADMIN", "VIEWER"]:
        client = TestClient(app)
        auth = client.post("/api/auth/login", json={"email": role.lower() + "@example.com", "password": PASSWORD})
        assert auth.status_code == 200, auth.text
        client.cookies.clear()  # Model separate Vercel/Render sites: no third-party cookies.
        client.headers["Authorization"] = "Bearer " + auth.json()["access_token"]
        items[role] = client
    yield items
    for client in items.values():
        client.close()


@pytest.fixture
def payload():
    return {
        "academic_year_id": 1,
        "school_id": 1,
        "teacher_id": 1,
        "class_id": 1,
        "day": 0,
        "start_time": "08:00",
        "end_time": "08:50",
        "notes": "",
    }

from sqlalchemy import func, select

from app.models import AuditLog, School, Teacher, TeacherSchoolAssignment

HEADER = "school,teacher,grade,class,day,start_time,end_time,notes\n"


def upload(client, rows, *, dry=True, create=True):
    return client.post(
        f"/api/import?academic_year_id=1&dry_run={str(dry).lower()}&create_missing={str(create).lower()}",
        files={"file": ("schedule.csv", HEADER + rows, "text/csv")},
    )


def test_super_admin_import_previews_then_creates_and_audits_setup(clients, store):
    client = clients["SUPER_ADMIN"]
    original = client.get("/api/catalog").json()
    with store() as db:
        audit_count = db.scalar(select(func.count()).select_from(AuditLog))
    rows = (
        "Frerre Deddeh,Teacher Grade 1A,1,1A,Monday,08:00,08:45,\n"
        "frerre deddeh,teacher grade 1a,1,1A,Tuesday,09:00,09:45,\n"
        "Frerre Deddeh,Teacher Grade 1B,1,1B,Wednesday,10:00,10:45,\n"
    )
    preview = upload(client, rows)
    assert preview.status_code == 200, preview.text
    data = preview.json()
    assert data["valid_rows"] == 3 and not data["errors"]
    assert data["new_records"] == {
        "schools": ["Frerre Deddeh"],
        "teachers": ["Teacher Grade 1A", "Teacher Grade 1B"],
        "assignments": [
            {"teacher": "Teacher Grade 1A", "school": "Frerre Deddeh"},
            {"teacher": "Teacher Grade 1B", "school": "Frerre Deddeh"},
        ],
        "classes": 2,
    }
    assert client.get("/api/catalog").json() == original
    with store() as db:
        assert db.scalar(select(func.count()).select_from(AuditLog)) == audit_count
    imported = upload(client, rows, dry=False).json()
    assert imported["imported"] == 3 and imported["new_records"] == data["new_records"]
    catalog = client.get("/api/catalog").json()
    assert len(catalog["schools"]) == len(original["schools"]) + 1
    assert len(catalog["teachers"]) == len(original["teachers"]) + 2
    assert len(catalog["assignments"]) == len(original["assignments"]) + 2
    assert len(client.get("/api/schedules").json()) == 3
    with store() as db:
        logs = list(db.scalars(select(AuditLog).where(AuditLog.action == "create")))
        assert {x.entity_type for x in logs} >= {"schools", "teachers", "teacher_school_assignments", "classes"}
        assert all(x.user_id == 1 for x in logs)


def test_invalid_import_rolls_back_all_new_setup_and_audit(clients, store):
    client = clients["SUPER_ADMIN"]
    original = client.get("/api/catalog").json()
    rows = (
        "New School,New Teacher,1,1A,Monday,08:00,08:45,\n"
        "Another School,Another Teacher,1,1B,Tuesday,25:00,09:45,\n"
    )
    response = upload(client, rows, dry=False)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["imported"] == 0 and result["errors"][0]["row"] == 3
    assert result["new_records"] == {"schools": [], "teachers": [], "assignments": [], "classes": 0}
    assert client.get("/api/catalog").json() == original
    assert client.get("/api/schedules").json() == []
    with store() as db:
        assert not db.scalar(select(AuditLog.id).where(AuditLog.entity_type == "schools"))


def test_import_cannot_assign_one_teacher_to_two_schools(clients):
    client = clients["SUPER_ADMIN"]
    original = client.get("/api/catalog").json()
    rows = (
        "School One,Same Teacher,1,A,Monday,08:00,08:45,\n"
        "School Two,Same Teacher,1,B,Tuesday,09:00,09:45,\n"
    )
    response = upload(client, rows, dry=False).json()
    assert response["imported"] == 0
    assert "One teacher can only belong to one school" in response["errors"][0]["message"]
    assert client.get("/api/catalog").json() == original
    existing = upload(client, "Horizon,Huda,1,A,Monday,08:00,08:45,\n", dry=False).json()
    assert "already assigned to 'Cedar'" in existing["errors"][0]["message"]


def test_admin_cannot_create_reference_records_through_import(clients):
    client = clients["ADMIN"]
    original = client.get("/api/catalog").json()
    for rows in [
        "New School,New Teacher,1,A,Monday,08:00,08:45,\n",
        "Cedar,New Teacher,1,A,Monday,08:00,08:45,\n",
    ]:
        result = upload(client, rows, dry=False, create=True).json()
        assert result["imported"] == 0 and "Super Admin" in result["errors"][0]["message"]
    assert client.get("/api/catalog").json() == original


def test_import_creates_missing_assignment_without_duplicate_teacher(clients, store):
    with store() as db:
        teacher = Teacher(full_name="Unassigned Teacher")
        db.add(teacher)
        db.commit()
        teacher_id = teacher.id
    client = clients["SUPER_ADMIN"]
    rows = "Cedar,Unassigned Teacher,1,A,Monday,08:00,08:45,\n"
    admin = upload(clients["ADMIN"], rows, dry=False).json()
    assert "not assigned" in admin["errors"][0]["message"]
    result = upload(client, rows, dry=False).json()
    assert result["imported"] == 1 and not result["new_records"]["teachers"]
    assert result["new_records"]["assignments"] == [{"school": "Cedar", "teacher": "Unassigned Teacher"}]
    with store() as db:
        assignment = db.scalar(select(TeacherSchoolAssignment).where(TeacherSchoolAssignment.teacher_id == teacher_id))
        assert assignment.school_id == 1 and assignment.academic_year_id == 1


def test_creation_can_be_disabled_and_ambiguous_or_inactive_records_are_rejected(clients, store):
    client = clients["SUPER_ADMIN"]
    result = upload(client, "New School,New Teacher,1,A,Monday,08:00,08:45,\n", create=False).json()
    assert "Enable creation" in result["errors"][0]["message"]
    with store() as db:
        db.add(Teacher(full_name="Huda"))
        db.get(School, 2).active = False
        db.commit()
    duplicate = upload(client, "Cedar,Huda,1,A,Monday,08:00,08:45,\n").json()
    assert "More than one teacher" in duplicate["errors"][0]["message"]
    inactive = upload(client, "Horizon,Rami,1,A,Monday,08:00,08:45,\n").json()
    assert "must be active" in inactive["errors"][0]["message"]

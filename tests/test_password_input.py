from app.schemas import UserCreate


def test_temporary_password_preserves_intentional_whitespace():
    password = "  meaningful-password  "
    data = UserCreate(full_name="  New User  ", email="new@example.com", role="VIEWER", temporary_password=password)
    assert data.temporary_password == password
    assert data.full_name == "New User"

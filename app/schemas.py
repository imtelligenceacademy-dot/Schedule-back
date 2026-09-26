from datetime import date
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, model_validator

Role = Literal["SUPER_ADMIN", "ADMIN", "VIEWER"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoginInput(Input):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    # Password whitespace is intentional and must not be trimmed.
    model_config = ConfigDict(extra="forbid")


class PasswordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class UserCreate(Input):
    full_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    role: Role
    temporary_password: Annotated[str, StringConstraints(strip_whitespace=False, min_length=12, max_length=256)]
    export_allowed: bool = False


class UserUpdate(Input):
    full_name: str = Field(min_length=1, max_length=120)
    role: Role
    active: bool
    export_allowed: bool = False


class ResetPassword(BaseModel):
    model_config = ConfigDict(extra="forbid")
    temporary_password: str = Field(min_length=12, max_length=256)


class SchoolInput(Input):
    name: str = Field(min_length=1, max_length=150)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    active: bool = True


class TeacherInput(Input):
    full_name: str = Field(min_length=1, max_length=120)
    email: EmailStr | None = None
    active: bool = True


class ClassInput(Input):
    school_id: int = Field(gt=0)
    grade: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=50)


class AssignmentInput(Input):
    teacher_id: int = Field(gt=0)
    school_id: int = Field(gt=0)
    academic_year_id: int = Field(gt=0)


class YearInput(Input):
    name: str = Field(min_length=1, max_length=40)
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def dates(self):
        if self.end_date < self.start_date:
            raise ValueError("End date must be on or after start date")
        return self


class YearUpdate(Input):
    archived: bool


class SessionInput(Input):
    school_id: int = Field(gt=0)
    teacher_id: int = Field(gt=0)
    class_id: int = Field(gt=0)
    academic_year_id: int = Field(gt=0)
    day: int = Field(ge=0, le=6)
    start_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def times(self):
        if self.end_time <= self.start_time:
            raise ValueError("End time must be later than start time")
        return self


class SessionUpdate(SessionInput):
    expected_version: int = Field(gt=0)

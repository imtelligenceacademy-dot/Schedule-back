from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_engine(
    settings.sqlalchemy_url,
    pool_pre_ping=True,
    **(
        {"connect_args": {"check_same_thread": False}}
        if settings.sqlalchemy_url.startswith("sqlite")
        else {
            "pool_size": 2,
            "max_overflow": 1,
            "pool_recycle": 300,
            "pool_timeout": 30,
            "connect_args": {"prepare_threshold": None, "connect_timeout": 15},
        }
    ),
)
if settings.sqlalchemy_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def sqlite_fk(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")


SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as db:
        yield db

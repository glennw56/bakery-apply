"""SQLite DataSource: engine, sessions, and table bootstrap.

WAL mode lets the UI keep serving while writes hit the same file.
BAKERY_APPLY_DB is a file path (default data/app.db). DATABASE_URL, if set,
wins (sqlite:///...). Analogous to spring.datasource.url pointing at an
H2/SQLite file.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DEFAULT_DB = DATA_DIR / "app.db"


def db_path() -> Path:
    raw = os.environ.get("BAKERY_APPLY_DB", str(DEFAULT_DB))
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return path


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


def _make_engine():
    url = database_url()
    if url.startswith("sqlite:///"):
        rest = url[len("sqlite:///"):]
        if rest and rest != ":memory:" and not rest.startswith("/"):
            (ROOT / Path(rest)).parent.mkdir(parents=True, exist_ok=True)
        elif rest.startswith("/"):
            Path(rest).parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        url,
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        echo=False,
    )

    @event.listens_for(engine, "connect")
    def _enable_wal(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables if they do not exist. Called on app startup."""
    from app import models  # noqa: F401 — register mappers

    if not os.environ.get("DATABASE_URL"):
        db_path().parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)

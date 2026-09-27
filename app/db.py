"""SQLite DataSource: engine, sessions, and table bootstrap.

Used when cloud env is not set. WAL mode lets the UI keep serving while writes
hit the same file. BAKERY_APPLY_DB is a file path (default data/app.db).
DATABASE_URL, if set, wins (sqlite:///...). Analogous to spring.datasource.url
pointing at an H2/SQLite file.

When GOOGLE_CLOUD_PROJECT (or GCP_PROJECT) and GCS_BUCKET are both set,
init_db() is a no-op — Firestore has no schema to create. Skip Cloud SQL.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.backend import use_cloud_backend

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DEFAULT_DB = DATA_DIR / "app.db"

engine = None
SessionLocal = None


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

    engine_ = create_engine(
        url,
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        echo=False,
    )

    @event.listens_for(engine_, "connect")
    def _enable_wal(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine_


def _ensure_sqlite():
    """Create the SQLite engine on first use. Skipped entirely in cloud mode."""
    global engine, SessionLocal
    if engine is None:
        engine = _make_engine()
        SessionLocal = sessionmaker(
            bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
        )
    return engine


if not use_cloud_backend():
    _ensure_sqlite()


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    if SessionLocal is None:
        _ensure_sqlite()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables if they do not exist (SQLite only). Called on app startup."""
    if use_cloud_backend():
        return
    from app import models  # noqa: F401 — register mappers

    _ensure_sqlite()
    if not os.environ.get("DATABASE_URL"):
        db_path().parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _migrate_user_columns()
    _migrate_application_columns()
    _migrate_position_columns()


def _migrate_user_columns() -> None:
    """Add google_sub / provider on an existing local users table."""
    from sqlalchemy import inspect, text

    from app.models import USER_NEW_COLUMNS

    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("users")}
    with engine.begin() as conn:
        for name, spec in USER_NEW_COLUMNS:
            if name not in existing:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {spec}"))
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_google_sub ON users (google_sub)"
            )
        )


def _migrate_application_columns() -> None:
    """ALTER TABLE ADD COLUMN for Talent fields if the local SQLite table already exists."""
    from sqlalchemy import inspect, text

    from app.models import APPLICATION_NEW_COLUMNS

    inspector = inspect(engine)
    if "applications" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("applications")}
    with engine.begin() as conn:
        for name, spec in APPLICATION_NEW_COLUMNS:
            if name not in existing:
                conn.execute(text(f"ALTER TABLE applications ADD COLUMN {name} {spec}"))


def _migrate_position_columns() -> None:
    """ALTER TABLE ADD COLUMN if a local positions table already exists without new fields."""
    from sqlalchemy import inspect, text

    from app.models import POSITION_NEW_COLUMNS

    inspector = inspect(engine)
    if "positions" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("positions")}
    with engine.begin() as conn:
        for name, spec in POSITION_NEW_COLUMNS:
            if name not in existing:
                conn.execute(text(f"ALTER TABLE positions ADD COLUMN {name} {spec}"))

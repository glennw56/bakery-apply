"""Data + resume adapter. SQLite by default; Firestore+GCS only when cloud env is set.

Cloud clients are imported inside open_store() so local tests never need them.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import db as sqlite_db
from app.backend import resume_attachment_name, use_cloud_backend
from app.models import (
    SEED_POSITION_DESCRIPTION,
    SEED_POSITION_HOURS,
    SEED_POSITION_PAY_CENTS,
    SEED_POSITION_TITLE,
    STATUS_REVIEWED,
    Application,
    Position,
    User,
)

ROOT = sqlite_db.ROOT
RESUMES_DIR = ROOT / "data" / "resumes"


class SqliteStore:
    """Default local backend: SQLAlchemy + files under data/resumes/{id}.pdf."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def close(self) -> None:
        self.db.close()

    def get_user_by_id(self, user_id) -> User | None:
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            return None
        return self.db.get(User, uid)

    def get_user_by_email(self, email: str) -> User | None:
        return self.db.scalar(select(User).where(User.email == email))

    def create_user(self, email: str, password_hash: str, is_admin: bool = False) -> User:
        user = User(email=email, password_hash=password_hash, is_admin=is_admin)
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def upsert_admin(self, email: str, password_hash: str) -> User:
        user = self.get_user_by_email(email)
        if user is None:
            return self.create_user(email, password_hash, is_admin=True)
        user.password_hash = password_hash
        user.is_admin = True
        self.db.commit()
        self.db.refresh(user)
        return user

    def get_application_for_user(self, user_id) -> Application | None:
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            return None
        return self.db.scalar(select(Application).where(Application.user_id == uid))

    def get_application(self, app_id) -> Application | None:
        try:
            aid = int(app_id)
        except (TypeError, ValueError):
            return None
        return self.db.get(Application, aid)

    def list_applications(self) -> list[Application]:
        return list(
            self.db.scalars(select(Application).order_by(Application.submitted_at.desc())).all()
        )

    def create_application(self, **fields) -> Application:
        if fields.get("submitted_at") is None:
            fields["submitted_at"] = datetime.now(timezone.utc).replace(tzinfo=None)
        app_row = Application(**fields)
        self.db.add(app_row)
        self.db.commit()
        self.db.refresh(app_row)
        return app_row

    def save_resume(self, application: Application, blob: bytes) -> str:
        RESUMES_DIR.mkdir(parents=True, exist_ok=True)
        rel = f"data/resumes/{application.id}.pdf"
        (ROOT / rel).write_bytes(blob)
        application.resume_path = rel
        self.db.commit()
        return rel

    def mark_reviewed(self, application: Application) -> Application:
        application.status = STATUS_REVIEWED
        application.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        self.db.commit()
        self.db.refresh(application)
        return application

    def resume_response(self, application: Application) -> FileResponse | None:
        rel = (application.resume_path or "").strip()
        if not rel:
            return None
        path = (ROOT / rel).resolve()
        resumes_root = RESUMES_DIR.resolve()
        if path != resumes_root and resumes_root not in path.parents:
            return None
        if not path.is_file():
            return None
        return FileResponse(
            path,
            media_type="application/pdf",
            filename=resume_attachment_name(application.name),
            content_disposition_type="attachment",
        )

    def list_positions(self) -> list[Position]:
        return list(self.db.scalars(select(Position).order_by(Position.id)).all())

    def list_open_positions(self) -> list[Position]:
        return list(
            self.db.scalars(
                select(Position).where(Position.open.is_(True)).order_by(Position.id)
            ).all()
        )

    def get_position(self, position_id) -> Position | None:
        try:
            pid = int(position_id)
        except (TypeError, ValueError):
            return None
        return self.db.get(Position, pid)

    def create_position(
        self,
        title: str,
        hours_per_week: int,
        hourly_pay_cents: int,
        open: bool = True,
        description: str = "",
    ) -> Position:
        row = Position(
            title=title.strip(),
            hours_per_week=int(hours_per_week),
            hourly_pay_cents=int(hourly_pay_cents),
            open=bool(open),
            description=(description or "").strip(),
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def update_position(self, position: Position, **fields) -> Position:
        for key, value in fields.items():
            setattr(position, key, value)
        self.db.commit()
        self.db.refresh(position)
        return position


def seed_positions() -> None:
    """If the positions table/collection is empty, insert the Counter / Cashier opening."""
    store = open_store()
    try:
        if store.list_positions():
            return
        store.create_position(
            title=SEED_POSITION_TITLE,
            hours_per_week=SEED_POSITION_HOURS,
            hourly_pay_cents=SEED_POSITION_PAY_CENTS,
            open=True,
            description=SEED_POSITION_DESCRIPTION,
        )
    finally:
        store.close()


def open_store():
    """Request-scoped store. Cloud clients imported only when env selects Firestore+GCS."""
    if use_cloud_backend():
        from app.cloud import CloudStore

        return CloudStore()
    sqlite_db._ensure_sqlite()
    return SqliteStore(sqlite_db.SessionLocal())


def get_store():
    store = open_store()
    try:
        yield store
    finally:
        store.close()

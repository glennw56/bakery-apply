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
    PROVIDER_GOOGLE,
    PROVIDER_PASSWORD,
    SEED_POSITION_DESCRIPTION,
    SEED_POSITION_HOURS,
    SEED_POSITION_PAY_CENTS,
    SEED_POSITION_TITLE,
    STATUS_REVIEWED,
    TASTING_DESCRIPTION,
    TASTING_PAY_MAX_CENTS,
    TASTING_PAY_MIN_CENTS,
    TASTING_TITLE,
    Application,
    Position,
    User,
    coerce_starting_out,
    normalize_description,
    position_pay_writes,
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

    def get_user_by_google_sub(self, google_sub: str) -> User | None:
        sub = (google_sub or "").strip()
        if not sub:
            return None
        return self.db.scalar(select(User).where(User.google_sub == sub))

    def create_user(
        self,
        email: str,
        password_hash: str,
        is_admin: bool = False,
        google_sub: str | None = None,
        provider: str = PROVIDER_PASSWORD,
    ) -> User:
        sub = (google_sub or "").strip() or None
        user = User(
            email=email,
            password_hash=password_hash,
            is_admin=is_admin,
            google_sub=sub,
            provider=provider or PROVIDER_PASSWORD,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def link_google(self, user: User, google_sub: str) -> User:
        """Attach a verified Google subject. Keeps any existing password hash."""
        user.google_sub = google_sub.strip()
        user.provider = PROVIDER_GOOGLE
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
        hourly_pay_cents: int | None = None,
        open: bool = True,
        description: str = "",
        hourly_pay_min_cents: int | None = None,
        hourly_pay_max_cents: int | None = None,
        starting_out: bool = False,
    ) -> Position:
        pay = position_pay_writes(
            hourly_pay_cents=hourly_pay_cents,
            hourly_pay_min_cents=hourly_pay_min_cents,
            hourly_pay_max_cents=hourly_pay_max_cents,
        )
        row = Position(
            title=title.strip(),
            hours_per_week=int(hours_per_week),
            hourly_pay_cents=int(pay["hourly_pay_cents"]),
            hourly_pay_min_cents=int(pay["hourly_pay_min_cents"]),
            hourly_pay_max_cents=int(pay["hourly_pay_max_cents"]),
            starting_out=coerce_starting_out(starting_out),
            open=bool(open),
            description=normalize_description(description),
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def update_position(self, position: Position, **fields) -> Position:
        if "starting_out" in fields:
            fields["starting_out"] = coerce_starting_out(fields["starting_out"])
        if "description" in fields:
            fields["description"] = normalize_description(fields["description"])
        if "hourly_pay_min_cents" in fields and "hourly_pay_cents" not in fields:
            fields["hourly_pay_cents"] = int(fields["hourly_pay_min_cents"])
        for key, value in fields.items():
            setattr(position, key, value)
        self.db.commit()
        self.db.refresh(position)
        return position


def create_tasting_position(store, hours_per_week: int):
    """Insert Ronald's Tasting opening. Not called on startup and does not touch prod.

    Hours were not specified, so the caller passes hours_per_week. Pay is
    $12–14/hour (1200–1400 cents), starting_out is true, and the job is open.
    """
    return store.create_position(
        title=TASTING_TITLE,
        hours_per_week=int(hours_per_week),
        hourly_pay_min_cents=TASTING_PAY_MIN_CENTS,
        hourly_pay_max_cents=TASTING_PAY_MAX_CENTS,
        starting_out=True,
        open=True,
        description=TASTING_DESCRIPTION,
    )


def seed_positions() -> None:
    """If the positions table/collection is empty, insert the Counter / Cashier opening."""
    if use_cloud_backend():
        return  # Production never auto-creates jobs; the owner manages them in admin.
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

"""SQLAlchemy 2.x entities (JPA @Entity). Sessions come from app/db.py."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

ROLE_COUNTER = "Counter / Cashier"
STATUS_SUBMITTED = "submitted"
STATUS_REVIEWED = "reviewed"

YES_NO = ("yes", "no")

# Stable slugs stored on Application.hear_about; labels shown in the UI.
HEAR_ABOUT_CHOICES: tuple[tuple[str, str], ...] = (
    ("walked_in", "Walked in"),
    ("facebook", "Facebook"),
    ("instagram", "Instagram"),
    ("friend", "Friend"),
    ("other", "Other"),
)
HEAR_ABOUT_LABELS = dict(HEAR_ABOUT_CHOICES)
HEAR_ABOUT_SLUGS = frozenset(HEAR_ABOUT_LABELS)

# SQLite create_all will not ALTER existing tables. init_db adds these if missing.
APPLICATION_NEW_COLUMNS: tuple[tuple[str, str], ...] = (
    ("weekends", "VARCHAR(8) DEFAULT '' NOT NULL"),
    ("start_date", "VARCHAR(32) DEFAULT '' NOT NULL"),
    ("hours_per_week", "VARCHAR(64) DEFAULT '' NOT NULL"),
    ("age_18", "VARCHAR(8) DEFAULT '' NOT NULL"),
    ("work_auth", "VARCHAR(8) DEFAULT '' NOT NULL"),
    ("been_in_shop", "VARCHAR(8) DEFAULT '' NOT NULL"),
    ("prior_counter", "VARCHAR(8) DEFAULT '' NOT NULL"),
    ("prior_where", "VARCHAR(255) DEFAULT '' NOT NULL"),
    ("why_shop", "TEXT DEFAULT '' NOT NULL"),
    ("hear_about", "VARCHAR(32) DEFAULT '' NOT NULL"),
    ("resume_path", "VARCHAR(255) DEFAULT '' NOT NULL"),
)


class User(Base):
    """Applicant or seeded admin. is_admin is never set from public signup."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    application: Mapped[Application | None] = relationship(
        "Application", back_populates="user", uselist=False
    )


class Application(Base):
    """One job application per account. Optional resume PDF (local disk or GCS)."""

    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("user_id", name="uq_applications_user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(64), nullable=False)
    availability: Mapped[str] = mapped_column(Text, nullable=False, default="")
    role: Mapped[str] = mapped_column(String(64), nullable=False, default=ROLE_COUNTER)
    weekends: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    start_date: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    hours_per_week: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    age_18: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    work_auth: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    been_in_shop: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    prior_counter: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    prior_where: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    why_shop: Mapped[str] = mapped_column(Text, nullable=False, default="")
    hear_about: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    resume_path: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=STATUS_SUBMITTED)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship("User", back_populates="application")

    @property
    def hear_about_label(self) -> str:
        return HEAR_ABOUT_LABELS.get(self.hear_about, self.hear_about or "")

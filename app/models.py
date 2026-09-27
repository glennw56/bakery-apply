"""SQLAlchemy 2.x entities (JPA @Entity). Sessions come from app/db.py."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

ROLE_COUNTER = "Counter / Cashier"
STATUS_SUBMITTED = "submitted"
STATUS_REVIEWED = "reviewed"

SEED_POSITION_TITLE = ROLE_COUNTER
SEED_POSITION_HOURS = 40
SEED_POSITION_PAY_CENTS = 1300
SEED_POSITION_DESCRIPTION = (
    "Greet guests, help them pick from the case, ring up orders, keep the front clean, "
    "and learn the week's menu. Bakery or coffee experience is nice, not required. "
    "Weekends matter. This is a small family shop, not a chain."
)

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
    ("position_id", "INTEGER"),
)

PROVIDER_PASSWORD = "password"
PROVIDER_GOOGLE = "google"

# create_all makes the table on a fresh DB. init_db ALTERs missing columns on existing files.
USER_NEW_COLUMNS: tuple[tuple[str, str], ...] = (
    ("google_sub", "VARCHAR(255)"),
    ("provider", "VARCHAR(32) DEFAULT 'password' NOT NULL"),
)

POSITION_NEW_COLUMNS: tuple[tuple[str, str], ...] = (
    ("title", "VARCHAR(128) DEFAULT '' NOT NULL"),
    ("hours_per_week", "INTEGER DEFAULT 0 NOT NULL"),
    ("hourly_pay_cents", "INTEGER DEFAULT 0 NOT NULL"),
    ("open", "BOOLEAN DEFAULT 1 NOT NULL"),
    ("description", "TEXT DEFAULT '' NOT NULL"),
)


def format_hourly_pay(cents: int) -> str:
    """1300 -> $13/hour. Uneven cents keep two decimals."""
    cents = int(cents)
    if cents % 100 == 0:
        return f"${cents // 100}/hour"
    return f"${cents / 100:.2f}/hour"


class User(Base):
    """Applicant or seeded admin. is_admin is never set from public signup."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # google_sub is NULL for password-only accounts. Unique so one Google account
    # maps to one user. provider is "password" or "google".
    google_sub: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    provider: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=PROVIDER_PASSWORD,
        server_default=PROVIDER_PASSWORD,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    application: Mapped[Application | None] = relationship(
        "Application", back_populates="user", uselist=False
    )


class Position(Base):
    """A job opening. Public home lists open rows only; admin can add/edit/close."""

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    hours_per_week: Mapped[int] = mapped_column(Integer, nullable=False)
    hourly_pay_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    @property
    def hourly_pay_display(self) -> str:
        return format_hourly_pay(self.hourly_pay_cents)

    @property
    def hours_label(self) -> str:
        return f"{int(self.hours_per_week)} hours/week"

    @property
    def pay_dollars_input(self) -> str:
        cents = int(self.hourly_pay_cents)
        if cents % 100 == 0:
            return str(cents // 100)
        return f"{cents / 100:.2f}"


class Application(Base):
    """One job application per account. Optional resume PDF (local disk or GCS).

    role is a title snapshot from the position at submit time. position_id is the
    live row (may later be renamed or closed).
    """

    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("user_id", name="uq_applications_user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(64), nullable=False)
    availability: Mapped[str] = mapped_column(Text, nullable=False, default="")
    role: Mapped[str] = mapped_column(String(64), nullable=False, default=ROLE_COUNTER)
    position_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
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

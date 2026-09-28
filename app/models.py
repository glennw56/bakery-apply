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

STARTING_OUT_LABEL = "Starting out"

# Ronald's entry-level tasting opening. Startup does not insert this.
# Hours were not set; create_tasting_position() takes hours_per_week.
# Talent creates the Firestore doc after merge. Do not write prod from here.
TASTING_TITLE = "Tasting"
TASTING_PAY_MIN_CENTS = 1200
TASTING_PAY_MAX_CENTS = 1400
TASTING_DESCRIPTION = (
    "Offer samples from the case, tell guests what came out of the oven, "
    "and keep the tasting spot tidy. No bakery experience required."
)

POSITION_NEW_COLUMNS: tuple[tuple[str, str], ...] = (
    ("title", "VARCHAR(128) DEFAULT '' NOT NULL"),
    ("hours_per_week", "INTEGER DEFAULT 0 NOT NULL"),
    ("hourly_pay_cents", "INTEGER DEFAULT 0 NOT NULL"),
    ("open", "BOOLEAN DEFAULT 1 NOT NULL"),
    ("description", "TEXT DEFAULT '' NOT NULL"),
    # Nullable so an existing row can omit them. Load falls back to hourly_pay_cents.
    ("hourly_pay_min_cents", "INTEGER"),
    ("hourly_pay_max_cents", "INTEGER"),
    # Entry-level flag. Missing or false does not show "Starting out".
    ("starting_out", "BOOLEAN DEFAULT 0 NOT NULL"),
)


def _format_dollars(cents: int) -> str:
    """1300 -> $13. 1350 -> $13.50. Whole dollars drop the decimals."""
    cents = int(cents)
    if cents % 100 == 0:
        return f"${cents // 100}"
    return f"${cents / 100:.2f}"


def format_hourly_pay(cents: int) -> str:
    """1300 -> $13/hour. Uneven cents keep two decimals."""
    return f"{_format_dollars(cents)}/hour"


def _ordered_pay_bounds(min_cents: int, max_cents: int) -> tuple[int, int]:
    lo = int(min_cents)
    hi = int(max_cents)
    if hi < lo:
        return hi, lo
    return lo, hi


def format_starting_hourly_pay(min_cents: int, max_cents: int | None = None) -> str:
    """Public hiring copy. Dollar sign follows "starting at".

    A wider range keeps both ends: 1200, 1400 -> starting at $12–14/hour.
    Equal ends stay one rate: 1400, 1400 -> starting at $14/hour.
    A single amount stays that rate: 1350 -> starting at $13.50/hour.
    """
    lo = int(min_cents)
    if max_cents is None:
        return f"starting at {format_hourly_pay(lo)}"
    return f"starting at {format_hourly_pay_range(lo, max_cents)}"


def format_hourly_pay_range(min_cents: int, max_cents: int) -> str:
    """Admin range. Equal ends stay one rate ($14/hour). A wider range is $12–14/hour (en dash, one $)."""
    lo, hi = _ordered_pay_bounds(min_cents, max_cents)
    if lo == hi:
        return format_hourly_pay(lo)
    high = _format_dollars(hi)
    if high.startswith("$"):
        high = high[1:]
    return f"{_format_dollars(lo)}\u2013{high}/hour"


def format_pay_dollars_input(cents: int) -> str:
    """Cents for an admin number input: 1300 -> 13, 1350 -> 13.50."""
    cents = int(cents)
    if cents % 100 == 0:
        return str(cents // 100)
    return f"{cents / 100:.2f}"


def resolve_hourly_bounds(
    min_cents: int | None,
    max_cents: int | None,
    legacy_cents: int | None,
) -> tuple[int, int]:
    """If min and max are missing, both ends come from legacy hourly_pay_cents."""
    if min_cents is None and max_cents is None:
        base = int(legacy_cents or 0)
        return base, base
    if min_cents is None:
        lo = int(legacy_cents) if legacy_cents is not None else int(max_cents)
    else:
        lo = int(min_cents)
    hi = lo if max_cents is None else int(max_cents)
    return lo, hi


def coerce_starting_out(value) -> bool:
    """Checkbox / Firestore flag. Missing means not entry-level."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "on", "yes"}


def position_pay_writes(
    *,
    hourly_pay_cents: int | None = None,
    hourly_pay_min_cents: int | None = None,
    hourly_pay_max_cents: int | None = None,
) -> dict[str, int]:
    """Values to persist. hourly_pay_cents stays equal to the minimum for old readers."""
    lo, hi = resolve_hourly_bounds(hourly_pay_min_cents, hourly_pay_max_cents, hourly_pay_cents)
    return {
        "hourly_pay_cents": lo,
        "hourly_pay_min_cents": lo,
        "hourly_pay_max_cents": hi,
    }


class HourlyPayMixin:
    """Shared pay-range and experience display for SQLite rows and Firestore docs."""

    @property
    def _resolved_pay_bounds(self) -> tuple[int, int]:
        return resolve_hourly_bounds(
            self.hourly_pay_min_cents,
            self.hourly_pay_max_cents,
            self.hourly_pay_cents,
        )

    @property
    def hourly_pay_display(self) -> str:
        """Public cards and job pages: starting at the rate, or the full range when the ends differ."""
        lo, hi = self._resolved_pay_bounds
        return format_starting_hourly_pay(lo, hi)

    @property
    def hourly_pay_range_display(self) -> str:
        """Full from–to rate. Admin keeps this beside the pay fields."""
        lo, hi = self._resolved_pay_bounds
        return format_hourly_pay_range(lo, hi)

    @property
    def hours_label(self) -> str:
        return f"{int(self.hours_per_week)} hours/week"

    @property
    def experience_display(self) -> str:
        return STARTING_OUT_LABEL if self.starting_out else ""

    def _role_meta(self, pay: str) -> str:
        line = f"{int(self.hours_per_week)} hours/week · {pay}"
        if self.starting_out:
            line = f"{line} · {STARTING_OUT_LABEL}"
        return line

    @property
    def role_meta(self) -> str:
        """Public hiring meta. Starting out stays a separate label."""
        return self._role_meta(self.hourly_pay_display)

    @property
    def admin_role_meta(self) -> str:
        """Admin list line. Shows the full range so from/to edits stay obvious."""
        return self._role_meta(self.hourly_pay_range_display)

    @property
    def pay_min_dollars_input(self) -> str:
        lo, _hi = self._resolved_pay_bounds
        return format_pay_dollars_input(lo)

    @property
    def pay_max_dollars_input(self) -> str:
        _lo, hi = self._resolved_pay_bounds
        return format_pay_dollars_input(hi)

    @property
    def pay_dollars_input(self) -> str:
        return self.pay_min_dollars_input


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


class Position(HourlyPayMixin, Base):
    """A job opening. Public home lists open rows only; admin can add/edit/close."""

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    hours_per_week: Mapped[int] = mapped_column(Integer, nullable=False)
    # Legacy single rate. New writes set this to the range minimum.
    hourly_pay_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    hourly_pay_min_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hourly_pay_max_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    starting_out: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")


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

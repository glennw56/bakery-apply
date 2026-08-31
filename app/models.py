"""SQLAlchemy 2.x entities (JPA @Entity). Sessions come from app/db.py."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

ROLE_COUNTER = "Counter / Cashier"
STATUS_SUBMITTED = "submitted"
STATUS_REVIEWED = "reviewed"


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
    """One job application per account. No resume PDF."""

    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("user_id", name="uq_applications_user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(64), nullable=False)
    availability: Mapped[str] = mapped_column(Text, nullable=False, default="")
    role: Mapped[str] = mapped_column(String(64), nullable=False, default=ROLE_COUNTER)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=STATUS_SUBMITTED)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship("User", back_populates="application")

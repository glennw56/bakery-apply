"""Local SQLite vs Cloud Run Firestore+GCS. Env is read live (not cached)."""

from __future__ import annotations

import os


def gcp_project() -> str:
    return (
        os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT") or ""
    ).strip()


def gcs_bucket() -> str:
    return (os.environ.get("GCS_BUCKET") or "").strip()


def firestore_database() -> str:
    raw = (os.environ.get("FIRESTORE_DATABASE") or "").strip()
    return raw or "(default)"


def firestore_collection() -> str:
    raw = (os.environ.get("FIRESTORE_COLLECTION") or "").strip()
    return raw or "applications"


def use_cloud_backend() -> bool:
    """True only when project AND bucket are both set. Otherwise SQLite + data/resumes/."""
    return bool(gcp_project() and gcs_bucket())


def session_https_only() -> bool:
    """Secure session cookie on Cloud Run (K_SERVICE) or when SESSION_HTTPS=1."""
    if (os.environ.get("K_SERVICE") or "").strip():
        return True
    return (os.environ.get("SESSION_HTTPS") or "").strip() == "1"


def resume_attachment_name(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in " -_" else "-" for c in (name or "").strip())
    cleaned = cleaned.strip(" -_") or "applicant"
    return f"{cleaned}-resume.pdf"

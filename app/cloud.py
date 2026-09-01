"""Firestore native + GCS adapter. Import only from open_store() when cloud env is set.

google-cloud-* are imported inside CloudStore so local SQLite tests do not load them
or need credentials. Users: collection `users` (email unique). Applications:
FIRESTORE_COLLECTION (default `applications`), one per user_id.
PDFs: gs://$GCS_BUCKET/resumes/{id}.pdf — bucket stays private; admin download streams.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

from fastapi.responses import StreamingResponse

from app.backend import (
    firestore_collection,
    firestore_database,
    gcp_project,
    gcs_bucket,
    resume_attachment_name,
)
from app.models import HEAR_ABOUT_LABELS, ROLE_COUNTER, STATUS_REVIEWED, STATUS_SUBMITTED

USERS_COLLECTION = "users"


def _naive_utc(dt) -> datetime | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class CloudUser:
    def __init__(
        self,
        id: str,
        email: str,
        password_hash: str,
        is_admin: bool,
        created_at: datetime | None = None,
    ) -> None:
        self.id = id
        self.email = email
        self.password_hash = password_hash
        self.is_admin = bool(is_admin)
        self.created_at = created_at


class CloudApplication:
    def __init__(self, id: str, data: dict) -> None:
        self.id = id
        self.user_id = data.get("user_id") or ""
        self.name = data.get("name") or ""
        self.phone = data.get("phone") or ""
        self.availability = data.get("availability") or ""
        self.role = data.get("role") or ROLE_COUNTER
        self.weekends = data.get("weekends") or ""
        self.start_date = data.get("start_date") or ""
        self.hours_per_week = data.get("hours_per_week") or ""
        self.age_18 = data.get("age_18") or ""
        self.work_auth = data.get("work_auth") or ""
        self.been_in_shop = data.get("been_in_shop") or ""
        self.prior_counter = data.get("prior_counter") or ""
        self.prior_where = data.get("prior_where") or ""
        self.why_shop = data.get("why_shop") or ""
        self.hear_about = data.get("hear_about") or ""
        self.resume_path = data.get("resume_path") or ""
        self.status = data.get("status") or STATUS_SUBMITTED
        self.submitted_at = _naive_utc(data.get("submitted_at")) or datetime.now(
            timezone.utc
        ).replace(tzinfo=None)
        self.reviewed_at = _naive_utc(data.get("reviewed_at"))

    @property
    def hear_about_label(self) -> str:
        return HEAR_ABOUT_LABELS.get(self.hear_about, self.hear_about or "")


class CloudStore:
    def __init__(self) -> None:
        from google.cloud import firestore, storage

        project = gcp_project()
        database = firestore_database()
        self._bucket_name = gcs_bucket()
        self._apps_col = firestore_collection()
        self._fs = firestore.Client(project=project, database=database)
        self._gcs = storage.Client(project=project)
        self._bucket = self._gcs.bucket(self._bucket_name)
        self._Query = firestore.Query

    def close(self) -> None:
        return None

    def _field_filter(self, field: str, op: str, value):
        from google.cloud.firestore_v1.base_query import FieldFilter

        return FieldFilter(field, op, value)

    def _user_from_doc(self, doc) -> CloudUser:
        data = doc.to_dict() or {}
        return CloudUser(
            id=doc.id,
            email=data.get("email") or "",
            password_hash=data.get("password_hash") or "",
            is_admin=bool(data.get("is_admin")),
            created_at=_naive_utc(data.get("created_at")),
        )

    def _app_from_doc(self, doc) -> CloudApplication:
        return CloudApplication(doc.id, doc.to_dict() or {})

    def get_user_by_id(self, user_id) -> CloudUser | None:
        if user_id is None or user_id == "":
            return None
        doc = self._fs.collection(USERS_COLLECTION).document(str(user_id)).get()
        if not doc.exists:
            return None
        return self._user_from_doc(doc)

    def get_user_by_email(self, email: str) -> CloudUser | None:
        docs = (
            self._fs.collection(USERS_COLLECTION)
            .where(filter=self._field_filter("email", "==", email))
            .limit(1)
            .stream()
        )
        for doc in docs:
            return self._user_from_doc(doc)
        return None

    def create_user(self, email: str, password_hash: str, is_admin: bool = False) -> CloudUser:
        ref = self._fs.collection(USERS_COLLECTION).document()
        payload = {
            "email": email,
            "password_hash": password_hash,
            "is_admin": bool(is_admin),
            "created_at": datetime.now(timezone.utc),
        }
        ref.set(payload)
        return CloudUser(
            id=ref.id,
            email=email,
            password_hash=password_hash,
            is_admin=bool(is_admin),
            created_at=_naive_utc(payload["created_at"]),
        )

    def upsert_admin(self, email: str, password_hash: str) -> CloudUser:
        user = self.get_user_by_email(email)
        if user is None:
            return self.create_user(email, password_hash, is_admin=True)
        self._fs.collection(USERS_COLLECTION).document(user.id).update(
            {"password_hash": password_hash, "is_admin": True}
        )
        user.password_hash = password_hash
        user.is_admin = True
        return user

    def get_application_for_user(self, user_id) -> CloudApplication | None:
        docs = (
            self._fs.collection(self._apps_col)
            .where(filter=self._field_filter("user_id", "==", str(user_id)))
            .limit(1)
            .stream()
        )
        for doc in docs:
            return self._app_from_doc(doc)
        return None

    def get_application(self, app_id) -> CloudApplication | None:
        if app_id is None or app_id == "":
            return None
        doc = self._fs.collection(self._apps_col).document(str(app_id)).get()
        if not doc.exists:
            return None
        return self._app_from_doc(doc)

    def list_applications(self) -> list[CloudApplication]:
        docs = (
            self._fs.collection(self._apps_col)
            .order_by("submitted_at", direction=self._Query.DESCENDING)
            .stream()
        )
        return [self._app_from_doc(doc) for doc in docs]

    def create_application(self, **fields) -> CloudApplication:
        submitted = fields.get("submitted_at") or datetime.now(timezone.utc)
        if isinstance(submitted, datetime) and submitted.tzinfo is None:
            submitted = submitted.replace(tzinfo=timezone.utc)
        payload = {
            "user_id": str(fields["user_id"]),
            "name": fields.get("name") or "",
            "phone": fields.get("phone") or "",
            "availability": fields.get("availability") or "",
            "role": fields.get("role") or ROLE_COUNTER,
            "weekends": fields.get("weekends") or "",
            "start_date": fields.get("start_date") or "",
            "hours_per_week": fields.get("hours_per_week") or "",
            "age_18": fields.get("age_18") or "",
            "work_auth": fields.get("work_auth") or "",
            "been_in_shop": fields.get("been_in_shop") or "",
            "prior_counter": fields.get("prior_counter") or "",
            "prior_where": fields.get("prior_where") or "",
            "why_shop": fields.get("why_shop") or "",
            "hear_about": fields.get("hear_about") or "",
            "resume_path": fields.get("resume_path") or "",
            "status": fields.get("status") or STATUS_SUBMITTED,
            "submitted_at": submitted,
            "reviewed_at": fields.get("reviewed_at"),
        }
        ref = self._fs.collection(self._apps_col).document()
        ref.set(payload)
        return CloudApplication(ref.id, payload)

    def save_resume(self, application: CloudApplication, blob: bytes) -> str:
        object_name = f"resumes/{application.id}.pdf"
        gcs_blob = self._bucket.blob(object_name)
        gcs_blob.upload_from_string(blob, content_type="application/pdf")
        # Do not make the object or bucket public. Admin download uses this client.
        gs_uri = f"gs://{self._bucket_name}/{object_name}"
        self._fs.collection(self._apps_col).document(application.id).update(
            {"resume_path": gs_uri}
        )
        application.resume_path = gs_uri
        return gs_uri

    def mark_reviewed(self, application: CloudApplication) -> CloudApplication:
        reviewed_at = datetime.now(timezone.utc)
        self._fs.collection(self._apps_col).document(application.id).update(
            {"status": STATUS_REVIEWED, "reviewed_at": reviewed_at}
        )
        application.status = STATUS_REVIEWED
        application.reviewed_at = _naive_utc(reviewed_at)
        return application

    def resume_response(self, application: CloudApplication) -> StreamingResponse | None:
        rel = (application.resume_path or "").strip()
        if not rel:
            return None
        object_name = f"resumes/{application.id}.pdf"
        if rel.startswith("gs://"):
            without = rel[5:]
            _bucket, _, rest = without.partition("/")
            if rest:
                object_name = rest
        gcs_blob = self._bucket.blob(object_name)
        if not gcs_blob.exists():
            return None
        filename = resume_attachment_name(application.name)
        quoted = quote(filename)

        def chunks():
            with gcs_blob.open("rb") as fh:
                while True:
                    chunk = fh.read(65536)
                    if not chunk:
                        break
                    yield chunk

        return StreamingResponse(
            chunks(),
            media_type="application/pdf",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{filename}"; filename*=utf-8\'\'{quoted}'
                )
            },
        )

"""Firestore native + GCS adapter. Import only from open_store() when cloud env is set.

google-cloud-* are imported inside CloudStore so local SQLite tests do not load them
or need credentials. Users: collection `users` (email unique). Applications:
FIRESTORE_COLLECTION (default `applications`), one per user_id.
Positions: collection `positions`.
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
from app.models import (
    HEAR_ABOUT_LABELS,
    PROVIDER_GOOGLE,
    PROVIDER_PASSWORD,
    ROLE_COUNTER,
    STATUS_REVIEWED,
    STATUS_SUBMITTED,
    HourlyPayMixin,
    coerce_starting_out,
    normalize_description,
    position_pay_writes,
    resolve_hourly_bounds,
)

USERS_COLLECTION = "users"
POSITIONS_COLLECTION = "positions"


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
        google_sub: str | None = None,
        provider: str = PROVIDER_PASSWORD,
    ) -> None:
        self.id = id
        self.email = email
        self.password_hash = password_hash
        self.is_admin = bool(is_admin)
        self.created_at = created_at
        self.google_sub = google_sub or None
        self.provider = provider or PROVIDER_PASSWORD


class CloudPosition(HourlyPayMixin):
    def __init__(self, id: str, data: dict) -> None:
        self.id = id
        self.title = data.get("title") or ""
        self.hours_per_week = int(data.get("hours_per_week") or 0)
        legacy = data.get("hourly_pay_cents")
        min_raw = data.get("hourly_pay_min_cents")
        max_raw = data.get("hourly_pay_max_cents")
        lo, hi = resolve_hourly_bounds(
            int(min_raw) if min_raw is not None else None,
            int(max_raw) if max_raw is not None else None,
            int(legacy) if legacy is not None else None,
        )
        self.hourly_pay_min_cents = lo
        self.hourly_pay_max_cents = hi
        # Leave a stored single rate alone on read. Missing legacy follows the minimum.
        self.hourly_pay_cents = int(legacy) if legacy is not None else lo
        self.open = bool(data.get("open"))
        self.description = data.get("description") or ""
        self.starting_out = coerce_starting_out(data.get("starting_out"))


class CloudApplication:
    def __init__(self, id: str, data: dict) -> None:
        self.id = id
        self.user_id = data.get("user_id") or ""
        self.name = data.get("name") or ""
        self.phone = data.get("phone") or ""
        self.availability = data.get("availability") or ""
        self.role = data.get("role") or ROLE_COUNTER
        self.position_id = data.get("position_id") or ""
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
            google_sub=(data.get("google_sub") or None),
            provider=data.get("provider") or PROVIDER_PASSWORD,
        )

    def _app_from_doc(self, doc) -> CloudApplication:
        return CloudApplication(doc.id, doc.to_dict() or {})

    def _pos_from_doc(self, doc) -> CloudPosition:
        return CloudPosition(doc.id, doc.to_dict() or {})

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

    def get_user_by_google_sub(self, google_sub: str) -> CloudUser | None:
        sub = (google_sub or "").strip()
        if not sub:
            return None
        docs = (
            self._fs.collection(USERS_COLLECTION)
            .where(filter=self._field_filter("google_sub", "==", sub))
            .limit(1)
            .stream()
        )
        for doc in docs:
            return self._user_from_doc(doc)
        return None

    def create_user(
        self,
        email: str,
        password_hash: str,
        is_admin: bool = False,
        google_sub: str | None = None,
        provider: str = PROVIDER_PASSWORD,
    ) -> CloudUser:
        ref = self._fs.collection(USERS_COLLECTION).document()
        sub = (google_sub or "").strip() or None
        payload = {
            "email": email,
            "password_hash": password_hash,
            "is_admin": bool(is_admin),
            "google_sub": sub,
            "provider": provider or PROVIDER_PASSWORD,
            "created_at": datetime.now(timezone.utc),
        }
        ref.set(payload)
        return CloudUser(
            id=ref.id,
            email=email,
            password_hash=password_hash,
            is_admin=bool(is_admin),
            created_at=_naive_utc(payload["created_at"]),
            google_sub=sub,
            provider=payload["provider"],
        )

    def link_google(self, user: CloudUser, google_sub: str) -> CloudUser:
        """Attach a verified Google subject. Keeps any existing password hash."""
        sub = google_sub.strip()
        self._fs.collection(USERS_COLLECTION).document(user.id).update(
            {"google_sub": sub, "provider": PROVIDER_GOOGLE}
        )
        user.google_sub = sub
        user.provider = PROVIDER_GOOGLE
        return user

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
        position_id = fields.get("position_id")
        payload = {
            "user_id": str(fields["user_id"]),
            "name": fields.get("name") or "",
            "phone": fields.get("phone") or "",
            "availability": fields.get("availability") or "",
            "role": fields.get("role") or ROLE_COUNTER,
            "position_id": "" if position_id is None else str(position_id),
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

    def list_positions(self) -> list[CloudPosition]:
        docs = self._fs.collection(POSITIONS_COLLECTION).stream()
        rows = [self._pos_from_doc(doc) for doc in docs]
        rows.sort(key=lambda p: (p.title.lower(), str(p.id)))
        return rows

    def list_open_positions(self) -> list[CloudPosition]:
        return [p for p in self.list_positions() if p.open]

    def get_position(self, position_id) -> CloudPosition | None:
        if position_id is None or position_id == "":
            return None
        doc = self._fs.collection(POSITIONS_COLLECTION).document(str(position_id)).get()
        if not doc.exists:
            return None
        return self._pos_from_doc(doc)

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
    ) -> CloudPosition:
        ref = self._fs.collection(POSITIONS_COLLECTION).document()
        pay = position_pay_writes(
            hourly_pay_cents=hourly_pay_cents,
            hourly_pay_min_cents=hourly_pay_min_cents,
            hourly_pay_max_cents=hourly_pay_max_cents,
        )
        payload = {
            "title": title.strip(),
            "hours_per_week": int(hours_per_week),
            "hourly_pay_cents": int(pay["hourly_pay_cents"]),
            "hourly_pay_min_cents": int(pay["hourly_pay_min_cents"]),
            "hourly_pay_max_cents": int(pay["hourly_pay_max_cents"]),
            "starting_out": coerce_starting_out(starting_out),
            "open": bool(open),
            "description": normalize_description(description),
        }
        ref.set(payload)
        return CloudPosition(ref.id, payload)

    def update_position(self, position: CloudPosition, **fields) -> CloudPosition:
        allowed = (
            "title",
            "hours_per_week",
            "hourly_pay_cents",
            "hourly_pay_min_cents",
            "hourly_pay_max_cents",
            "starting_out",
            "open",
            "description",
        )
        int_keys = {
            "hours_per_week",
            "hourly_pay_cents",
            "hourly_pay_min_cents",
            "hourly_pay_max_cents",
        }
        payload = {}
        for key in allowed:
            if key not in fields:
                continue
            value = fields[key]
            if key == "description":
                value = normalize_description(value if isinstance(value, str) else "")
            elif key == "title":
                value = (value or "").strip() if isinstance(value, str) else value
            elif key in ("open", "starting_out"):
                value = coerce_starting_out(value) if key == "starting_out" else bool(value)
            elif key in int_keys:
                value = int(value)
            payload[key] = value
            setattr(position, key, value)
        if "hourly_pay_min_cents" in payload and "hourly_pay_cents" not in payload:
            payload["hourly_pay_cents"] = payload["hourly_pay_min_cents"]
            position.hourly_pay_cents = payload["hourly_pay_cents"]
        if payload:
            self._fs.collection(POSITIONS_COLLECTION).document(str(position.id)).update(payload)
        return position

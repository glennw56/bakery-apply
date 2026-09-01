# Sunshine's Bakery — Apply

## What this is

Public job-apply site for **Sunshine's Bakery** (Irondale, AL). One live role (Counter / Cashier), applicant signup/login, one application per account, optional resume PDF, seeded admin list. FastAPI + Jinja + HTMX.

**Shop:** 2231 1st Ave S, Irondale AL 35210 · (205) 602-3485

**Persistence:** locally, one SQLite file (`data/app.db`, WAL) and resume PDFs under `data/resumes/`. On Cloud Run, when `GCS_BUCKET` and `GOOGLE_CLOUD_PROJECT` (or `GCP_PROJECT`) are set, users + applications go to Firestore native and resume PDFs go to a private GCS bucket. Skip Cloud SQL.

**Not in git:** `.env`, the live sqlite file, resume PDFs, Square tokens / API keys (this app does not use Square). `data/*` is gitignored except `data/.gitkeep`. Copy `.env.example` to `.env` and set `SESSION_SECRET`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`.

v1 does **not** post jobs, email candidates, or talk about wages. There is no second location and no public `/register-admin`. An optional resume PDF can be uploaded on the apply form (`%PDF` magic, 5 MB max). `/docs`, `/redoc`, and `/openapi.json` are disabled (404).

## Quick start

From the repo root (Python 3.12+):

```bash
./scripts/setup.sh
./scripts/run.sh
```

Open http://127.0.0.1:8000

`setup.sh` creates `.venv`, installs `requirements.txt`, copies `.env.example` → `.env` if missing, and makes `data/`. `run.sh` sources `.env` and starts uvicorn (`HOST=127.0.0.1`, `PORT=8000`, `RELOAD=1` by default). Same thing via `make setup` then `make run`.

Admin is **not** a public signup. On startup the app creates/updates the user in `ADMIN_EMAIL` with `ADMIN_PASSWORD` and `is_admin=true`. Log in at `/login`, then `/admin`.

htmx 2.x is vendored at `static/htmx.min.js` (offline).

## Screens

| Route | What |
| --- | --- |
| `GET /` | Public hiring page — Irondale shop, live Counter / Cashier role |
| `GET`/`POST /signup` | Applicant account (email + password). `is_admin` is ignored if sent |
| `GET`/`POST /login` | Session cookie login |
| `POST /logout` | Clear session |
| `GET`/`POST /apply` | Logged-in applicant form: name, phone, availability, role, Talent screening, optional resume PDF |
| `GET /application` | Own application + status (`submitted` / `reviewed`). Shows “Resume attached (PDF)” if a file was uploaded; does not serve the file |
| `GET /admin` | Admin-only list (name, phone, availability, role, submitted_at, status) |
| `POST /admin/applications/{id}/review` | Mark reviewed (HTMX swaps the row) |
| `GET /admin/applications/{id}/resume` | Admin-only PDF download (`{name}-resume.pdf`). 404 if none. Streams from local disk or GCS. `/data/resumes` is not a public static path |

Unauthenticated `/admin` redirects to `/login`. There is no `/register-admin`.

## Spring Boot + Angular map

Keep this stack — do not rewrite it in Java or Angular. The mapping is small:

| You already know | Here |
| --- | --- |
| `@Controller` / `@RestController` methods | FastAPI routes in `app/main.py` (`@app.get`, `@app.post`) |
| JPA `@Entity` + repository | SQLAlchemy 2.x models in `app/models.py` locally; `app/store.py` (SQLite) or `app/cloud.py` (Firestore+GCS) |
| `spring.datasource.url` (H2 file) | `BAKERY_APPLY_DB` or `DATABASE_URL` → `data/app.db` (WAL) when GCS is unset. See `app/db.py` |
| Spring Security user + `BCryptPasswordEncoder` | `app/auth.py` (`passlib` bcrypt) + Starlette `SessionMiddleware` cookie |
| `@PostConstruct` admin seed / `application.yml` | Lifespan: `init_db()` + `seed_admin()` from `ADMIN_EMAIL` / `ADMIN_PASSWORD` |
| Angular component + HTTP client | Jinja templates render HTML on the server. HTMX (`hx-post`, `hx-target`) swaps a fragment in place — like a server-rendered partial, not a SPA |
| `spring-boot:run` with restart | `./scripts/run.sh` (`RELOAD=1` → uvicorn `--reload`) |
| `mvn test` | `./scripts/test.sh` or `make test` |
| Optional Docker / Cloud Run | `Dockerfile` + `docker-compose.yml` — listen on `0.0.0.0` and `$PORT`, non-root |

`templates/admin/_row.html` is the fragment (one application row). Mark reviewed posts into that row and never full-reloads. That is the whole “frontend.”

## Recreate from GitHub

Repo is **private** over SSH: `git@github.com:glennw56/bakery-apply.git`.

```bash
git clone git@github.com:glennw56/bakery-apply.git
cd bakery-apply
./scripts/setup.sh
./scripts/run.sh
```

Then http://127.0.0.1:8000. Edit `.env` so `SESSION_SECRET` and `ADMIN_PASSWORD` are not the example values. Preferred local path is venv (`setup.sh` / `run.sh`). Docker is optional:

```bash
docker compose up --build
```

## Tests

```bash
./scripts/test.sh
```

Or `make test`, or `PYTHONPATH=. .venv/bin/pytest -q`. Uses a throwaway sqlite file (`BAKERY_APPLY_DB` tempfile); does not touch `data/app.db`. GCP clients are lazy-imported, so local tests do not need credentials. Covers signup, login, submit application (with and without optional PDF), rejected non-PDF, admin list + resume download, unauthenticated `/admin` and resume GET, no public admin register, no wage text on pages, `/docs` and `/openapi.json` 404, session `https_only` false without `K_SERVICE`.

## Env

| Variable | What |
| --- | --- |
| `SESSION_SECRET` | Cookie signing key (itsdangerous / Starlette sessions) |
| `ADMIN_EMAIL` | Seeded admin email (create/update on startup, `is_admin=true`) |
| `ADMIN_PASSWORD` | Seeded admin password |
| `BAKERY_APPLY_DB` | SQLite file path (default `data/app.db`). Used only when cloud env is unset |
| `DATABASE_URL` | Optional; if set, wins over `BAKERY_APPLY_DB` (e.g. `sqlite:///data/app.db`) |
| `HOST` | uvicorn bind (local default `127.0.0.1`; Docker/Cloud Run `0.0.0.0`) |
| `PORT` | uvicorn port (default `8000`; Cloud Run injects this) |
| `GOOGLE_CLOUD_PROJECT` | GCP project. Also accepts `GCP_PROJECT`. Glenn default: `bakery-444323` |
| `GCP_PROJECT` | Alias for `GOOGLE_CLOUD_PROJECT` |
| `FIRESTORE_DATABASE` | Native Firestore database id. Default `(default)` (nam5, free tier) |
| `GCS_BUCKET` | Private resume bucket. Glenn default: `bakery-444323-apply-resumes` (us-east1, uniform, public access prevention). **Unset locally → SQLite + `data/resumes/`** |
| `FIRESTORE_COLLECTION` | Applications collection name. Default `applications`. Users stay in collection `users` |
| `K_SERVICE` | Set by Cloud Run. When present, session cookie is `https_only=True` |
| `SESSION_HTTPS` | Set to `1` to force `https_only=True` without `K_SERVICE`. Local default is false |

Cloud backend is used **only** when both `GCS_BUCKET` and `GOOGLE_CLOUD_PROJECT` (or `GCP_PROJECT`) are set. GCP client libraries are imported inside `CloudStore`, so a local pytest run never talks to GCP.

## Cloud Run (copy-paste)

Do **not** use Cloud SQL. Do **not** pass `--allow-unauthenticated`. Do **not** delete existing Cloud Run services `asd`, `getorders`, or `resetitems`. This app does not use Square and does not attach sunshinebakeshop.com.

When `GCS_BUCKET` and `GOOGLE_CLOUD_PROJECT` are set:

- Users (`users`) and applications (`FIRESTORE_COLLECTION`, default `applications`) persist in Firestore native (`FIRESTORE_DATABASE`, default `(default)`, nam5, free tier).
- Resume PDFs persist at `gs://$GCS_BUCKET/resumes/{application_id}.pdf`. The bucket stays private (uniform bucket-level access, public access prevention). Admin `GET /admin/applications/{id}/resume` (`require_admin`) streams from GCS.
- Session cookie is Secure because Cloud Run sets `K_SERVICE`.

Glenn defaults (not secrets — secrets stay in Secret Manager, never git):

| Env | Value |
| --- | --- |
| `GOOGLE_CLOUD_PROJECT` | `bakery-444323` |
| `FIRESTORE_DATABASE` | `(default)` |
| `GCS_BUCKET` | `bakery-444323-apply-resumes` |
| `FIRESTORE_COLLECTION` | `applications` |

Runtime service account needs Secret Accessor, Firestore User, and Storage Object Admin on `bakery-444323-apply-resumes`.

```bash
PROJECT_ID=bakery-444323
REGION=us-east1
IMAGE=gcr.io/${PROJECT_ID}/bakery-apply

# Secrets (once). Do not put these in git.
printf '%s' 'replace-with-long-random' | gcloud secrets create SESSION_SECRET --data-file=-
printf '%s' 'admin@example.com' | gcloud secrets create ADMIN_EMAIL --data-file=-
printf '%s' 'replace-with-strong-password' | gcloud secrets create ADMIN_PASSWORD --data-file=-

# Build + push
gcloud builds submit --tag "$IMAGE"

# Runtime service account needs Secret Accessor
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
for S in SESSION_SECRET ADMIN_EMAIL ADMIN_PASSWORD; do
  gcloud secrets add-iam-policy-binding "$S"     --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"     --role="roles/secretmanager.secretAccessor"
done

# Deploy bakery-apply only. Do not delete asd / getorders / resetitems.
# Skip Cloud SQL. Bucket stays private. No --allow-unauthenticated.
gcloud run deploy bakery-apply   --image "$IMAGE"   --region "$REGION"   --no-allow-unauthenticated   --min-instances 0   --max-instances 1   --memory 512Mi   --set-env-vars "GOOGLE_CLOUD_PROJECT=bakery-444323,FIRESTORE_DATABASE=(default),GCS_BUCKET=bakery-444323-apply-resumes,FIRESTORE_COLLECTION=applications,HOST=0.0.0.0"   --set-secrets "SESSION_SECRET=SESSION_SECRET:latest,ADMIN_EMAIL=ADMIN_EMAIL:latest,ADMIN_PASSWORD=ADMIN_PASSWORD:latest"
```

Image is `python:3.12-slim`, non-root `appuser`, listens on `0.0.0.0:$PORT`. Dockerfile `CMD` is `scripts/docker-entrypoint.sh`.

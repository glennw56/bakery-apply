# Deploy — Sign in with Google

Same Cloud Run service: **`bakery-apply`** in GCP project **`bakery-444323`**. Do not create a new service, and do not deploy from this change until Shop Tech reviews it.

Applicant Google sign-in is the OAuth 2.0 authorization-code flow. Admin stays on email + password (`ADMIN_EMAIL` / `ADMIN_PASSWORD`). Google login refuses `is_admin` accounts.

## Exact redirect URI

Register this on the OAuth 2.0 **Web** client (Authorized redirect URIs):

```
https://bakery-apply-k6uuoen7wa-ue.a.run.app/auth/google/callback
```

That is also the app default when `GOOGLE_REDIRECT_URI` and `PUBLIC_BASE_URL` are both unset.

## Secret Manager

Create these secrets. Do not commit the values. Keep the existing secrets `SESSION_SECRET`, `ADMIN_EMAIL`, and `ADMIN_PASSWORD`.

| Secret | What |
| --- | --- |
| `GOOGLE_CLIENT_ID` | OAuth client id (`….apps.googleusercontent.com`) |
| `GOOGLE_CLIENT_SECRET` | OAuth client secret |
| `GOOGLE_REDIRECT_URI` | `https://bakery-apply-k6uuoen7wa-ue.a.run.app/auth/google/callback` |

`GOOGLE_REDIRECT_URI` is not highly sensitive, but it is the value the token exchange sends back to Google, so keep it in Secret Manager with the other two and match the console entry exactly (no trailing slash).

Optional plain env var, not a secret: `PUBLIC_BASE_URL`. Used only when `GOOGLE_REDIRECT_URI` is unset. The callback becomes `{PUBLIC_BASE_URL}/auth/google/callback`.

```bash
PROJECT_ID=bakery-444323
REDIRECT_URI='https://bakery-apply-k6uuoen7wa-ue.a.run.app/auth/google/callback'

printf '%s' 'YOUR_CLIENT_ID' | gcloud secrets create GOOGLE_CLIENT_ID --data-file=- --project "$PROJECT_ID"
printf '%s' 'YOUR_CLIENT_SECRET' | gcloud secrets create GOOGLE_CLIENT_SECRET --data-file=- --project "$PROJECT_ID"
printf '%s' "$REDIRECT_URI" | gcloud secrets create GOOGLE_REDIRECT_URI --data-file=- --project "$PROJECT_ID"

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
for S in GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET GOOGLE_REDIRECT_URI; do
  gcloud secrets add-iam-policy-binding "$S" \
    --project "$PROJECT_ID" \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
done
```

Add them to the existing `gcloud run deploy bakery-apply` (do not change the service name):

```bash
--set-secrets "SESSION_SECRET=SESSION_SECRET:latest,ADMIN_EMAIL=ADMIN_EMAIL:latest,ADMIN_PASSWORD=ADMIN_PASSWORD:latest,GOOGLE_CLIENT_ID=GOOGLE_CLIENT_ID:latest,GOOGLE_CLIENT_SECRET=GOOGLE_CLIENT_SECRET:latest,GOOGLE_REDIRECT_URI=GOOGLE_REDIRECT_URI:latest"
```

Firestore user documents gain `google_sub` and `provider` (`password` or `google`). No new collection and no schema migration job — fields are written on the next Google sign-in. SQLite local databases add the columns on startup.

Applicant routes: `GET /auth/google/start`, `GET /auth/google/callback`. Email/password `/login` and `/signup` stay.

# Architecture

One FastAPI Cloud Run service serves the compiled Vite SPA, REST APIs and protected internal handlers. Production requires no resident background worker: a job submission persists an immutable settings snapshot, input references, idempotency fingerprint, and quota/cost reservations before enqueueing Cloud Tasks. A five-minute Cloud Scheduler maintenance request repairs enqueue gaps, reconciles expired leases and deletes expired private objects.

Firebase Auth SDK uses Identity Platform email/password authentication with server-enforced reCAPTCHA Enterprise. Firebase web-app registration is optional for this flow: the project supports direct Identity Platform configuration with a restricted public authentication API key. Backend token verification checks revocation, and authoritative Firestore profiles enforce account activation, roles and the first-login password-change gate. Direct browser Firestore access is denied.

Firestore transactions enforce shared quotas and budget reservations across Cloud Run instances. All provider calls occur outside transactions. Claims/leases and durable submission markers protect against duplicate task delivery. Asynchronous provider prediction IDs are persisted and polled. Ambiguous non-idempotent submissions become `unknown`; they are not automatically resubmitted and remain conservatively counted for cost. Polling errors can be retried without resubmitting generation.

The public service needs application-level verification of Google's task OIDC issuer, audience, expiry and exact dispatcher service-account identity. Task headers are not identity. Separate runtime, dispatcher and build accounts have scoped permissions; no service-account key files are generated.

Collections include `users`, `categories`, `garments`, `application_settings`, `uploads`, `generation_jobs`, `idempotency`, `usage_events`, user/global quota documents, monthly budgets and `shares`. Default single-field indexes serve POC queries; analytics are assembled from metadata and filtered server-side. This keeps infrastructure small, but scanning event history should be replaced with materialized aggregates before large-scale SaaS use.

Maintenance uses indexed equality queries for queued/processing jobs and pending object-cleanup markers. Successful deletion clears the marker; failed deletion remains discoverable for retry. Historical completed jobs and already-cleaned uploads are not repeatedly fetched or deleted by the five-minute schedule.

Catalog and temporary photographs use separate private buckets. Temporary storage has soft delete and versioning disabled. Application expiry is checked on every read; maintenance removes objects, and a two-day bucket lifecycle is a cleanup backstop. Metadata TTL is not used to promise immediate object deletion. User deletion disables access first and removes live photos/shares; operational metadata can remain without image content.

Gallery records and image blobs are AES-GCM encrypted in IndexedDB under the current UID. An authenticated endpoint releases that user's stable 256-bit key; it exists only in memory while signed in. The default capacity is 20; saving a result can replace the oldest after warning. Browser-cleared storage cannot be recovered from metadata.

QR sharing copies a result into short-lived private storage. A random bearer token is stored only as a SHA-256 hash. The URL places the token in a fragment; the anonymous share page POSTs it to the backend for expiry/revocation checks and image streaming with `no-store`. Local images can be uploaded again after their original server result expires.

Interfaces use Pydantic request validation and snake_case JSON. `POST /api/uploads` returns an owned upload ID; `POST /api/tryon/catalog` and `/holding-garment` return `202` job records; `/api/tryon/jobs/{id}` exposes state; result URLs require the owning user's token. Administrative endpoints require the administrator role. `/api/openapi.json` and `/api/docs` describe the API.

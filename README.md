# StyleReel

A mobile-first virtual garment try-on POC for retail demonstrations. React/TypeScript/Vite/Tailwind and FastAPI run as a single scale-to-zero Cloud Run service. Firebase Authentication/Identity Platform manages accounts, Firestore stores operational metadata, Cloud Tasks runs durable jobs, and private Cloud Storage holds catalog assets and temporary photos.

Deployed POC: [Open StyleReel](https://stylereel-ynpzfmjw7q-el.a.run.app). See [implementation and verification evidence](IMPLEMENTATION_REPORT.md).

The app has catalog and experimental held-garment workflows, compatible two-item outfits, a generated-photo view with scrollable recent looks, an encrypted per-user IndexedDB gallery, downloads and revocable QR sharing. Laptops use a live webcam preview; Android/iPhone/iPad retain native camera capture. Saree jobs add complete-outfit draping instructions. Administration covers users, garments/categories, provider settings, usage limits, and estimated-cost analytics. Checkout and physical sizing are outside this POC.

## Development

Requirements: Node 24, Python 3.12+ (development was checked with 3.14), uv or pip, Google Cloud CLI. Java 21+ and Firebase CLI are needed only for local Auth/Firestore emulators.

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r backend/requirements.txt
cd frontend
npm ci
npm run dev
```

In a second terminal, export the values in `.env.example`, then run:

```bash
PYTHONPATH=backend .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Vite proxies `/api` to port 8080. Do not commit `.env` or credentials. Public Firebase web API configuration is not a privileged provider key.

For isolated authentication/database development, start `npx firebase-tools emulators:start --project virtualtryon-511016 --only auth,firestore`, set `FIREBASE_AUTH_EMULATOR_HOST=127.0.0.1:9099` and `FIRESTORE_EMULATOR_HOST=127.0.0.1:8081`, and run `PYTHONPATH=backend .venv/bin/python -m app.bootstrap`. The local-only initial password is `admin123`, followed by a password change. Public deployment rejects this default. Storage still requires configured private buckets/ADC; `scripts/local_worker.py` can process emulator jobs in the foreground. External AI calls are real and billable, never mocked at runtime. Emulator quotas are isolated from production.

## Checks

```bash
PYTHONPATH=backend .venv/bin/pytest backend/tests -q
cd frontend
npm test
npm run build
```

Automated tests inject isolated provider/repository doubles. They do not establish live AI quality. Live evidence and any deployment limitations belong in `IMPLEMENTATION_REPORT.md`.

The generated Pydantic/OpenAPI contract is available at `/api/openapi.json`; `/api/docs` opens that contract. Import it into an OpenAPI client for authenticated API exploration.

## Deployment and accounts

See [DEPLOYMENT.md](DEPLOYMENT.md). The target project is `virtualtryon-511016`; the administrator is `joinarun@gmail.com`. The public initial password is stored in Secret Manager as `stylereel-bootstrap-password`, never source code. On first login, change it before using the application. Administrators create users; there is no public signup.

The small disclosure at the bottom explains that pressing Generate authorizes sending the photo to the active provider; no checkbox is required. Camera capture, file selection and cropping stay local until Generate is pressed. Google global inference may run outside India. Source images are deleted on terminal job completion; server results expire after 24 hours. The local gallery is device/browser specific and can be cleared by the browser. Download look creates an independent downloaded file outside application deletion control. Anyone possessing a QR link can download during its 15-minute lifetime; owners can revoke it. Clicking the top-left StyleReel logo opens a fresh studio from any page; a job already in progress still completes into the gallery.

Defaults: two billable AI calls per rolling minute, one active job per user, 20 daily calls per user, 100 globally, a $25/month conservative estimated AI ceiling, and 20 local gallery images. AI quality and provider retention limitations are described in [AI_PROVIDERS.md](AI_PROVIDERS.md). Sample image licenses are in [sample_assets/LICENSES.md](sample_assets/LICENSES.md).

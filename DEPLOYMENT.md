# Google Cloud deployment

The approved target is `virtualtryon-511016` in `asia-south1`. Inference location is separately configured as `global`. Cloud Run uses request-based billing, 1 CPU, 1 GiB RAM, minimum zero, maximum three instances, concurrency four and a 600-second timeout. Cloud Tasks dispatches at most two handlers concurrently.

## Repeatable setup

Use an authorized project administrator and billing-enabled project. The scripts explicitly pass the target project, rather than changing the CLI's current project. Inspect scripts before running in another project.

```bash
python3 scripts/cloud_setup.py
GOOGLE_CLOUD_PROJECT=virtualtryon-511016 GOOGLE_CLOUD_QUOTA_PROJECT=virtualtryon-511016 PYTHONPATH=backend .venv/bin/python -m app.bootstrap
python3 scripts/download_samples.py
STORAGE_CATALOG_BUCKET=virtualtryon-511016-stylereel-catalog STORAGE_TEMP_BUCKET=virtualtryon-511016-stylereel-temp GOOGLE_CLOUD_PROJECT=virtualtryon-511016 GOOGLE_CLOUD_QUOTA_PROJECT=virtualtryon-511016 PYTHONPATH=backend .venv/bin/python scripts/seed_catalog.py
python3 scripts/deploy.py
python3 scripts/smoke.py
```

Setup creates/reuses only namespaced APIs/resources: native default Firestore, catalog/temp buckets, runtime/dispatcher accounts, generation queue, Secret Manager entries and Artifact Registry. If Firebase project registration is unavailable, it falls back to supported Identity Platform initialization and a Firebase Authentication SDK key without inventing an app ID. Provider keys are restricted to runtime secret access/version creation. Authentication signup/deletion are disabled for end users; reCAPTCHA email/password mode is `ENFORCE`, blocking scores below 0.3.

Deployment uses Cloud Build with a dedicated account, private source staging bucket and repository permissions, then deploys the image and registers the actual service domain in Identity Platform. It creates/updates the authenticated five-minute maintenance scheduler. Local Docker need not be running. Public Firebase settings and resource names are saved in ignored `.deployment/config.json`; privileged credentials are not.

## Administrator setup

Open the deployed URL listed in `.deployment/config.json` or the implementation report. Retrieve the initial password through [Secret Manager](https://console.cloud.google.com/security/secret-manager/secret/stylereel-bootstrap-password/versions?project=virtualtryon-511016) using the authorized cloud account. Log in as `joinarun@gmail.com` and change it. The backend blocks other functionality until the change succeeds, revokes the old session, and requires login again. Do not share the cloud password/credentials or paste them into chat.

Add staff/user accounts and upload store photographs through administration. FASHN requires an API key and prepaid credits. Pruna additionally requires confirmation of appropriate privacy/no-training terms. No alternate-provider credits are bought automatically.

## Verification and recovery

Check anonymous protected routes return `401/403`, Firebase login without a CAPTCHA token is rejected, reCAPTCHA keys are provisioned, and public signup is disabled. Confirm a real authenticated Google job produces an image and records usage. Check queue status and safe application error categories in Cloud Logging; logs must not contain tokens, image bytes or provider bodies. Scheduler/worker failures leave metadata that maintenance can reconcile.

The CAPTCHA score threshold may need tuning for real devices after observing verdict/token metrics. Never disable enforcement to make a test pass. Cloud IAM or service/model availability failures must be reported as failures, not successful deployments.

For the current UX/saree revision, `scripts/revision_session.py` creates disposable accounts and `scripts/browser_signin.mjs` signs them in through normal email/password and enforced CAPTCHA. No runtime token-signing IAM grant is needed. The ignored session files contain temporary passwords/tokens and are owner-readable; never print or commit them. `scripts/revision_saree.py` makes one real Google Pro saree call through the normal API. `scripts/browser_revision_verify.mjs` makes one more call from the deployed UI, checks the generated-only view and recent-look selection, desktop webcam capture, home navigation, QR revocation and desktop/Android/iPhone/iPad layouts. Installed Chrome and the frontend Playwright dependency are required. The separate `scripts/camera_verify.mjs` uses a controlled synthetic camera feed and does not transmit a photograph or run AI.

Use `PYTHONPATH=backend` and the project/quota-project environment values for the Python checks. Afterward run `scripts/e2e_live.py --cleanup` with the project and both storage bucket environment values shown above. Cleanup removes only the accounts recorded in the ignored acceptance session and their images; it preserves all spending history and other users' data. The revision checks refuse to repeat a recorded paid submission automatically. For an intentional new benchmark, archive its evidence and replay marker first, after checking the prior job outcome. Legacy `e2e_live.py --full` and `browser_verify.mjs` reproduce the original comparison/checkbox-era acceptance only; they are retained as historical evidence, not the current UX harness.

The final revision browser check deletes its own disposable result to test gallery/Studio deletion. A replay requires an existing unexpired result; it never resubmits AI when a result is deleted or its outcome is unknown. `scripts/revision_verify_cleanup.py` checks the three UIDs pinned in `.deployment/cleanup-scope.json`; `scripts/revision_smoke.py` writes the current anonymous security/OpenAPI checks. Refresh `verification/infrastructure.json` with `scripts/verify_infrastructure.py` before smoke verification. Physical camera hardware and native Safari are separate from Chrome layout/device emulation and the controlled webcam feed.

## Stop or remove

To stop new generation task dispatch, pause the queue and scheduler. Calls already in flight can finish. The service remains accessible; use the removal command below to take down the POC. Cloud Run minimum zero avoids idle compute but stored artifacts/data/secrets can still accrue charges.

```bash
gcloud tasks queues pause stylereel-generations --location=asia-south1 --project=virtualtryon-511016
gcloud scheduler jobs pause stylereel-maintenance --location=asia-south1 --project=virtualtryon-511016
```

For explicit removal: `python3 scripts/teardown.py --confirm-delete-stylereel`. This deletes namespaced compute, queues, image/build buckets, secrets, repository and service accounts. It deliberately preserves the existing project, billing, Firestore and Firebase accounts; review and remove application records/accounts separately. Deleting local downloaded files remains the device owner's responsibility.

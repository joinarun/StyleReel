# StyleReel implementation report

## Deployment and access

The working POC is deployed at **[StyleReel](https://stylereel-ynpzfmjw7q-el.a.run.app)** in Google Cloud project `virtualtryon-511016`. FastAPI and the compiled React/TypeScript/Vite/Tailwind frontend share one Mumbai (`asia-south1`) Cloud Run service, minimum instances zero. Google image inference uses the separate global endpoint and can process outside India.

The administrator is `joinarun@gmail.com`. Public bootstrap stores a generated initial password in [Secret Manager](https://console.cloud.google.com/security/secret-manager/secret/stylereel-bootstrap-password/versions?project=virtualtryon-511016), and the backend enforces a change at first login. The bootstrap secret does not track subsequent password changes. Acceptance testing uses disposable accounts without resetting the real administrator. No public `admin123` account was deployed. Users are created by administrators; public signup/deletion are disabled.

The original POC deployment was revision `stylereel-00009-jrh`, built through Cloud Build `38b6287c-15ca-446e-89de-f172f5303a3a` from image version `20261008-201424`. Its seven disposable acceptance accounts and test photos were removed. Subsequent revision checks target only their newly created fixture accounts and preserve existing users, photos and all spending history. The original temporary operator token-signing permission was removed; current revision testing uses ordinary CAPTCHA-protected email/password sign-in.

## October 11 catalog, reference-role and all-age revision

Final application deployment: **`stylereel-00013-6xr`**, Cloud Build **`ae1c6a72-6d8e-490c-be9d-07ce2ec07ebd`**, image **`20261011-175526`**. The URL and Mumbai scale-to-zero configuration are unchanged.

The try-on options are now **Pick a real Dress to Try** and **Pick a virtual Dress to Try**, each with the requested smaller supporting text. The real-dress workflow accepts children, adolescents and adults. Its structured preflight rejects only an explicit inability to identify a person or garment; folds, cropping, imperfect lighting, incidental people, already-worn garments and inconclusive structured responses proceed to editing. Decodable small/unusual-aspect photos are accepted, with malformed files, unsafe decoded sizes and upload limits still enforced. The guidance is reduced to one short line.

Find your look retains existing type labels and adds independent Store Name and Brand Name rows. Admins can create type/store/brand labels inline and assign them while adding a dress, with one to six ordered photos. Model-worn photos are supported, and the viewer exposes every saved photo. Labels persist in Firestore and become available in the studio after refresh. Existing single-photo garments and older accepted jobs remain compatible. Catalog uploads automatically prepare large browser-decodable photos and enforce a 28 MiB combined upload limit below Cloud Run's inbound HTTP/1 limit; Google inputs separately use a 12 MiB raw operating budget without dropping references.

Mandatory provider instructions designate the first image as the end user's identity, apparent age, body, pose and background source, and all later images as garment appearance references. Models in those references must never replace the end user. Immutable jobs capture all photos grouped by garment. Google/Pruna receive each reference; FASHN receives a locally composed sheet per garment while retaining sequential upper/lower calls. Those alternative-provider changes are mock/contract tested, not live quality tested; their availability/privacy gates are unchanged.

Source checks passed **74 unique backend tests**, **78 frontend tests**, the TypeScript/Vite production build, and whitespace checks. Backend coverage includes all-age/inconclusive preflight, role labels, all-view grouping and snapshots, legacy jobs, asynchronous polling without resubmission, estimates, catalog access/CRUD/rollback, Unicode type labels, upload bounds, and scoped cleanup. Frontend coverage includes filter combinations, label/photo presentation and upload preparation. The deployed service passed **16 HTTPS/security checks** and **21 live API checks**. Local evidence and fictional photographs remain ignored by Git; reproducible verification scripts are included in the repository.

Two actual Google Pro 2K jobs succeeded with **three provider attempts** (one catalog edit, one preflight and one held-garment edit), **$0.53 reserved** and **$0.283186 reconciled estimated AI usage**. Both source photos were deleted on completion; duplicate idempotency requests returned their existing jobs. The catalog test deliberately used a fictional child's photo and two dress references, one on a mannequin and one on a different fictional adult model. Visual review found a recognizable child identity with cream color, long sleeves, asymmetric hem and waist-band details, without copying the adult model's identity. The held-garment test dressed the same fictional child in the visible blue shirt, transferring collar, buttons, pocket and cuffs. Both outputs lowered the original holding pose; wrinkles, button spacing, drape and inferred fit varied. These two samples establish functioning all-age/reference processing, not general identity or retail-fit guarantees. Nano, traditional-garment quality and alternative-provider quality were not rerun for this change.

The deployed UI passed **68 browser checks** on desktop and Chrome-emulated Android, iPhone and iPad layouts: inline label creation, two-photo creation, automatic filters, filter combinations, photo arrows/thumbnails, reload persistence, requested option text/fonts, minimal child guidance, home navigation and horizontal overflow. No paid generation was submitted by the browser harness; actual AI validation used the API jobs above. Physical-device and native Safari checks were not performed for this revision. The UI fixture uploads the same licensed photo under two names for control/persistence checks; the live API test uses distinct mannequin and model references.

Normal CAPTCHA-protected password sign-in succeeded for the three scoped accounts (one was a recent ordinary-login session reused). Subsequent fresh automated administrator sign-ins were intermittently rejected, including three headless and three headed attempts despite successful CAPTCHA configuration initialization. The final UI checks therefore restored that administrator's existing ordinary-login ID token into Firebase persistence after the backend verified its identity, role and readiness. These checks establish authenticated UI functionality and session reuse, not a fresh CAPTCHA login for each layout. No CAPTCHA enforcement or IAM configuration was weakened, and no custom tokens were minted. The rejected attempts remain documented in local evidence.

A second 61-check browser pass refreshed screenshots after thumbnails finished loading, reusing the already-created fixtures and making no AI calls. Scoped cleanup removed exactly two test dresses, two types, two store labels, two brand labels and three disposable accounts, including their controlled images and saved browser-token state. Seven cleanup checks passed, including Firebase identity removal. Other catalog/user data and all job, usage and spending history were retained. Local evidence: `catalog-upgrade-unit.json`, `catalog-upgrade-live.json`, `catalog-upgrade-quality.json`, `catalog-upgrade-browser-initial.json`, `catalog-upgrade-browser.json` and `catalog-upgrade-cleanup.json` under `verification/`.

## October 9 camera, result and saree revision

Final verified deployment: **`stylereel-00011-2qc`**, Cloud Build **`34c634be-6954-4d69-8007-de3e0e1fe558`**, image **`20261009-035038`**. The public URL is unchanged. All three new disposable accounts and their temporary images/upload/share records were removed; only those fixture UIDs were targeted. All usage history and other users' data were preserved. Monthly estimated AI spend was **$1.759884**, with **$0 pending reservations**, at the scoped cleanup observation. That total includes prior usage and is not the cost of this revision alone. [Final smoke](verification/revision-smoke-evidence.json), [scoped cleanup](verification/revision-cleanup-evidence.json), [resource inventory](verification/infrastructure.json).

The requested changes replace the half-original comparison with one generated photograph, place clickable/scrollable recent looks directly below it, make the StyleReel logo reset to home, and move the Generate authorization disclosure to the bottom without a checkbox. Mac/laptop capture opens a live webcam modal with permission/device guidance; Android/iPhone/iPad retain their native picker. Camera pause/resume, close/navigation and late permission responses stop or disable capture safely.

Home and gallery behavior also guard delayed recovery, result saving and QR responses. Deleted results cannot reappear from Studio memory, closed share dialogs stay closed, and logout/account changes cannot save an old account's photo into a new account's gallery. The backend exposes the submitted provider/model from its immutable job snapshot so later administrator settings changes do not relabel an earlier result.

Current source verification: **37 backend tests**, **63 frontend tests**, a successful TypeScript/Vite production build, and **13 controlled Chrome webcam checks**. Backend checks include the saree instruction snapshot reaching the worker after catalog edits and provider/model metadata surviving settings changes. Frontend checks include delayed callbacks, recovery barriers, deletion versus unsynced results, immutable metadata, encryption and stale account sessions. [Revision unit evidence](verification/revision-unit-evidence.json), [camera evidence](verification/browser/camera-report.json).

The final deployment passed **55 Chrome browser checks**, including normal CAPTCHA-protected login, local camera capture without upload, generated-only results, bottom disclosure, horizontal recent-look scrolling and image/metadata/download selection, logo navigation from Studio/Gallery/Admin/public shares, QR revocation, encrypted result recovery, Home during a deliberately delayed recovery response, closed QR dialogs receiving late responses, and Gallery deletion without Studio resurrection. Desktop, Android, iPhone and iPad layouts had no page overflow. Recent-strip overflow uses encrypted copies of actual synthetic Google results, not additional paid calls. The final browser run reuses the successful paid job from the first revision build. [Final browser report](verification/browser/revision/report.json), [current desktop result](verification/browser/revision/desktop-generated-saree.png), [iPhone recent looks](verification/browser/revision/iphone-recent-looks.png).

There were **zero application page/console errors** in the final browser run. Google CAPTCHA iframe `requestStorageAccess: Permission denied` messages are attributed to `https://www.google.com/recaptcha/enterprise/anchor` and retained as external observations; normal protected email/password login and the complete journey succeeded. The untouched [pre-final raw report](verification/browser/revision/pre-final-run-raw.json) is retained. The first harness checked revocation before its asynchronous DELETE completed; the corrected harness waits for the HTTP 200 and confirms public delivery returns 410. [First paid run](verification/browser/revision/first-paid-run.json). There was no repeated paid generation to repair a harness assertion.

Two **real Google Pro 2K** saree generations succeeded through normal Cloud Tasks/quota accounting: a grey T-shirt/black-trousers input and a synthetic cream-dress input. Both show a complete continuous floral saree, front pleats, shoulder pallu and matching blouse, with **no visible original-clothing remnants or half-original split**. The new instructions add no extra generation calls. The calls cost **$0.140964 + $0.140244 = $0.281208 in reconciled AI estimates**, not invoice charges, and count toward the unchanged $25 monthly ceiling. [API job evidence](verification/saree-revision-evidence.json), [browser job receipt](verification/saree-browser-receipt.json), [qualitative review](verification/saree-quality-review.json).

![Actual Google saree result from the synthetic dress input](verification/results/saree-revision-dress.jpg)

Pattern placement, border texture and blouse construction remain inferred. The casual-input result changes one arm to hold the pallu, and both outputs narrow the stance. Faces/hair are broadly similar, with no biometric fidelity metric. These two fixtures support full-outfit replacement for these cases; they do not guarantee all saree/customer results. Sarees remain labeled experimental. Physical Mac camera hardware and native Safari have not been tested; controlled Chrome tests include Safari-style track pause events.

## Implemented behavior

- Firebase/Identity Platform email/password login with **Enterprise reCAPTCHA ENFORCE**, revoked-token checks, backend account/role checks, and mandatory initial password change.
- User creation, activation/deactivation, deletion and reset-link initiation; account changes revoke sessions. Reset links are copied by an administrator rather than sending unrequested email.
- Laptop webcam preview/capture, native Android/iPhone/iPad camera controls, file uploads, cropping, previews and photograph guidance. Camera streams stop on capture/close/navigation, including late permission responses; paused tracks cannot produce black captures. Server decoding supports JPEG, PNG, WebP and HEIC, validates dimensions/size, corrects orientation, strips metadata and normalizes private provider inputs.
- Nine extensible categories and upper/lower/full-body compatibility; one upper plus one lower garment is allowed. Four CC0 seed assets have recorded source/license attribution. Other categories accept administrator uploads.
- A small bottom disclosure identifies provider/global processing; Generate authorizes transmission without a checkbox. Capture/selection/cropping stay local. Call/cost estimates, real Google image editing, asynchronous `202` jobs and polling. Saree jobs snapshot full-outfit replacement/draping instructions; experimental flags remain attached to traditional/holding results and encrypted gallery records.
- Transactional quotas and cost reservations, one active job per user, idempotency, durable task leases and prediction IDs, enqueue recovery, and conservative unknown-outcome handling without automatic paid resubmission.
- Generated-image-only Studio/Gallery views, with a scroll/swipe row of recent looks below the main image. Selecting a thumbnail updates the image, metadata and download/QR targets. Encrypted per-account IndexedDB gallery, download, capacity warning/default 20, single/bulk deletion and account locking on logout. Browser/device storage and downloaded files have separate lifetimes.
- The top-left StyleReel logo returns to a fresh studio from any page, including the completed result and public share page. Active submissions/jobs remain recoverable and save into the gallery after a home reset.
- Revocable 15-minute QR bearer links, hash-only server tokens, anonymous image delivery with expiry checks, and temporary re-upload of older local results.
- Source deletion on terminal completion, result access expiry within 24 hours, five-minute cleanup and storage lifecycle backstop. Admin analytics expose metadata rather than customer photographs.
- Supported provider/model/prompt settings, write-only Secret Manager credentials for alternate providers, quotas, gallery settings, nonbillable provider checks and usage/cost charts/history.

## Original POC verification evidence

| Verification | Evidence and scope |
|---|---|
| Backend | **34 pytest tests passed**, covering auth/roles/password gate, malformed uploads, catalog contracts, concurrent quotas, budget reservation, duplicate tasks/jobs, asynchronous prediction reuse, ambiguous requests, cancellation races and cleanup retries. Test repositories/providers are isolated doubles. |
| OpenAPI | `/api/docs` opens the generated Pydantic contract at `/api/openapi.json` under the strict script policy. |
| Frontend | **27 Vitest tests passed**, covering selection/cost metadata, API authorization/quota errors, AES-GCM encryption and account isolation, logout locking, password validation and reported-token/CSV mapping. Production TypeScript/Vite build passed. |
| Deployed API | **53 live benchmark checks** plus **12 additional API checks** passed. Real Firestore transactions, private Storage, Firebase verification and Cloud Tasks were used. HEIC conversion, consent rejection, catalog activation/attribution editing, password gating, reset revocation, deactivation and deletion were verified live. |
| CAPTCHA | The correct bootstrap password without a CAPTCHA token was rejected with `MISSING_RECAPTCHA_TOKEN`. Normal browser email/password login succeeded with enforcement active; initial and voluntary password changes, reauthentication, session revocation and login with the new password passed. |
| Task identity | Cloud Tasks generated the real images. Scheduler maintenance returned HTTP 200; anonymous calls returned 401. Worker/scheduler audience and exact dispatcher identity are verified in the application. |
| Security review | A final read-only review checked revocation/account state, roles/password gating, transactional spending reservations, task leases/idempotency, unknown outcomes, worker OIDC, private objects and expiry/cleanup. No new high-priority launch blocker was found. This is an implementation review, not an independent penetration test. |
| QR privacy | Anonymous/other-account result access was denied. A bearer link downloaded its image anonymously, revocation returned 410, and forced expiry was denied before maintenance. |
| Responsive browser | **50 live browser checks passed**: 40 main checks across desktop, Android, iPhone and iPad plus 10 gallery checks. The file → crop → consent → real Google job → image → encrypted save/reload journey passed, along with comparison/download/QR, capacity warning/cancel, pending-job recovery/oldest eviction and single/bulk deletion returning server 410. Physical devices, native Safari, camera hardware and real iPhone HEIC capture remain untested. |

Evidence files: [unit checks and security review](verification/unit-evidence.json), [Google benchmark](verification/live-evidence.json), [browser generation receipt](verification/browser-generation-evidence.json), [additional API checks](verification/api-evidence.json), [auth enforcement](verification/auth-enforcement.json), [main browser checks](verification/browser/report.json), [gallery checks](verification/browser/gallery-report.json), [real password flow](verification/browser/password-report.json), [provider readiness](verification/provider-readiness.json), [cleanup](verification/cleanup-evidence.json), and [resource inventory](verification/infrastructure.json), and [final deployment smoke](verification/final-smoke-evidence.json). Scripts reproduce cloud setup/deployment and acceptance checks. Privileged test credentials were kept outside source control and removed after testing.

The main browser journey ran before the final API documentation and persisted-label patches; the unchanged journey is backed by those live checks, final unit/build checks and final deployment smoke checks. The main browser run had no application CSP violations, page errors or protected-API failures. Google CAPTCHA PAT negotiation returned documented external 401 responses. Two Google report-only iframe/telemetry messages are retained separately, including the untouched [raw report](verification/browser/report-raw.json); they did not block login or the application journey. [Google PAT documentation](https://docs.cloud.google.com/recaptcha/docs/private-access-tokens).

## Actual Google benchmark

The benchmark used one fictional adult full-body photograph and a held-blouse variation, plus licensed catalog images. Fixture generation used the built-in imagegen tool; its prompts are recorded in [PROMPTS.md](verification/fixtures/PROMPTS.md). These are synthetic inputs, not stand-ins for provider outputs. Both Google image models received the same corresponding inputs/settings and produced real provider images.

| Case | Pro status / observed job time | Nano 2.1 status / observed job time |
|---|---|---|
| Ordinary T-shirt | Succeeded, 30.8 s | Succeeded, 24.4 s |
| T-shirt + skirt, one Google call | Succeeded, 40.9 s | Succeeded, 20.4 s |
| Saree | Succeeded, 34.1 s | Succeeded, 20.5 s |
| Clear held blouse, two durable calls | Succeeded, 34.0 s | Succeeded, 27.2 s |
| No held garment, visibility check only | Rejected with recapture guidance, 6.9 s | Rejected with recapture guidance, 3.6 s |
| Additional dress | Succeeded, 38.2 s | Not run for this additional case |

This benchmark generated **nine images**, correctly rejected **two unsuitable inputs**, made **13 provider attempts** including visibility checks, and reconciled **$0.919047 estimated AI spend** from reported tokens. The final browser-driven Pro dress generation added one image/call and **$0.139428**, bringing the session to **10 generated images, two rejected inputs, 14 provider attempts and $1.058475 estimated AI spend**. Pending reservations are zero. These are estimates, not billing invoices. Pro 2K remains the default, the $25 monthly ceiling remains enabled, and gallery capacity is restored to 20.

The following images document the original benchmark and its former comparison UI. The current app shows the generated image alone.

![Original browser-driven Google benchmark result](verification/browser/desktop-browser-generated-result.png)

![Synthetic input and actual provider outputs](verification/comparison-sheet.jpg)

Visual inspection found realistic garment placement and recognizable colors/patterns in both models, with limits:

- **Identity:** facial detail and expressions drifted. Pro's ordinary T-shirt output changed the closed-mouth expression to a teeth-visible smile; Nano's held-blouse output also changed the expression. Hair/body proportions can shift.
- **Garment detail:** broad colors and patterns transferred, but tiny logos, motifs, folds and construction were regenerated. The skirt's central opening/pleats differed between models. Unseen garment regions are inferred.
- **Alignment/framing:** Pro's single-shirt image cropped the legs despite a full-body input. Output aspect ratios varied. Other examples retained feet more consistently; both saree outputs changed the hand pose.
- **Traditional clothing:** both produced plausible sarees, but drape, pleat placement, blouse details and pattern scale differed. Salwar suits and other traditional references still need retail-specific evaluation.
- **Holding:** both removed the held reference and dressed the person in a burgundy blouse. Visibility checks rejected the no-held-garment photograph. More folding/occlusion/ambiguity cases remain to be tested.

Nano was faster and cheaper in this sample and often preserved full-body framing better. One person and one reference per case do not establish a general quality ranking. Pro remains the requested default; traditional/holding previews remain experimental. These images do not predict physical sizing or guarantee retail fabric/fit.

## Mock-tested, unavailable and unverified boundaries

FASHN and Pruna have real REST adapters and documented asynchronous prediction handling, with mocked request/error/usage/polling tests. **Neither was live-generated** because no API key/credits were configured. FASHN submits separate top/bottom references sequentially. Pruna supports native multiple references and remains blocked until applicable no-training/retention terms are confirmed. Neither adapter supports holding photos.

Cloud failure/ambiguous-timeout races, simultaneous quota attempts and enqueue-recovery failures were exercised using controlled doubles, rather than deliberately disrupting production cloud services. Local Auth/Firestore emulator configuration and startup are provided; emulator processes were not run in this session (installed Java is 17; documented startup requires Java 21+). Real cloud integration was exercised instead. No physical-device checks, independent identity metric or statistically representative garment benchmark is claimed.

## Resources and operating costs

| Resource | Deployed configuration |
|---|---|
| Cloud Run `stylereel` | Mumbai, 1 vCPU/1 GiB, concurrency 4, timeout 600 s, minimum 0, service maximum 3 |
| Firestore `(default)` | Native mode, Mumbai; client rules deny direct access |
| Catalog bucket | `virtualtryon-511016-stylereel-catalog`, private/uniform access |
| Temporary bucket | `virtualtryon-511016-stylereel-temp`, private; versioning/soft delete disabled; two-day cleanup backstop |
| Cloud Tasks | `stylereel-generations`, Mumbai; two concurrent dispatches, application OIDC checks |
| Scheduler | `stylereel-maintenance`, every five minutes, dispatcher OIDC |
| Artifact Registry / build staging | Mumbai `stylereel` repository and private `virtualtryon-511016-stylereel-build-source` bucket |
| Service accounts | Scoped runtime, dispatcher and build identities; no downloaded key files |
| Secret Manager | Generated bootstrap password and write-only alternate-provider key containers |
| Identity Platform | Email/password, invitation-only accounts, Enterprise CAPTCHA blocking rule |

See [COST_ESTIMATION.md](COST_ESTIMATION.md) for AI and hosting/storage/database/CAPTCHA/logging projections at 100/1,000/10,000 generations. Pro's baseline single-garment 2K image plus two inputs is approximately $0.137 before prompt/thinking usage; this benchmark's catalog Pro calls were approximately $0.140 each. Estimated infrastructure budgets are separate from the $25 AI ceiling. Larger scenarios are projections and require explicit quota/budget changes.

## Phase 2 recommendations

Before retail rollout, evaluate a consented, varied cohort with modern store references and multiple poses/lighting conditions; obtain independent identity/detail/drape ratings. Test physical Android/iPhone/iPad cameras and Safari. Confirm alternate-provider contracts before enabling them. Replace historical analytics scans with aggregates as usage grows, add automated billing reconciliation/alerts and resource-age cleanup, and decide whether to add server gallery sync. Checkout, physical sizing and SaaS tenancy remain outside this POC.

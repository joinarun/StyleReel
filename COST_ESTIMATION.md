# Operating cost estimates

Price references checked October 9, 2026; all amounts below are USD before tax. These are estimates, not invoices. Free quotas are shared across the billing account/project as applicable, and other projects may already consume them.

## AI

Google Pro: $2/million input tokens, $12/million text/thinking output tokens, $120/million image output tokens. A 1K/2K image uses approximately 1120 image output tokens ($0.1344). Two image inputs add approximately $0.00224 before prompt and thinking tokens. Nano Banana 2.1 has $1.50/$7.50/$30 per million input/text-output/image-output tokens; a 2K output costs $0.0504 plus inputs/thinking. [Official prices](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing).

| Single-garment generations | Pro 2K image + two inputs | Nano 2K image + two inputs |
|---|---:|---:|
| 100 | $13.66 | $5.38 |
| 1,000 | $136.64 | $53.76 |
| 10,000 | $1,366.40 | $537.60 |

These projections exclude text/thinking, held-photo preflight, retries and infrastructure; the 1,000/10,000 scenarios are projections rather than permission to exceed the configured $25 ceiling. Google catalog outfits use one call with another input; FASHN outfits use two calls. FASHN balanced 2K uses three credits per output, approximately $0.225 at $0.075/credit. Pruna's developer unit model is priced separately from its website promotion; administrator-configurable unit price remains explicitly estimated until an account's actual rate is verified. No provider credits are automatically purchased.

The application initially reserves a conservative estimate before dispatch (Pro 2K: $0.25). Reported token/credit usage reconciles estimated cost where available. Unknown outcomes retain the conservative reservation. The monthly budget includes pending reservations and completed costs; it is not a hard cap on the provider's final invoice or cloud spending.

## Infrastructure

Assume one 1-vCPU/1-GiB worker request for an average 60 seconds, 2 MiB per output, modest catalog storage, evenly distributed monthly traffic, and no other use of the relevant free quotas. The synthetic benchmark completed successful jobs in roughly 20–41 seconds; 60 seconds leaves room for cold starts and more difficult inputs.

| Component | Billing basis and practical implication |
|---|---|
| Cloud Run | Request-based CPU, memory, requests and egress. At the assumed 60 seconds, 10,000 runs use 600,000 vCPU/GiB-seconds. Beyond the shared 180,000 CPU/360,000 memory free allowances, estimated worker compute is $10.08 CPU + $0.60 memory. API requests, maintenance, cold starts and egress add usage. |
| Firestore | Reads/writes/storage and network. Default database includes 50,000 reads/day, 20,000 writes/day and 1 GiB stored; small evenly spread demonstrations can fit these quotas. Current analytics scan metadata, so dashboard frequency affects reads. |
| Storage/egress | Private catalog, temporary results and build artifacts are charged by retained bytes and operations. 100/1,000/10,000 results at 2 MiB imply roughly 0.20/1.95/19.53 GiB delivered, plus source/catalog/share traffic. India storage/egress do not inherit every US-region storage free allowance. |
| Cloud Tasks | Request operations; small POC traffic is within its one-million-operation monthly free tier if unused elsewhere. Polling increases operations. |
| Scheduler | One job costs $0.10/month after the first three billing-account jobs. |
| Identity Platform/reCAPTCHA | Email/password MAU and CAPTCHA assessments. CAPTCHA's first 10,000 assessments/month are free; 10,001–100,000 cost an $8 flat fee. Generation count is not login-assessment count. |
| Secret Manager, Logging | Secret versions/accesses and log ingestion/retention. Retain only needed secret versions, metadata and safe error categories. |
| Build/Artifact Registry | Build minutes, source archives and image storage. Old deployment images/source bundles should be removed; scale-to-zero does not erase them. |

Illustrative monthly component allowances below assume no more than 10,000 CAPTCHA assessments, fewer than 50,000 email/password MAU, logs below 50 GiB, six or fewer active secret versions, and 30 dashboard refreshes. Storage/egress are allowances rather than exact quotes because destinations and download/share counts vary. Maintenance queries only active jobs and pending cleanup records; analytics still scan selected history.

| Component (USD/month, excluding AI) | 100 generations | 1,000 | 10,000 |
|---|---:|---:|---:|
| Worker Cloud Run compute | $0 | $0 | ~$10.68 |
| Firestore operations/storage | $0–$0.20 | $0–$0.50 | $1–$5 |
| Photo storage, operations and delivery egress | $0.10–$0.50 | $0.30–$1.50 | $3–$8 |
| Identity Platform + CAPTCHA under stated free limits | $0 | $0 | $0 |
| Tasks + one Scheduler job | $0–$0.10 | $0–$0.10 | $0–$0.10 |
| Secret Manager + safe metadata logging | $0–$0.10 | $0–$0.10 | $0–$0.50 |
| Build minutes, image registry and source archives | $0.10–$2 | $0.10–$2 | $0.10–$2 |

Budget approximately **$1–$5**, **$1–$8**, and **$15–$30** respectively, excluding AI and tax. These ranges are not guaranteed free-tier bills and increase with repeated downloads, high login traffic, longer inference or exhausted shared free quotas. The larger scenarios also require explicitly increasing application quotas/budget; no such increase was made.

Sources: [Cloud Run](https://cloud.google.com/run/pricing), [Firestore](https://cloud.google.com/firestore/pricing), [Storage](https://cloud.google.com/storage/pricing), [Tasks](https://cloud.google.com/tasks/pricing), [Scheduler](https://cloud.google.com/scheduler/pricing), [Identity Platform](https://cloud.google.com/identity-platform/pricing), [reCAPTCHA](https://cloud.google.com/recaptcha/pricing), [Secret Manager](https://cloud.google.com/secret-manager/pricing), [Logging](https://cloud.google.com/stackdriver/pricing).

At zero users, minimum-zero Cloud Run has no reserved idle instance cost. Retained objects, registry images, secret versions, scheduled operations and logs may still incur charges. Cloud budgets are alerts, not request-blocking limits; app quotas are the enforceable AI control.

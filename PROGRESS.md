# PharmaGuard — Engineering Progress & Phase 2 Implementation

Tracks the architecture, pipeline hardening, bug fixes, pharmacovigilance depth, and intelligence analytics implemented per the **PharmaGuard Repo Review & Phase 2 Plan**.

---

## Phase 2 Implementation Summary

| Workstream | Scope & Objectives | Status | Key Modules & Implementation Details |
|---|---|---|---|
| **2A: Fix & Harden** | Fix all 11 repo issues, async job queue, state machine, tests & CI | **DONE** | • `/auth/register` privilege escalation closed (`authController.js`)<br>• Persisted AI narrative summary on `Report` and surfaced in UI (`ReportDetail.jsx`)<br>• Fixed RAG seeding fast-path avoiding repeat external calls (`corpus_seed.py`, `retrieve.py`)<br>• Fixed `needs_more_info` count tile on `Dashboard.jsx`<br>• Sorted triage queue by clinical severity (`reportController.js`)<br>• Implemented event-driven async `pipelineQueue.js` with progress polling<br>• Guarded report state machine (`reviewReport`)<br>• Added PDF/DOCX file intake (`fileParser.js`, `Intake.jsx`)<br>• Security: Rate limiting (`express-rate-limit`), doctor row-level ACL, CORS tightening<br>• Cryptographic SHA-256 hash-chaining on `AuditLog` with `verifyChain()`<br>• Jest tests (4 suites, 9 tests) + Pytest suite (5 tests) + GitHub Actions CI (`ci.yml`) |
| **2B: Real PV Depth** | Regulatory criteria, causality assist, duplicates, E2B(R3) export | **DONE** | • ICH E2A Seriousness criteria (death, hospitalization, disability, congenital anomaly, life-threatening, medically important) in ML classification & UI<br>• Naranjo Algorithm (10 criteria) & WHO-UMC causality assist (`causality.py`) with pharmacist confirmation<br>• Regulatory clocks: automated 7-day (fatal/life-threatening) and 15-day expedited clocks (`regulatoryClock.js`)<br>• Duplicate-case detection heuristic (`duplicateDetector.js`)<br>• Standard ICH E2B(R3) XML ICSR generation and download (`e2bExport.js`)<br>• Terminology coding: RxNorm RxCUI & MedDRA Preferred Terms |
| **2C: Intelligence & Analytics** | Statistical signal detection (PRR/ROR), hybrid retrieval, citation verification | **DONE** | • Disproportionality Signal Detection engine (`signalDetection.js`) with PRR, ROR, 95% CIs, and Yates χ² test<br>• Interactive dashboard charts: signals, top suspect drugs, top adverse events, age/sex demographics<br>• Hybrid retrieval combining dense embeddings + BM25 lexical matching + targeted live PubMed/FDA queries<br>• Citation ground audit verifying claims against retrieved literature (`citation_checker.py`) |
| **2D: Evaluation & Feedback Loop** | Clinical benchmark harness, AI-vs-human diffing | **DONE** | • Benchmark evaluation harness (`eval_harness.py`) testing extraction F1, seriousness accuracy, and retrieval recall on reference cases<br>• Reviewer correction form with AI-vs-human edit diffing and audit tracking |
| **2E: Production Readiness** | Redis service, container healthchecks, security defaults | **DONE** | • Redis added to `docker-compose.yml` with healthchecks<br>• Dynamic JWT secret configuration with dev fallbacks |

---

## The 11 Core Problems: Resolution Log

1. **`/auth/register` open privilege escalation:** Initial system bootstrap allows creating the first admin; once users exist, public registration strictly defaults to `doctor` and blocks elevated role creation. Elevated roles must be provisioned by admins via `/api/users`.
2. **AI summary was never saved or shown:** Added `aiSummary` field to `Report` schema, saved during pipeline execution, returned via `GET /api/reports/:id`, and rendered in a prominent card in `ReportDetail.jsx`.
3. **`ensure_seeded()` made live fetches before checking if seeded:** Added collection existence and point count fast-path check in `corpus_seed.py` and a cached `_SEEDED` flag in `retrieve.py`.
4. **Live evidence was fixed filler:** Replaced with targeted `fetch_pubmed_for_query` and `fetch_fda_for_query` searching for the specific drug and adverse reactions, extracting real paper titles, journals, and label warnings.
5. **Dashboard counted `request_more_info` instead of `needs_more_info`:** Synchronized `STATUS_ORDER`, status styles, and badges across `Dashboard.jsx` and `Badge.jsx`.
6. **Review queue wasn't sorted by severity:** Implemented severity priority sorting (`life_threatening` > `serious` > `moderate` > `mild`) in `reportController.js`.
7. **Pipeline ran in single 60s HTTP request risking 502s:** Moved pipeline execution to an async event-driven queue (`pipelineQueue.js`). `POST /reports/:id/run-pipeline` returns 202 Accepted immediately; frontend polls `GET /reports/:id/status` with real-time stage progress.
8. **Edit review action lacked UI, diffing, and state guards:** Built reviewer correction form in `ReportDetail.jsx`, applied updates to `Extraction`/`Classification` with diff tracking, and enforced state machine transitions in `reviewReport`.
9. **File upload was unfinished:** Added `pdf-parse`, `mammoth`, and text parsing in `fileParser.js`. Upgraded `Intake.jsx` with Document Upload (PDF/DOCX), Paste Note, and Structured Clinical Form tabs.
10. **Security basics missing:** Implemented global & auth rate limiting (`express-rate-limit`), row-level access control restricting doctors to their own reports, restricted ML service CORS via `ALLOWED_ORIGINS`, and cryptographic SHA-256 hash chaining on `AuditLog` with `verifyChain()` API.
11. **No tests, no CI, leftover console.log:** Added Jest unit test suite (4 suites, 9 tests), Pytest suite (5 tests), GitHub Actions workflow (`.github/workflows/ci.yml`), and removed leftover `console.log` in `IntroGuard`.

---

## Test Verification

- **Client Production Build (`npm run build`):** PASSED (0 errors, 414 kB bundle)
- **Server Unit Tests (`npm test`):** 4 test suites, 9 tests PASSED
- **ML Service Unit Tests (`pytest ml-service/tests`):** 5 tests PASSED
- **Evaluation Benchmark (`eval_harness.py`):** Verified offline resilience and metrics calculation


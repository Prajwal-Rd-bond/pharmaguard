# Intentional Deltas: PharmaGuard Phase 2 vs Origin-Main Baseline (`f2a797f`)

This document records every intentional design and implementation divergence between the Phase 2 integration branch (`integration/pharmaguard`) and the `origin/main` baseline (`f2a797f8f376d6ef7ad320f1c778b18b570eb600`).
Wait-free backup of the pre-final version of this document is preserved at `D:\pharmaguard-artifacts\intentional_deltas_pre_final_20261030.md`.

---

### 1. Naranjo Q5 Scoring: Conservative Evidence-Based Baseline
- **Origin-Main Behavior**:
  Awarded +2 points (`breakdown["q5_alternative_causes_absent"] = 2`) by default whenever `comorbidities` were empty and `concomitantDrugs` had $\le 1$ entry, even if the clinical narrative made no mention of alternative etiologies or alternative-cause workups.
- **Phase 2 Design**:
  Scores `0` for Q5 unless the narrative or clinical extraction explicitly reports alternative causes (`-1`, e.g., explicit comorbidities, concomitant drugs $> 1$, viral infection, underlying disease) or explicitly confirms that alternative causes were investigated and ruled out (`+2`, e.g., `"no alternative cause"`, `"alternative causes ruled out"`, `"no other cause"`).
- **Impact on Baseline Sample**:
  For `"Patient: Jane Doe, MRN: 12345. Took amoxicillin and got rash."`, the baseline Naranjo score is **1** (`"Possible"`) rather than **3** (`"Possible"`) because Q5 is awarded `0` instead of `2`.

### 2. Additive `unevidenced_items` in Causality
- **Origin-Main Behavior**:
  Did not indicate which Naranjo points were inferred from static lookup tables rather than narrative evidence.
- **Phase 2 Design**:
  Includes `unevidenced_items: List[str]` in the causality result payload. When Q1 is awarded `+1` solely from the static `well_known_pairs` lookup, `"q1_previous_conclusive_reports"` is listed in `unevidenced_items` so callers can distinguish table-lookup points from narrative-evidenced points.

### 3. De-identification Label Preservation and Span Sanitization (`[REDACTED]`)
- **Origin-Main Behavior**:
  - Over-consumed clinical cue prefixes (e.g., `Patient: Jane Doe` became `[REDACTED_NAME]`, stripping `Patient: `).
  - Returned the raw patient identifier in `deidentification_log[].span` (e.g., `{"type": "hospital_id", "span": "12345"}`).
- **Phase 2 Design**:
  - Regexes use capturing groups and token boundaries (`NAME_TITLE_RE`, `MRN_RE`) so clinical cue prefixes (`Patient: `, `MRN: `) are preserved while only the identifier value is replaced:
    `"Patient: [REDACTED_NAME], MRN: [REDACTED_HOSPITAL_ID]. Took amoxicillin and got rash."`
  - Every `deidentification_log` entry sets `span: "[REDACTED]"` so raw identifiers are never reflected in responses, logs, or persistence.
  - Log entry `type` values (`hospital_id`, `location`, `name`, `phone`, `email`, `ssn`, `date`) map 1:1 to scrubbed spans.

### 4. Separation of `evidence_status` and `assessment_status`
- **Origin-Main Behavior**:
  Did not report retrieval or assessment execution state in `PipelineResponse`.
- **Phase 2 Design**:
  `PipelineResponse` exposes two orthogonal status fields:
  - `evidence_status`: Reports the retrieval outcome independently of LLM configuration:
    - `"live_disabled"`: Live OpenFDA retrieval is disabled (`ENABLE_LIVE_OPENFDA=false`, the default).
    - `"ok"`: Retrieval succeeded and returned at least one clean evidence record.
    - `"none_found"`: Live retrieval was enabled and succeeded at the transport layer, but zero matching records were found.
    - `"provider_error"`: Upstream OpenFDA returned an HTTP error (e.g. HTTP 500) or non-timeout transport failure.
    - `"live_timeout"`: Upstream OpenFDA request timed out.
    - `"malformed_response"`: Upstream OpenFDA returned non-JSON or structurally invalid payload (missing `"results"`).
    - `"invalid_term" | "invalid_characters" | "term_too_long" | "pii_rejected"`: Outbound query term failed `validate_openfda_query_term()` before any network call.
    - `"partial_pii_rejected"`: One or more trusted evidence records failed the direct-identifier check and were dropped, while at least one clean record remained.
  - `assessment_status`: Reports the LLM causality assessment state independently of retrieval:
    - `"disabled"`: `LLM_PROVIDER=disabled`.
    - `"unconfigured"`: `LLM_PROVIDER` is set to an active provider (e.g. `openrouter`), but required credentials (`LLM_API_KEY`) or settings are missing.
    - `"completed"`: Advisory assessment completed (either model-derived or deterministic fallback).
    - `"failed"`: An unexpected non-privacy exception occurred during assessment; `assessment` is `null` and `assessment_error` records only the exception class name.
  - Unknown `live_status` values in `retrieve()` are preserved verbatim and never fall through to `"none_found"`.

### 5. Reference Corpus and OpenFDA Retrieval Configuration (`ENABLE_LIVE_OPENFDA=false`, `ALLOW_BUILTIN_REFERENCE_CORPUS`)
- **Origin-Main Behavior**:
  - `retrieve()` seeded and queried the 11-document in-memory demo array `KNOWLEDGE_CORPUS` unconditionally and made an unguarded live HTTPS call to `https://api.fda.gov` on every `/pipeline/run` request.
  - Cached empty `[]` results permanently in `_LIVE_EVIDENCE_CACHE` even when upstream OpenFDA calls failed with transient HTTP errors, timeouts, or malformed JSON.
- **Phase 2 Design**:
  - `ENABLE_LIVE_OPENFDA` is the canonical setting controlling live OpenFDA requests and defaults to `false`. `OPENFDA_API_ENABLED` is supported only as a backward-compatible fallback alias when `ENABLE_LIVE_OPENFDA` is unset.
  - `ALLOW_BUILTIN_REFERENCE_CORPUS` defaults to `false` unless `NODE_ENV` is explicitly `"development"` or `"test"`, in which case `load_settings()` defaults it to `true` unless overridden by `ALLOW_BUILTIN_REFERENCE_CORPUS=false`.
  - Every returned retrieval item includes `corpus_origin` (`"builtin_demo_corpus"` for static demo corpus records or `"external_or_vector"` for live OpenFDA / Qdrant vector records), which is surfaced in `/pipeline/run` and displayed in `ReportDetail.jsx`.
  - Transient OpenFDA failures (`provider_error`, `live_timeout`, `malformed_response`) are NOT cached in `_LIVE_EVIDENCE_CACHE`; only `"ok"` and `"none_found"` responses are cached, permitting retries after transient upstream failures.

### 6. Trusted Evidence Provenance (`TrustedEvidenceRecord`) and Contaminated-Record Policy
- **Problem**:
  Standard FDA SPL section headings and label metadata such as `"Patient Counseling Information (17)"`, `"Patient Information"`, `"Medication Guide"`, `"Revised: 11/15/2023"`, and manufacturer addresses (`"100 Example Parkway"`) either were corrupted into `[REDACTED_NAME]` by spaCy NER or triggered false-positive `DeidentificationError` / `pii_rejected` failures in `NAME_TITLE_RE`, `DATE_RE`, and `ADDRESS_RE`.
- **Phase 2 Design**:
  - **Provenance Type**: `TrustedEvidenceRecord(dict)` is assigned only by the internal retrieval stage (`retrieve()` / `sanitize_and_mark_trusted_evidence()`). Deserialized JSON from HTTP client requests or LLM outputs produces plain `dict` instances (`isinstance(x, TrustedEvidenceRecord) is False`) and cannot forge trusted status even if string keys such as `"type": "TrustedEvidenceRecord"` or `"_trusted_retrieval_token"` are supplied.
  - **Trusted Records**: Bypass statistical NER redaction and bypass generic `NAME_TITLE_RE`, `DATE_RE`, and `ADDRESS_RE` so legitimate FDA label section headings (`"Patient Counseling Information (17)"`), label revision dates (`"Revised: 11/15/2023"`), and manufacturer addresses (`"100 Example Parkway"`) pass through unchanged. Trusted records are still checked against all direct patient-identifier patterns (`EMAIL_RE`, `SSN_RE`, `MRN_RE`, `PHONE_RE`, plus patient-contextualized dates `_PATIENT_DATE_CONTEXT_RE` such as `DOB:` and patient-contextualized addresses `_PATIENT_ADDRESS_CONTEXT_RE` such as `residing at`) via `_has_trusted_evidence_identifier_phi()`.
  - **Contaminated-Record Policy**: When a trusted record fails `_has_trusted_evidence_identifier_phi()`, only that contaminated record is dropped; `{"source_id": <id>, "reason": "pii_rejected"}` is appended to `rejected_records` (and `evidence_metadata.rejected_records`); `evidence_status` is set to `"partial_pii_rejected"` if clean records remain or `"pii_rejected"` if none remain; and the pipeline continues without logging or returning the rejected text.
  - **Untrusted Records & Patient Text**: Any non-`TrustedEvidenceRecord` retrieval dict, patient narrative, or extraction field undergoes full regex + spaCy NER de-identification (`_deidentify_or_block`) and full residual-PHI checking including `NAME_TITLE_RE`, `DATE_RE`, and `ADDRESS_RE` (`_assert_no_residual_regex_phi`), failing closed with HTTP 500 (`DeidentificationError`) if any identifier remains.

### 7. Classification Contract (`regulatory_clock_days` and `expedited_clock_label`) and `frozen_origin_main_full.json` Reconciliation
- **Behavior**:
  - `classify(extraction)` in `ml-service/app/pipeline/classify.py` calls both `evaluate_ich_e2a_criteria(symptoms)` and `evaluate_expedited_regulatory_clock(is_serious=is_serious, criteria=ich_criteria)`.
  - `regulatory_clock_days` retains the legacy periodic/SLA integer value (`7` for fatal/life-threatening, `15` for other serious, `90` for non-serious periodic reporting), matching `frozen_origin_main_full.json` (`"regulatory_clock_days": 90`).
  - `expedited_clock_label` is added to `ClassificationResult` and `/pipeline/run` (`"potential_7_day"`, `"potential_15_day"`, or `"none"` at intake when expectedness and causality confirmation are pending; `"expedited_7_day"` or `"expedited_15_day"` when `unexpected=True` and `reasonably_related=True` are confirmed), propagated through Express (`pipelineQueue.js`, `Classification.js`, `Report.js`), and displayed in `ReportDetail.jsx`.

### 8. Extractor (`extract.py`) Multi-Drug Attribution and Scope
- **Deterministic Fallback (`extract_fallback`)**:
  - Dictionary-based drug matching covers `len(KNOWN_DRUGS) == 49` lowercase terms (`31` generic drug entries in `DRUG_CLASSES` plus `18` brand-name keys in `BRAND_TO_GENERIC`).
  - Multi-drug narratives: all matched drugs are ordered by first character offset in the narrative; explicit suspect labels or acute initiation cues (`started`, `prescribed`, `after`, `following` after chronic/background medications) promote the suspected drug as primary (`drugName`/`genericName`), while remaining distinct canonical drugs populate `concomitantDrugs`.
  - `_get_suspect_drug_windows()` and `_extract_suspect_regimen_fields()` bound `dosage`, `frequency`, `route`, and `duration` extraction to the suspected drug's local mention windows (bounded by adjacent concomitant drug mentions and clause boundaries) so concomitant medication regimens are never misattributed to the suspected drug and missing suspect values are left `None`.
  - `comorbidities` is `[]` on the `extract_fallback` path.
- **LLM Path (`extract` with Gemini client)**:
  - `_ground_llm_temporal_and_dosing_fields()` verifies that LLM-returned `dosage` and `frequency` appear verbatim within the suspected drug's local mention windows (`_get_suspect_drug_windows`), and `onsetTimeline` is grounded via `_extract_onset`, clearing ungrounded values to `None`.

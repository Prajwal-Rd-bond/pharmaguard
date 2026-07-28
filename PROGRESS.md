# Pipeline Hardening — Status, Findings, Next Steps

Tracks the effort to move every `ml-service` pipeline stage off hardcoded/mock baselines and onto
real models, each with the hardcoded version kept only as a resilience fallback. See
`PharmaGuard_Planning.md` (parent folder) for the full epic/module numbering referenced below.

## Status by stage

| Stage | Module | Real implementation | Fallback (on failure) |
|---|---|---|---|
| De-identification | M3 | Regex pass + `obi/deid_roberta_i2b2` clinical NER model (`deidentify.py`) | Fails open — logs the model error, keeps whatever the regex pass caught |
| LLM Extraction | M4 | Local Ollama (`llama3.2:3b`) via a JSON-constrained prompt (`extract.py`) | Regex/keyword-list baseline extractor, result tagged `incomplete: true` |
| ML Risk Classification | M5 | Same Ollama model, prompted with the full structured extraction (drug, dosage, timeline, comorbidities — not just symptoms) to reason about severity + return a one-sentence `rationale` (`classify.py`) | Rule-based keyword-set scoring (unchanged logic), tagged `model_name: "rule_based_baseline"`, `prompt_version: "n/a"` |
| RAG Retrieval | M6/M7 | Sentence-Transformers (`all-MiniLM-L6-v2`) embeddings + Qdrant semantic search across 3 seeded collections (`drug_labels`, `historical_cases`, `clinical_guidelines`); seeding is idempotent and runs on ml-service startup (`corpus_seed.py`, wired into `main.py`) | Keyword-overlap baseline over the same seed docs, each result tagged `retrieval_mode: "fallback_baseline"` |
| Explainable Summary | M8 | **Intentionally** template-based, not LLM — `summarize.py`'s docstring: "no free-form LLM generation, so there is nothing to hallucinate." Not a gap; a deliberate choice. Its own docstring floats an *optional* Phase 1 hardening path (LLM constrained to cite only retrieved evidence) if we ever want it. | n/a |

Classification's decision to use LLM reasoning rather than a trained classifier (XGBoost/Random
Forest/ClinicalBERT, as `classify.py`'s old docstring suggested) was a deliberate call: there is no
labeled ADR dataset anywhere in this repo to train one on, and fabricating one for a demo would
produce a classifier that looks real but isn't.

Every real-path result now carries which model/prompt produced it (`modelVersion`/`promptVersion`
on extraction, `model_name`/`prompt_version` on classification, `retrieval_mode` on each retrieved
item) so this is auditable end-to-end, per the planning doc's NFR: "every AI-facing endpoint must
persist model version + prompt version used."

## Findings from testing

- **Classification can under-triage when a named diagnosis doesn't survive extraction.** Tested a
  clear anaphylaxis case ("severe difficulty breathing and swelling of the throat... emergency
  epinephrine administered"). Extraction's prompt treats `symptoms` as reaction symptoms only, so it
  correctly excluded the word "anaphylaxis" itself (a diagnosis, not a symptom) — but that means
  `classify()`, which only ever sees the structured extraction dict and never the raw text, lost that
  signal. Result: the model classified it "serious" instead of "life_threatening." Not a bug in this
  round's code — a real limitation of the schema-only hand-off between extract → classify. See
  **Next steps** below.
- **Local Ollama in Docker on Mac is CPU-only** (no GPU passthrough), so under sequential load
  within a single pipeline run (extraction's LLM call immediately followed by classification's),
  the second call can occasionally be slow enough to hit the fallback path even though Ollama is up
  — the resilience pattern doing its job, not a defect, but worth knowing when timing a demo or
  tuning `OLLAMA_TIMEOUT_SECONDS`.
- Both fallback and real-model paths were verified directly for retrieval and classification
  (Qdrant up vs. down; Ollama up vs. down) — all four combinations return 200 with the correct
  `*_mode`/`model_name` tagging, never a hard failure.

## Next steps (not yet done)

1. **Fix the anaphylaxis under-triage gap** — likely fix: either keep named diagnoses in
   extraction's `symptoms` output (loosen the prompt's "symptoms only" instruction), or pass the
   de-identified raw text into the classification prompt alongside the structured extraction, so
   diagnosis terms aren't lost between stages.
2. **RAG corpus is still the Phase 1 "reduced corpus"** (3 collections, 4 seed docs total, ported
   from the old mock data) — Phase 2 per the planning doc calls for the full PubMed/WHO/FDA feeds.
3. **`docker-compose.yml` healthchecks** — `server` and `ml-service` use plain `depends_on` (waits
   for container start, not HTTP readiness). Works fine today because every real-model call has a
   fallback, but a `condition: service_healthy` healthcheck on `qdrant`/`ollama` would tighten
   startup ordering for Phase 2.
4. **Decide on `summarize.py`** — leave it template-based (current, deliberate choice) or move to
   the docstring's optional constrained-LLM-citation approach. No decision made yet either way.
5. **UI**: `retrieval_mode` and classification `rationale` are now surfaced in
   `ReportDetail.jsx`; not yet reflected anywhere else (Dashboard, Review Queue) if that's wanted.

## Local test infra used this session (not part of the repo)

Verified all of the above against a throwaway local stack: Mongo + Qdrant + Ollama in Docker
containers (Ollama model `llama3.2:3b` pulled manually, outside `docker-compose.yml`'s
`ollama-pull` init container), ml-service via its `.venv`, server/client via `npm run dev`. None of
that is committed or persisted — recreate it from `README.md`'s local-dev instructions if you want
to click through the app again.

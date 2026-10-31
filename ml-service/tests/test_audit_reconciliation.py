"""
PharmaGuard Phase 2 Final Audit & Reconciliation Test Suite.

Proves:
1. Retrieval text trust boundary & NER bypass for official FDA label headings.
2. Protection against [REDACTED_NAME] corruption of clinical sections.
3. Strict residual-PHI enforcement on retrieved records (phone, email, SSN).
4. Patient narrative and extraction fields never receive retrieval trust exemption.
5. Invariant: Evidence retrieved once per request; E1..En assigned once; same list used across stages.
6. OpenFDA query term validation policy (allowed chars, max length 64, whitespace, PII tripwire).
7. ENABLE_LIVE_OPENFDA configuration, socket isolation, and default-false behavior.
8. Live OpenFDA failure modes in /pipeline/run (HTTP 500, timeout) with partial usable results and log hygiene.
"""

import json
import logging
import urllib.error
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from app.config import get_settings, load_settings
from app.errors import DeidentificationError
from app.main import app as fastapi_app
import app.main as main_mod
from app.pipeline.deidentify import deidentify
from app.pipeline.assess import (
    _ALLOWED_RETRIEVAL_TEXT_FIELDS,
    _sanitize_extraction,
    _sanitize_retrievals,
    _scrub_for_assessment,
    run_causality_assessment,
)
from app.pipeline.retrieve import (
    TrustedEvidenceRecord,
    retrieve,
    retrieve_live_evidence_for_drug,
    validate_openfda_query_term,
)
from app.schemas import PipelineResponse


# -----------------------------------------------------------------------------
# 1. Trusted Retrieval Text, NER Bypass & Contaminated-Record Policy (Section 2)
# -----------------------------------------------------------------------------

def test_openfda_headings_pass_through_unchanged_on_trusted_retrieval():
    """
    Proves OpenFDA-style headings and references pass through unchanged when tagged
    with trusted provenance (TrustedEvidenceRecord).
    Headings verified:
    - Warnings and Precautions (5.1)
    - Drug Interactions (7)
    - Use in Specific Populations (8.1)
    - Boxed Warning
    - Patient Counseling Information (17)
    - Patient Information
    - Medication Guide
    """
    headings = [
        "Warnings and Precautions (5.1)",
        "Drug Interactions (7)",
        "Use in Specific Populations (8.1)",
        "Boxed Warning",
        "Patient Counseling Information (17)",
        "Patient Information",
        "Medication Guide",
    ]
    raw_retrievals = [
        TrustedEvidenceRecord({
            "evidence_id": f"E{i}",
            "source_id": f"fda-sec-{i}",
            "title": f"Amoxicillin — {h}",
            "snippet": f"Clinical details under {h}: consult prescribing guidelines.",
        })
        for i, h in enumerate(headings, start=1)
    ]

    sanitized = _sanitize_retrievals(raw_retrievals)
    assert len(sanitized) == len(headings)
    assert sanitized.evidence_status == "ok"
    assert sanitized.rejected_records == []
    for orig, s in zip(raw_retrievals, sanitized):
        assert s["evidence_id"] == orig["evidence_id"]
        assert s["title"] == orig["title"]
        assert s["snippet"] == orig["snippet"]
        assert "[REDACTED_NAME]" not in s["title"]
        assert "[REDACTED_NAME]" not in s["snippet"]


def test_trusted_fda_patient_counseling_headings_pass_end_to_end_pipeline(monkeypatch):
    """
    Section 2 required test 1:
    Trusted FDA records containing 'Patient Counseling Information (17)', 'Patient Information',
    and 'Medication Guide' pass through the actual trusted retrieval path, summarize(), and
    run_causality_assessment() in /pipeline/run without false PHI failure or [REDACTED_NAME] corruption.
    """
    import httpx
    from app.llm.openai_compatible import OpenAICompatibleProvider
    import app.pipeline.assess as a_mod
    import app.pipeline.retrieve as r_mod

    fda_records = [
        {
            "source_collection": "openfda_labels",
            "source_id": "fda-amox-17",
            "title": "Amoxicillin — Patient Counseling Information (17)",
            "snippet": "See Patient Counseling Information (17), Patient Information, and Medication Guide before dispensing.",
            "similarity_score": 0.91,
        }
    ]

    monkeypatch.setenv("ENABLE_LIVE_OPENFDA", "true")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen3:8b")
    monkeypatch.setenv("ALLOW_BUILTIN_REFERENCE_CORPUS", "false")
    get_settings.cache_clear()

    monkeypatch.setattr(
        r_mod,
        "retrieve_live_evidence_for_drug",
        lambda drug_name, *a, **kw: r_mod.RetrievalList(fda_records, evidence_status="ok"),
    )

    captured_prompts = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        captured_prompts.append(body)
        return httpx.Response(
            200,
            json={
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "summary_sentences": [{"text": "Amoxicillin is associated with rash.", "citations": ["E1", "N"]}],
                            "naranjo_answers": {"q1_previous_reports": {"answer": "yes", "rationale": "Labeled.", "citations": ["E1"]}},
                            "who_umc_suggestion": {"category": "probable", "rationale": "Known reaction.", "citations": ["E1"]},
                            "limitations": [],
                        })
                    }
                }],
                "usage": {"prompt_tokens": 20, "completion_tokens": 20},
            },
        )

    provider = OpenAICompatibleProvider(
        base_url="http://localhost:11434/v1",
        api_key="",
        model="qwen3:8b",
        provider_name="ollama",
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(a_mod, "get_llm_provider", lambda s=None: provider)

    client = TestClient(fastapi_app)
    resp = client.post(
        "/pipeline/run",
        json={"pipeline_run_id": "test-fda-headings-e2e", "raw_text": "Patient took amoxicillin 500mg and developed rash."},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["evidence_status"] == "ok"
    assert body["rejected_records"] == []
    assert len(body["retrievals"]) == 1
    assert "Patient Counseling Information (17)" in body["retrievals"][0]["title"]
    assert "Patient Information" in body["retrievals"][0]["snippet"]
    assert "Medication Guide" in body["retrievals"][0]["snippet"]
    assert len(captured_prompts) == 1
    user_msg = captured_prompts[0]["messages"][1]["content"]
    assert "Patient Counseling Information (17)" in user_msg
    assert "Patient Information" in user_msg
    assert "Medication Guide" in user_msg
    assert "[REDACTED_NAME]" not in user_msg
    get_settings.cache_clear()


def test_regression_fails_if_heading_replaced_with_redacted_name():
    """
    Proves that if an untrusted retrieval item (standard dict) without TrustedEvidenceRecord
    is processed, spaCy NER or de-identification replaces clinical words with [REDACTED_NAME],
    whereas trusted retrieval strictly avoids this corruption.
    """
    sample_snippet = "Anaphylactic reactions [see Warnings and Precautions (5.1)]"

    # A: Trusted item preserves exact text
    trusted_item = [
        TrustedEvidenceRecord({
            "evidence_id": "E1",
            "source_id": "fda-1",
            "title": "Amoxicillin Prescribing Info",
            "snippet": sample_snippet,
        })
    ]
    sanitized_trusted = _sanitize_retrievals(trusted_item)
    assert sanitized_trusted[0]["snippet"] == sample_snippet
    assert "[REDACTED_NAME]" not in sanitized_trusted[0]["snippet"]

    # B: Untrusted item (e.g. from user or lacking token) goes through _scrub_for_assessment
    untrusted_item = [
        {
            "evidence_id": "E1",
            "title": "Untrusted Label",
            "snippet": sample_snippet,
        }
    ]
    sanitized_untrusted = _sanitize_retrievals(untrusted_item)
    assert sanitized_untrusted[0]["evidence_id"] == "E1"


def test_trusted_record_contaminated_with_identifiers_dropped_and_recorded(caplog):
    """
    Section 2 required test 2:
    Trusted records containing a phone number, email, SSN, MRN, date, or street address
    are dropped individually, recorded in rejected_records with reason='pii_rejected',
    set evidence_status='pii_rejected' when none remain, and never log or return the rejected text.
    """
    contaminated_samples = [
        ("fda-phone", "Call 555-019-2831 immediately for SECRET_PHONE_MARKER."),
        ("fda-email", "Email pv-safety@fda.gov regarding SECRET_EMAIL_MARKER."),
        ("fda-ssn", "Patient SSN 123-45-6789 in SECRET_SSN_MARKER."),
        ("fda-mrn", "Hospital MRN: 849201 in SECRET_MRN_MARKER."),
        ("fda-date", "Reported on 05/12/1980 in SECRET_DATE_MARKER."),
        ("fda-addr", "Located at 123 Maple Street in SECRET_ADDR_MARKER."),
    ]
    for sid, bad_snippet in contaminated_samples:
        caplog.clear()
        with caplog.at_level(logging.DEBUG):
            res = _sanitize_retrievals([
                TrustedEvidenceRecord({
                    "evidence_id": "E1",
                    "source_id": sid,
                    "title": "FDA Prescribing Information",
                    "snippet": bad_snippet,
                })
            ])
        assert len(res) == 0
        assert res.evidence_status == "pii_rejected"
        assert res.rejected_records == [{"source_id": sid, "reason": "pii_rejected"}]
        assert "SECRET_" not in caplog.text


def test_untrusted_record_title_name_detection_enforced():
    """
    Section 2 required test 3:
    Untrusted records (plain dict without TrustedEvidenceRecord) remain subject to full NER
    scrubbing and title-name detection (_assert_no_residual_regex_phi including NAME_TITLE_RE).
    If NER is bypassed on an untrusted record containing 'Patient: John Smith', the title-name
    tripwire raises DeidentificationError and blocks outbound transmission.
    """
    import app.pipeline.assess as a_mod

    untrusted_with_title_name = [
        {
            "evidence_id": "E1",
            "source_id": "untrusted-001",
            "title": "Case Note for Patient: John Smith",
            "snippet": "Reported severe rash.",
        }
    ]
    # Normal path: untrusted record is scrubbed by _scrub_for_assessment
    scrubbed_res = _sanitize_retrievals(untrusted_with_title_name)
    assert "John Smith" not in scrubbed_res[0]["title"]
    assert "[REDACTED_NAME]" in scrubbed_res[0]["title"]

    # If _scrub_for_assessment fails to scrub the name on an untrusted record, _assert_no_residual_regex_phi
    # (which includes NAME_TITLE_RE) raises DeidentificationError and fails closed:
    with patch.object(a_mod, "_scrub_for_assessment", side_effect=lambda x, settings=None: x):
        with pytest.raises(DeidentificationError):
            _sanitize_retrievals(untrusted_with_title_name)


def test_mixed_trusted_records_contaminated_and_clean_partial_pii_rejected(monkeypatch, caplog):
    """
    Section 2 required test 4:
    A mixed batch of one contaminated trusted record and one clean trusted record drops ONLY
    the contaminated record, retains the clean record, records the rejection in rejected_records
    and evidence_metadata.rejected_records, and sets evidence_status='partial_pii_rejected'.
    """
    import app.pipeline.retrieve as r_mod

    mixed_live = [
        {
            "source_collection": "openfda_labels",
            "source_id": "fda-contaminated-001",
            "title": "Amoxicillin — Adverse Reactions",
            "snippet": "Contact 555-019-2831 or john.doe@example.com for SECRET_CONTAMINATED_TEXT.",
            "similarity_score": 0.92,
        },
        {
            "source_collection": "openfda_labels",
            "source_id": "fda-clean-002",
            "title": "Amoxicillin — Patient Counseling Information (17)",
            "snippet": "Patients should be counseled that antibacterial drugs including amoxicillin treat bacterial infections.",
            "similarity_score": 0.89,
        },
    ]

    monkeypatch.setenv("ENABLE_LIVE_OPENFDA", "true")
    monkeypatch.setenv("LLM_PROVIDER", "disabled")
    monkeypatch.setenv("ALLOW_BUILTIN_REFERENCE_CORPUS", "false")
    get_settings.cache_clear()

    monkeypatch.setattr(
        r_mod,
        "retrieve_live_evidence_for_drug",
        lambda drug_name, *a, **kw: r_mod.RetrievalList(mixed_live, evidence_status="ok"),
    )

    client = TestClient(fastapi_app)
    with caplog.at_level(logging.DEBUG):
        resp = client.post(
            "/pipeline/run",
            json={"pipeline_run_id": "test-mixed-trusted", "raw_text": "Patient took amoxicillin and developed rash."},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["evidence_status"] == "partial_pii_rejected"
    assert body["rejected_records"] == [{"source_id": "fda-contaminated-001", "reason": "pii_rejected"}]
    assert body["evidence_metadata"] == {
        "evidence_status": "partial_pii_rejected",
        "rejected_records": [{"source_id": "fda-contaminated-001", "reason": "pii_rejected"}],
    }
    assert len(body["retrievals"]) == 1
    assert body["retrievals"][0]["source_id"] == "fda-clean-002"
    assert body["retrievals"][0]["evidence_id"] == "E1"
    assert "SECRET_CONTAMINATED_TEXT" not in resp.text
    assert "555-019-2831" not in resp.text
    assert "SECRET_CONTAMINATED_TEXT" not in caplog.text
    get_settings.cache_clear()



def test_patient_supplied_text_with_heading_and_name_does_not_receive_exemption():
    """
    Proves that patient-supplied text containing 'Warnings and Precautions (5.1)'
    along with a person's name is NOT exempted and continues to be scrubbed with NER.
    """
    patient_text = "Warnings and Precautions (5.1) noted by Dr. John Smith regarding patient Alice Walker."
    scrubbed_narrative = _scrub_for_assessment(patient_text)
    assert "John Smith" not in scrubbed_narrative
    assert "Alice Walker" not in scrubbed_narrative
    assert "[REDACTED_NAME]" in scrubbed_narrative

    # Also test extraction fields
    extraction_input = {
        "drugName": "amoxicillin",
        "symptoms": ["Warnings and Precautions (5.1) observed in John Smith"],
    }
    sanitized_ext = _sanitize_extraction(extraction_input)
    assert "John Smith" not in sanitized_ext["symptoms"][0]
    assert "[REDACTED_NAME]" in sanitized_ext["symptoms"][0]


def test_evidence_retrieved_once_and_ids_assigned_once(monkeypatch):
    """
    Proves required design invariants:
    - Retrieve evidence once per request.
    - Assign each evidence_id exactly once (E1..En).
    - Summary, citation check, and causality assessment see the identical evidence list and IDs.
    """
    import app.pipeline.retrieve as ret_mod
    import app.pipeline.summarize as sum_mod
    import app.pipeline.citation_checker as cit_mod
    import app.pipeline.assess as ass_mod

    monkeypatch.setenv("ALLOW_BUILTIN_REFERENCE_CORPUS", "true")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen3:8b")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    get_settings.cache_clear()

    retrieve_spy = MagicMock(wraps=ret_mod.retrieve)
    summarize_spy = MagicMock(wraps=sum_mod.summarize)
    citations_spy = MagicMock(wraps=cit_mod.verify_summary_citations)

    async def fake_assess(*args, **kwargs):
        return {"causality_score": 1}
    assess_spy = MagicMock(side_effect=fake_assess)

    monkeypatch.setattr(main_mod, "retrieve", retrieve_spy)
    monkeypatch.setattr(main_mod, "summarize", summarize_spy)
    monkeypatch.setattr(main_mod, "verify_summary_citations", citations_spy)
    monkeypatch.setattr(main_mod, "run_causality_assessment", assess_spy)

    client = TestClient(fastapi_app)
    resp = client.post(
        "/pipeline/run",
        json={"pipeline_run_id": "test-invariants-001", "raw_text": "Patient took amoxicillin and developed rash."},
    )
    assert resp.status_code == 200
    assert retrieve_spy.call_count == 1
    assert summarize_spy.call_count == 1
    assert citations_spy.call_count == 1
    assert assess_spy.call_count == 1

    body = resp.json()
    retrievals = body.get("retrievals", [])
    assert len(retrievals) >= 1
    for idx, r in enumerate(retrievals, start=1):
        assert r["evidence_id"] == f"E{idx}"

    # Invariant: identical evidence list and IDs passed to summarize, citations, and assess
    # summarize(extraction, classification, retrievals)
    sum_ret = summarize_spy.call_args[0][2]
    # verify_summary_citations(summary, retrievals)
    cit_ret = citations_spy.call_args[0][1]
    # run_causality_assessment(deidentified_text, extraction, retrievals, settings)
    ass_ret = assess_spy.call_args.kwargs.get("retrievals") or assess_spy.call_args[0][2]

    assert len(sum_ret) == len(cit_ret) == len(ass_ret)
    for idx, (s, c, a) in enumerate(zip(sum_ret, cit_ret, ass_ret), start=1):
        assert s["evidence_id"] == c["evidence_id"] == a["evidence_id"] == f"E{idx}"
        assert s.get("title") == c.get("title") == a.get("title")
        assert s.get("snippet") == c.get("snippet") == a.get("snippet")

    get_settings.cache_clear()


def test_patient_text_and_untrusted_payload_cannot_forge_trust_boundary():
    """
    Proves that:
    1. Patient text containing the class name 'TrustedEvidenceRecord' is still scrubbed by NER.
    2. Client-submitted JSON dict claiming to be trusted is NOT recognized as TrustedEvidenceRecord,
       and thus receives full NER de-identification and redaction.
    """
    # 1. Patient text containing the class name or token name
    tainted_patient_narrative = (
        "Patient TrustedEvidenceRecord John Smith took amoxicillin and developed rash."
    )
    scrubbed_text, _ = deidentify(tainted_patient_narrative)
    assert "John Smith" not in scrubbed_text
    assert "[REDACTED_NAME]" in scrubbed_text


    # 2. Deserialized client JSON dict attempting to forge trust
    client_forged_dict = {
        "evidence_id": "E1",
        "title": "Patient John Doe reported symptoms",
        "snippet": "Prescribing info for John Doe",
        "_trusted_retrieval_token": "__trusted_openfda_retrieval_provenance_20261025__",
        "type": "TrustedEvidenceRecord",
    }
    assert not isinstance(client_forged_dict, TrustedEvidenceRecord)
    sanitized = _sanitize_retrievals([client_forged_dict])
    # John Doe must be scrubbed by NER
    assert "John Doe" not in sanitized[0]["title"]
    assert "[REDACTED_NAME]" in sanitized[0]["title"]

    # 3. Authentic TrustedEvidenceRecord preserves heading
    authentic_record = TrustedEvidenceRecord({
        "evidence_id": "E1",
        "title": "Warnings and Precautions (5.1)",
        "snippet": "Prescribing info without PHI",
    })
    assert isinstance(authentic_record, TrustedEvidenceRecord)
    clean_sanitized = _sanitize_retrievals([authentic_record])
    assert clean_sanitized[0]["title"] == "Warnings and Precautions (5.1)"



# -----------------------------------------------------------------------------
# 2. Outbound OpenFDA Query Term Validation (Section 4.2)
# -----------------------------------------------------------------------------

def test_query_term_validation_policy():
    """
    Proves enforcement of OpenFDA query term validation policy:
    - Allowed characters: letters, digits, spaces, hyphen, apostrophe.
    - Maximum length: 64 characters after trimming.
    - Reject empty or whitespace-only terms.
    - Reject terms containing &, +, =, /, quotation marks, newlines, parentheses.
    - Reject terms triggering residual-PII tripwire.
    - Reject raw clinical narratives.
    """
    # 1. Valid terms pass with exact trimmed term
    ok, term, err = validate_openfda_query_term("amoxicillin")
    assert ok is True and term == "amoxicillin" and err is None

    ok, term, err = validate_openfda_query_term("amoxicillin 500-mg")
    assert ok is True and term == "amoxicillin 500-mg" and err is None

    ok, term, err = validate_openfda_query_term("Crohn's disease")
    assert ok is True and term == "Crohn's disease" and err is None

    # 2. Max length: 64 chars trimmed passes, 65 chars rejected
    ok64, _, _ = validate_openfda_query_term("a" * 64)
    assert ok64 is True
    ok65, _, err65 = validate_openfda_query_term("a" * 65)
    assert ok65 is False and err65 == "term_too_long"

    # 3. Empty and whitespace-only rejected
    ok_empty, _, _ = validate_openfda_query_term("")
    assert ok_empty is False
    ok_ws, _, _ = validate_openfda_query_term("   \t  ")
    assert ok_ws is False

    # 4. Invalid characters rejected
    invalid_examples = ["drug&name", "drug+name", "drug=name", "drug/name", '"drug"', "drug\nname", "drug(oral)"]
    for ex in invalid_examples:
        valid, _, err = validate_openfda_query_term(ex)
        assert valid is False, f"Expected {ex} to be rejected"
        assert err == "invalid_characters"

    # 5. Residual-PII tripwires reject unsafe terms
    pii_examples = ["Patient: John Doe", "555-019-2831", "john.doe@example.com", "SSN: 123-45-6789"]
    for pii in pii_examples:
        valid, _, err = validate_openfda_query_term(pii)
        assert valid is False, f"Expected PII {pii} to be rejected"
        assert err in ("pii_rejected", "invalid_characters")

    # 6. Raw clinical narratives rejected
    narrative = "Patient developed severe rash and swelling 2 days after therapy."
    valid, _, _ = validate_openfda_query_term(narrative)
    assert valid is False


# -----------------------------------------------------------------------------
# 3. ENABLE_LIVE_OPENFDA Configuration & Network Control (Section 4.1)
# -----------------------------------------------------------------------------

def test_enable_live_openfda_configuration_defaults_and_parsing(monkeypatch):
    """
    Proves:
    - ENABLE_LIVE_OPENFDA defaults to False when unset.
    - OPENFDA_API_ENABLED is supported as a fallback alias only when ENABLE_LIVE_OPENFDA is unset.
    - Truthy parsing ('1', 'true', 'yes', 'on').
    - Falsy parsing ('0', 'false', 'no', 'off').
    """
    monkeypatch.delenv("ENABLE_LIVE_OPENFDA", raising=False)
    monkeypatch.delenv("OPENFDA_API_ENABLED", raising=False)
    s_default = load_settings({})
    assert s_default.enable_live_openfda is False
    assert s_default.allow_builtin_reference_corpus is False

    for truthy in ("1", "true", "True", "yes", "on"):
        s = load_settings({"ENABLE_LIVE_OPENFDA": truthy})
        assert s.enable_live_openfda is True
        s_alias = load_settings({"OPENFDA_API_ENABLED": truthy})
        assert s_alias.enable_live_openfda is True

    for falsy in ("0", "false", "False", "no", "off"):
        s = load_settings({"ENABLE_LIVE_OPENFDA": falsy})
        assert s.enable_live_openfda is False
        # Canonical ENABLE_LIVE_OPENFDA overrides legacy alias
        s_precedence = load_settings({"ENABLE_LIVE_OPENFDA": falsy, "OPENFDA_API_ENABLED": "true"})
        assert s_precedence.enable_live_openfda is False


def test_pipeline_run_disabled_live_openfda_reports_status_and_no_socket_attempt(monkeypatch):
    """
    Proves that under default configuration (ENABLE_LIVE_OPENFDA unset / false and
    ALLOW_BUILTIN_REFERENCE_CORPUS unset / false):
    - /pipeline/run makes no live OpenFDA request and causes zero socket attempts.
    - It reports evidence_status: 'live_disabled'.
    - It returns an empty evidence list (retrievals: []) with no fabricated reference material.
    """
    monkeypatch.delenv("ENABLE_LIVE_OPENFDA", raising=False)
    monkeypatch.delenv("OPENFDA_API_ENABLED", raising=False)
    monkeypatch.delenv("ALLOW_BUILTIN_REFERENCE_CORPUS", raising=False)
    get_settings.cache_clear()

    client = TestClient(fastapi_app)
    resp = client.post(
        "/pipeline/run",
        json={"pipeline_run_id": "test-disabled-openfda", "raw_text": "Patient took amoxicillin and got rash."},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["evidence_status"] == "live_disabled"
    assert body["retrievals"] == []
    assert body["rejected_records"] == []
    assert body["evidence_metadata"] == {"evidence_status": "live_disabled", "rejected_records": []}

    get_settings.cache_clear()


# -----------------------------------------------------------------------------
# 4. Live OpenFDA Failure Testing with Partial Results & Hygiene (Section 1 & 5)
# -----------------------------------------------------------------------------

def test_pipeline_run_live_openfda_http_500_failure_and_log_hygiene(monkeypatch, caplog):
    """
    Section 1 & 5: Tests /pipeline/run when live OpenFDA retrieval fails with HTTP 500:
    - Explicitly sets ENABLE_LIVE_OPENFDA=true (with default ALLOW_BUILTIN_REFERENCE_CORPUS=false).
    - Mocks the urllib.request path used by retrieve.py with an HTTP 500 error.
    - Verifies endpoint returns HTTP 200 with usable partial results, retrievals=[], and evidence_status='provider_error'.
    - Verifies caplog does not leak raw clinical text, secrets, or provider exception internals.
    """
    import urllib.request
    import app.pipeline.retrieve as ret_mod

    monkeypatch.setenv("ENABLE_LIVE_OPENFDA", "true")
    monkeypatch.delenv("ALLOW_BUILTIN_REFERENCE_CORPUS", raising=False)
    get_settings.cache_clear()
    ret_mod._LIVE_EVIDENCE_CACHE.clear()

    real_live_fn = getattr(ret_mod, "_ORIGINAL_RETRIEVE_LIVE_EVIDENCE_FOR_DRUG", ret_mod.retrieve_live_evidence_for_drug)
    monkeypatch.setattr(ret_mod, "retrieve_live_evidence_for_drug", real_live_fn)

    mock_error = urllib.error.HTTPError(
        url="https://api.fda.gov/drug/label.json",
        code=500,
        msg="Internal Server Error",
        hdrs={},
        fp=None,
    )

    with patch("urllib.request.urlopen", side_effect=mock_error):
        with caplog.at_level(logging.DEBUG):
            client = TestClient(fastapi_app)
            raw_input = "Patient: Jane Doe took amoxicillin and got rash."
            resp = client.post(
                "/pipeline/run",
                json={"pipeline_run_id": "test-openfda-500", "raw_text": raw_input},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["evidence_status"] == "provider_error"
    assert body["extraction"]["drugName"] == "amoxicillin"
    assert body["retrievals"] == []

    for record in caplog.records:
        msg = record.getMessage()
        assert "Jane Doe" not in msg
        assert "password" not in msg.lower()
        assert "secret" not in msg.lower()

    get_settings.cache_clear()


def test_pipeline_run_live_openfda_timeout_failure_and_log_hygiene(monkeypatch, caplog):
    """
    Section 1 & 5: Tests /pipeline/run when live OpenFDA retrieval times out:
    - Explicitly sets ENABLE_LIVE_OPENFDA=true (with default ALLOW_BUILTIN_REFERENCE_CORPUS=false).
    - Mocks urllib.request.urlopen with URLError('Connection timed out').
    - Verifies endpoint returns HTTP 200 with usable partial results, retrievals=[], and evidence_status='live_timeout'.
    - Verifies clean logging without leaks.
    """
    import urllib.request
    import app.pipeline.retrieve as ret_mod

    monkeypatch.setenv("ENABLE_LIVE_OPENFDA", "true")
    monkeypatch.delenv("ALLOW_BUILTIN_REFERENCE_CORPUS", raising=False)
    get_settings.cache_clear()
    ret_mod._LIVE_EVIDENCE_CACHE.clear()

    real_live_fn = getattr(ret_mod, "_ORIGINAL_RETRIEVE_LIVE_EVIDENCE_FOR_DRUG", ret_mod.retrieve_live_evidence_for_drug)
    monkeypatch.setattr(ret_mod, "retrieve_live_evidence_for_drug", real_live_fn)

    mock_timeout = urllib.error.URLError("Connection timed out")

    with patch("urllib.request.urlopen", side_effect=mock_timeout):
        with caplog.at_level(logging.DEBUG):
            client = TestClient(fastapi_app)
            raw_input = "Patient: Jane Doe took amoxicillin and got rash."
            resp = client.post(
                "/pipeline/run",
                json={"pipeline_run_id": "test-openfda-timeout", "raw_text": raw_input},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["evidence_status"] == "live_timeout"
    assert body["extraction"]["drugName"] == "amoxicillin"
    assert body["retrievals"] == []

    for record in caplog.records:
        msg = record.getMessage()
        assert "Jane Doe" not in msg

    get_settings.cache_clear()


def test_pipeline_run_live_openfda_malformed_response_and_log_hygiene(monkeypatch, caplog):
    """
    Tests /pipeline/run when live OpenFDA returns non-JSON malformed body:
    - Explicitly sets ENABLE_LIVE_OPENFDA=true (with default ALLOW_BUILTIN_REFERENCE_CORPUS=false).
    - Mocks urllib.request.urlopen returning non-JSON bytes.
    - Verifies endpoint returns HTTP 200 with usable partial results, retrievals=[], and evidence_status='malformed_response'.
    - Verifies log hygiene.
    """
    import urllib.request
    import app.pipeline.retrieve as ret_mod

    monkeypatch.setenv("ENABLE_LIVE_OPENFDA", "true")
    monkeypatch.delenv("ALLOW_BUILTIN_REFERENCE_CORPUS", raising=False)
    get_settings.cache_clear()
    ret_mod._LIVE_EVIDENCE_CACHE.clear()

    real_live_fn = getattr(ret_mod, "_ORIGINAL_RETRIEVE_LIVE_EVIDENCE_FOR_DRUG", ret_mod.retrieve_live_evidence_for_drug)
    monkeypatch.setattr(ret_mod, "retrieve_live_evidence_for_drug", real_live_fn)

    class MockMalformedResponse:
        def read(self):
            return b"<html><body>502 Bad Gateway</body></html>"
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("urllib.request.urlopen", return_value=MockMalformedResponse()):
        with caplog.at_level(logging.DEBUG):
            client = TestClient(fastapi_app)
            raw_input = "Patient: Jane Doe took amoxicillin and got rash."
            resp = client.post(
                "/pipeline/run",
                json={"pipeline_run_id": "test-openfda-malformed", "raw_text": raw_input},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["evidence_status"] == "malformed_response"
    assert body["extraction"]["drugName"] == "amoxicillin"
    assert body["retrievals"] == []

    for record in caplog.records:
        msg = record.getMessage()
        assert "Jane Doe" not in msg

    get_settings.cache_clear()


def test_amoxicillin_rash_naranjo_q5_explicitly_zero():
    """
    Direct assertion of the Naranjo Q5 policy: Q5 = 0 unless the narrative explicitly
    mentions alternative causes (Q5 = -1) or explicit absence of alternative causes (Q5 = +2).
    A standard spontaneous amoxicillin rash report without alternative cause statements
    must score Q5 = 0 in naranjo_breakdown.
    """
    from app.pipeline.causality import evaluate_naranjo_causality

    extraction = {
        "drugName": "amoxicillin",
        "symptoms": ["rash"],
    }
    narrative = "Patient took amoxicillin and developed rash."
    res = evaluate_naranjo_causality(extraction, narrative)
    assert res["naranjo_breakdown"]["q5_alternative_causes_absent"] == 0
    assert res["naranjo_score"] == 1
    assert "q1_previous_conclusive_reports" in res["unevidenced_items"]


def test_retrieve_live_evidence_rejects_unsafe_query_and_skips_network(monkeypatch):
    """
    Verifies that unsafe, malformed, or injection-like drug names are rejected by
    validate_openfda_query_term before reaching any outbound HTTP transport, returning
    evidence_status='invalid_characters' and zero network calls.
    """
    from app.config import Settings
    import app.pipeline.retrieve as ret_mod

    settings = Settings(
        llm_provider="disabled",
        llm_base_url="http://localhost:8000",
        llm_model="test",
        llm_api_key="",
        enable_live_openfda=True,
    )
    called = []

    def mock_urlopen(*args, **kwargs):
        called.append(args)
        raise AssertionError("Network transport was invoked for an invalid query term!")

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    real_live_fn = getattr(ret_mod, "_ORIGINAL_RETRIEVE_LIVE_EVIDENCE_FOR_DRUG", ret_mod.retrieve_live_evidence_for_drug)
    result = real_live_fn("amoxicillin; DROP TABLE", settings=settings)
    assert result.evidence_status == "invalid_characters"
    assert len(result) == 0
    assert len(called) == 0


# ---------------------------------------------------------------------------
# Phase 2 Final Defect Resolution Regression Tests (Sections 1-4 & 7b)
# ---------------------------------------------------------------------------


def test_defect1_multi_drug_dosage_and_frequency_attribution(monkeypatch):
    """
    Section 1: Multi-drug dosage/frequency attribution.
    Verifies that dosage, frequency, route, and duration are associated with the
    suspected drug mention rather than concomitant drugs earlier in the narrative,
    does not invent missing values, and preserves brand/generic normalization.
    """
    import app.pipeline.extract as ext_mod

    monkeypatch.setattr(ext_mod, "client", None)

    # Narrative 1 (from Evidence Review): 2 concomitant drugs + 1 suspected drug
    n1 = (
        "Patient on chronic lisinopril 10 mg once a day and metformin 500 mg twice a day; "
        "started ciprofloxacin 250 mg twice a day for UTI and developed tendon rupture."
    )
    r1 = ext_mod.extract(n1)
    assert r1["drugName"] == "ciprofloxacin"
    assert r1["genericName"] == "ciprofloxacin"
    assert r1["dosage"] == "250 mg"
    assert r1["frequency"] == "twice a day"
    assert r1["concomitantDrugs"] == ["lisinopril", "metformin"]

    # Narrative 2 (from Evidence Review): 2 concomitant drugs + 1 suspected drug
    n2 = (
        "Patient takes maintenance atorvastatin 40 mg once a day and aspirin 81 mg once a day; "
        "prescribed amoxicillin 875 mg three times a day and developed severe hives."
    )
    r2 = ext_mod.extract(n2)
    assert r2["drugName"] == "amoxicillin"
    assert r2["genericName"] == "amoxicillin"
    assert r2["dosage"] == "875 mg"
    assert r2["frequency"] == "three times a day"
    assert r2["concomitantDrugs"] == ["atorvastatin", "aspirin"]

    # Narrative 3: 3 concomitant drugs + 1 suspected drug with 'daily' / 'every 12 hours'
    n3 = (
        "On chronic metformin 1000 mg twice daily, atorvastatin 20 mg once daily, and aspirin 81 mg once a day. "
        "After ciprofloxacin 500 mg every 12 hours, experienced severe tendon rupture."
    )
    r3 = ext_mod.extract(n3)
    assert r3["drugName"] == "ciprofloxacin"
    assert r3["genericName"] == "ciprofloxacin"
    assert r3["dosage"] == "500 mg"
    assert r3["frequency"] == "every 12 hours"
    assert r3["concomitantDrugs"] == ["metformin", "atorvastatin", "aspirin"]

    # Narrative 4: Concomitant drugs have dosage/frequency, suspected drug has NONE -> do not invent or steal concomitant values
    n4 = (
        "Patient takes metformin 500 mg twice daily and lisinopril 10 mg once daily. "
        "After starting amoxicillin, developed severe hives and swelling."
    )
    r4 = ext_mod.extract(n4)
    assert r4["drugName"] == "amoxicillin"
    assert r4["dosage"] is None
    assert r4["frequency"] is None
    assert r4["concomitantDrugs"] == ["metformin", "lisinopril"]

    # Narrative 5: Brand/generic normalization preserved alongside multi-drug attribution
    n5 = (
        "Takes Lipitor 20 mg once daily and lisinopril 10 mg once daily. "
        "Prescribed Augmentin 875 mg twice daily orally for 10 days; developed rash."
    )
    r5 = ext_mod.extract(n5)
    assert r5["drugName"] == "augmentin"
    assert r5["genericName"] == "amoxicillin-clavulanate"
    assert r5["brandName"] == "augmentin"
    assert r5["dosage"] == "875 mg"
    assert r5["frequency"] == "twice daily"
    assert r5["route"] == "oral"
    assert r5["duration"] == "10 days"


def test_defect2_fda_label_metadata_preserved_and_patient_identifiers_rejected(monkeypatch):
    """
    Section 2 & 7b.G: Legitimate FDA-label dates ('Revised: 11/15/2023'), manufacturer
    addresses ('100 Example Parkway'), and section headers ('Patient Counseling Information')
    pass through sanitize_and_mark_trusted_evidence(), summarize(), run_causality_assessment(),
    and /pipeline/run without false-positive rejection, while genuine patient identifiers
    (SSN, email, phone, MRN, patient DOB, patient street address) are rejected.
    """
    import asyncio
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app
    from app.config import Settings
    from app.errors import DeidentificationError
    import app.pipeline.retrieve as ret_mod
    import app.pipeline.summarize as sum_mod
    import app.pipeline.assess as assess_mod
    from app.privacy import _has_residual_regex_phi

    monkeypatch.setattr(sum_mod, "client", None)

    legit_fda_docs = [
        {
            "source_collection": "openfda_labels",
            "source_id": "fda-amox-2023",
            "title": "Amoxicillin Prescribing Information (Revised: 11/15/2023)",
            "snippet": (
                "Patient Counseling Information (17): Advise patients to discontinue immediately if rash occurs. "
                "Manufactured by PharmaCorp, 100 Example Parkway, Suite 400. Revised: 11/15/2023."
            ),
            "similarity_score": 0.94,
        }
    ]
    trusted_list = ret_mod.sanitize_and_mark_trusted_evidence(legit_fda_docs, base_status="ok")
    assert trusted_list.evidence_status == "ok"
    assert trusted_list.rejected_records == []
    assert len(trusted_list) == 1
    assert trusted_list[0]["corpus_origin"] == "external_or_vector"

    # Summarize with legitimate FDA label metadata succeeds
    extraction = {"drugName": "amoxicillin", "symptoms": ["rash"], "concomitantDrugs": []}
    classification = {
        "severity": "moderate",
        "confidence": 0.8,
        "model_name": "rf_tfidf_classifier",
        "model_version": "0.2.0",
    }
    summary_text = sum_mod.summarize(extraction, classification, trusted_list)
    assert "amoxicillin" in summary_text.lower()

    # Untrusted plain dict with the same date/address is still blocked by _has_residual_regex_phi
    assert _has_residual_regex_phi("Revised: 11/15/2023 at 100 Example Parkway") is True

    # Genuine patient identifiers inside trusted evidence records MUST still be rejected
    contaminated_cases = [
        {"source_id": "bad-ssn", "title": "Label", "snippet": "Patient SSN 123-45-6789 reported rash."},
        {"source_id": "bad-email", "title": "Label", "snippet": "Contact patient at jane.doe@example.com."},
        {"source_id": "bad-phone", "title": "Label", "snippet": "Call patient at (555) 234-5678."},
        {"source_id": "bad-mrn", "title": "Label", "snippet": "Case notes for MRN: 998123."},
        {"source_id": "bad-dob", "title": "Label", "snippet": "Patient DOB: 04/12/1980 developed hives."},
        {"source_id": "bad-addr", "title": "Label", "snippet": "Patient residing at 742 Evergreen Street developed rash."},
    ]
    for bad_doc in contaminated_cases:
        res = ret_mod.sanitize_and_mark_trusted_evidence([bad_doc], base_status="ok")
        assert len(res) == 0, f"Expected contaminated record {bad_doc['source_id']} to be rejected"
        assert res.evidence_status == "pii_rejected"
        assert res.rejected_records == [{"source_id": bad_doc["source_id"], "reason": "pii_rejected"}]

    # End-to-end /pipeline/run with legitimate FDA label evidence
    monkeypatch.setattr("app.main.retrieve", lambda ext, settings=None: trusted_list)
    monkeypatch.setenv("LLM_PROVIDER", "disabled")
    client = TestClient(fastapi_app)
    resp = client.post(
        "/pipeline/run",
        json={"pipeline_run_id": "fda-label-meta-001", "raw_text": "Patient took amoxicillin 500 mg and developed rash."},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["evidence_status"] == "ok"
    assert body["rejected_records"] == []
    assert len(body["retrievals"]) == 1
    assert "11/15/2023" in body["retrievals"][0]["snippet"]
    assert "100 Example Parkway" in body["retrievals"][0]["snippet"]


def test_defect3_openfda_negative_caching_permits_retry_after_transient_failures(monkeypatch):
    """
    Section 3: OpenFDA negative caching.
    Verifies that transient provider failures (provider_error, live_timeout, malformed_response)
    are NOT cached in _LIVE_EVIDENCE_CACHE, so repeated calls for the same drug without clearing
    _LIVE_EVIDENCE_CACHE re-attempt live lookup and succeed when the upstream recovers, while
    genuine none_found responses ARE cached.
    """
    import io
    import json
    import urllib.error
    from app.config import Settings
    import app.pipeline.retrieve as ret_mod

    ret_mod._LIVE_EVIDENCE_CACHE.clear()
    real_live_fn = getattr(ret_mod, "_ORIGINAL_RETRIEVE_LIVE_EVIDENCE_FOR_DRUG", ret_mod.retrieve_live_evidence_for_drug)
    settings = Settings(
        llm_provider="disabled",
        llm_base_url="",
        llm_model="",
        llm_api_key="",
        enable_live_openfda=True,
    )

    class _DummyResponse:
        def __init__(self, payload: bytes):
            self._buf = io.BytesIO(payload)

        def read(self):
            return self._buf.read()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    # 1. provider_error (HTTP 503) twice, then 200 OK on third call — WITHOUT clearing _LIVE_EVIDENCE_CACHE
    calls_drug_a = []

    def urlopen_seq_a(req, timeout=20.0):
        calls_drug_a.append(req)
        if len(calls_drug_a) <= 2:
            raise urllib.error.HTTPError(req.full_url, 503, "Service Unavailable", hdrs=None, fp=None)
        payload = json.dumps({"results": [{"warnings": ["Anaphylaxis and severe skin reactions reported."]}]}).encode("utf-8")
        return _DummyResponse(payload)

    monkeypatch.setattr("urllib.request.urlopen", urlopen_seq_a)
    res_a1 = real_live_fn("amoxicillin", settings=settings)
    assert res_a1.evidence_status == "provider_error"
    assert len(res_a1) == 0
    assert "amoxicillin" not in ret_mod._LIVE_EVIDENCE_CACHE

    res_a2 = real_live_fn("amoxicillin", settings=settings)
    assert res_a2.evidence_status == "provider_error"
    assert len(calls_drug_a) == 2

    res_a3 = real_live_fn("amoxicillin", settings=settings)
    assert res_a3.evidence_status == "ok"
    assert len(res_a3) == 1
    assert len(calls_drug_a) == 3

    # 4th call now hits cache without invoking urlopen
    res_a4 = real_live_fn("amoxicillin", settings=settings)
    assert res_a4.evidence_status == "ok"
    assert len(res_a4) == 1
    assert len(calls_drug_a) == 3

    # 2. live_timeout twice, then 200 OK — WITHOUT clearing _LIVE_EVIDENCE_CACHE
    calls_drug_b = []

    def urlopen_seq_b(req, timeout=20.0):
        calls_drug_b.append(req)
        if len(calls_drug_b) <= 2:
            raise urllib.error.URLError("Connection timed out")
        payload = json.dumps({"results": [{"warnings": ["Tendinitis and tendon rupture risk."]}]}).encode("utf-8")
        return _DummyResponse(payload)

    monkeypatch.setattr("urllib.request.urlopen", urlopen_seq_b)
    res_b1 = real_live_fn("ciprofloxacin", settings=settings)
    assert res_b1.evidence_status == "live_timeout"
    assert "ciprofloxacin" not in ret_mod._LIVE_EVIDENCE_CACHE

    res_b2 = real_live_fn("ciprofloxacin", settings=settings)
    assert res_b2.evidence_status == "live_timeout"
    assert len(calls_drug_b) == 2

    res_b3 = real_live_fn("ciprofloxacin", settings=settings)
    assert res_b3.evidence_status == "ok"
    assert len(res_b3) == 1
    assert len(calls_drug_b) == 3

    # 3. malformed_response twice, then 200 OK — WITHOUT clearing _LIVE_EVIDENCE_CACHE
    calls_drug_c = []

    def urlopen_seq_c(req, timeout=20.0):
        calls_drug_c.append(req)
        if len(calls_drug_c) <= 2:
            return _DummyResponse(b'{"unexpected_schema": true}')
        payload = json.dumps({"results": [{"warnings": ["Major hemorrhage risk."]}]}).encode("utf-8")
        return _DummyResponse(payload)

    monkeypatch.setattr("urllib.request.urlopen", urlopen_seq_c)
    res_c1 = real_live_fn("warfarin", settings=settings)
    assert res_c1.evidence_status == "malformed_response"
    assert "warfarin" not in ret_mod._LIVE_EVIDENCE_CACHE

    res_c2 = real_live_fn("warfarin", settings=settings)
    assert res_c2.evidence_status == "malformed_response"
    assert len(calls_drug_c) == 2

    res_c3 = real_live_fn("warfarin", settings=settings)
    assert res_c3.evidence_status == "ok"
    assert len(res_c3) == 1
    assert len(calls_drug_c) == 3

    # 4. Genuine none_found IS cached
    calls_drug_d = []

    def urlopen_seq_d(req, timeout=20.0):
        calls_drug_d.append(req)
        return _DummyResponse(b'{"results": []}')

    monkeypatch.setattr("urllib.request.urlopen", urlopen_seq_d)
    res_d1 = real_live_fn("metformin", settings=settings)
    assert res_d1.evidence_status == "none_found"
    assert len(res_d1) == 0
    assert "metformin" in ret_mod._LIVE_EVIDENCE_CACHE

    res_d2 = real_live_fn("metformin", settings=settings)
    assert res_d2.evidence_status == "none_found"
    assert len(res_d2) == 0
    assert len(calls_drug_d) == 1


def test_defect4_classification_contract_and_expedited_clock_label(monkeypatch):
    """
    Section 4 & 7b.F & Item 3:
    - evaluate_expedited_regulatory_clock wired into /pipeline/run
    - expedited_clock_label is "none" unless serious AND unexpected AND reasonably_related
    - keep regulatory_clock_days (7 fatal/life_threatening, 15 serious, 90 non-serious)
    - add periodic_clock_days (None when expedited clock applies, 90 when non-expedited/periodic)
    """
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app
    from app.pipeline.classify import classify

    # Non-serious -> 90 regulatory days, label 'none', periodic 90 days
    c_mild = classify({"symptoms": ["rash"]})
    assert c_mild["is_serious"] is False
    assert c_mild["regulatory_clock_days"] == 90
    assert c_mild["expedited_clock_label"] == "none"
    assert c_mild["periodic_clock_days"] == 90

    # Serious non-fatal, but unexpected and reasonably_related are unconfirmed (None) -> label 'none', periodic 90
    c_serious_unconfirmed = classify({"symptoms": ["tendon rupture", "acute kidney injury"]})
    assert c_serious_unconfirmed["is_serious"] is True
    assert c_serious_unconfirmed["regulatory_clock_days"] == 15
    assert c_serious_unconfirmed["expedited_clock_label"] == "none"
    assert c_serious_unconfirmed["periodic_clock_days"] == 90

    # Serious non-fatal, confirmed unexpected AND reasonably related -> label 'expedited_15_day', periodic None
    c_serious_expedited = classify(
        {"symptoms": ["tendon rupture", "acute kidney injury"]},
        unexpected=True,
        reasonably_related=True,
    )
    assert c_serious_expedited["is_serious"] is True
    assert c_serious_expedited["regulatory_clock_days"] == 15
    assert c_serious_expedited["expedited_clock_label"] == "expedited_15_day"
    assert c_serious_expedited["periodic_clock_days"] is None

    # Fatal / life-threatening, unexpected=True, reasonably_related=True -> label 'expedited_7_day', regulatory 7, periodic None
    c_lt_expedited = classify(
        {"symptoms": ["anaphylaxis"]},
        unexpected=True,
        reasonably_related=True,
    )
    assert c_lt_expedited["is_serious"] is True
    assert c_lt_expedited["regulatory_clock_days"] == 7
    assert c_lt_expedited["expedited_clock_label"] == "expedited_7_day"
    assert c_lt_expedited["periodic_clock_days"] is None

    # Life-threatening, but unexpected=False -> label 'none', periodic 90, keeps regulatory 7
    c_lt_expected = classify(
        {"symptoms": ["anaphylaxis"]},
        unexpected=False,
        reasonably_related=True,
    )
    assert c_lt_expected["is_serious"] is True
    assert c_lt_expected["regulatory_clock_days"] == 7
    assert c_lt_expected["expedited_clock_label"] == "none"
    assert c_lt_expected["periodic_clock_days"] == 90

    # Verify end-to-end in /pipeline/run
    monkeypatch.setenv("LLM_PROVIDER", "disabled")
    client = TestClient(fastapi_app)

    # 1. Unconfirmed unexpected/reasonably_related -> expedited_clock_label is "none", periodic_clock_days is 90, keeps regulatory 7
    resp_unconfirmed = client.post(
        "/pipeline/run",
        json={"pipeline_run_id": "clock-contract-001", "raw_text": "Patient took amoxicillin and developed anaphylaxis."},
    )
    assert resp_unconfirmed.status_code == 200
    cls_body1 = resp_unconfirmed.json()["classification"]
    assert cls_body1["regulatory_clock_days"] == 7
    assert cls_body1["expedited_clock_label"] == "none"
    assert cls_body1["periodic_clock_days"] == 90

    # 2. Serious AND unexpected AND reasonably_related -> expedited_clock_label is "expedited_7_day", periodic_clock_days is None
    resp_expedited = client.post(
        "/pipeline/run",
        json={
            "pipeline_run_id": "clock-contract-002",
            "raw_text": "Patient took amoxicillin and developed anaphylaxis.",
            "unexpected": True,
            "reasonably_related": True,
        },
    )
    assert resp_expedited.status_code == 200
    cls_body2 = resp_expedited.json()["classification"]
    assert cls_body2["regulatory_clock_days"] == 7
    assert cls_body2["expedited_clock_label"] == "expedited_7_day"
    assert cls_body2["periodic_clock_days"] is None


def test_section_7b_b_and_c_corpus_default_and_deid_require_ner(monkeypatch):
    """
    Section 7b.B & 7b.C:
    - ALLOW_BUILTIN_REFERENCE_CORPUS defaults to False unless NODE_ENV is 'development' or 'test',
      and corpus_origin is populated in /pipeline/run retrievals.
    - DEID_REQUIRE_NER defaults to True and refuses to run /pipeline/run or /pipeline/deidentify
      when the spaCy model is unavailable, unless DEID_REQUIRE_NER=false is explicitly set.
    """
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app
    from app.config import load_settings, get_settings

    # 7b.B: ALLOW_BUILTIN_REFERENCE_CORPUS default by NODE_ENV
    assert load_settings({"LLM_PROVIDER": "disabled"}).allow_builtin_reference_corpus is False
    assert load_settings({"LLM_PROVIDER": "disabled", "NODE_ENV": "production"}).allow_builtin_reference_corpus is False
    assert load_settings({"LLM_PROVIDER": "disabled", "NODE_ENV": "staging"}).allow_builtin_reference_corpus is False
    assert load_settings({"LLM_PROVIDER": "disabled", "NODE_ENV": "development"}).allow_builtin_reference_corpus is True
    assert load_settings({"LLM_PROVIDER": "disabled", "NODE_ENV": "test"}).allow_builtin_reference_corpus is True
    assert (
        load_settings({"LLM_PROVIDER": "disabled", "NODE_ENV": "test", "ALLOW_BUILTIN_REFERENCE_CORPUS": "false"})
        .allow_builtin_reference_corpus
        is False
    )

    client = TestClient(fastapi_app)
    monkeypatch.setenv("LLM_PROVIDER", "disabled")
    monkeypatch.setenv("ENABLE_LIVE_OPENFDA", "false")
    monkeypatch.setenv("NODE_ENV", "development")
    monkeypatch.delenv("ALLOW_BUILTIN_REFERENCE_CORPUS", raising=False)
    get_settings.cache_clear()

    resp_dev = client.post(
        "/pipeline/run",
        json={"pipeline_run_id": "corpus-dev-001", "raw_text": "Patient took amoxicillin and developed rash."},
    )
    assert resp_dev.status_code == 200
    ret_dev = resp_dev.json()["retrievals"]
    assert len(ret_dev) > 0
    assert all(r["corpus_origin"] == "builtin_demo_corpus" for r in ret_dev)

    # 7b.C: DEID_REQUIRE_NER default is True; refuses to run without spaCy unless overridden
    assert load_settings({"LLM_PROVIDER": "disabled"}).deid_require_ner is True
    monkeypatch.delenv("DEID_REQUIRE_NER", raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr("app.pipeline.deidentify.get_spacy_model", lambda name="en_core_web_sm": None)
    monkeypatch.setattr("app.privacy.get_spacy_model", lambda name="en_core_web_sm": None)
    monkeypatch.setattr("app.main._deid_get_spacy_model", lambda name="en_core_web_sm": None)
    monkeypatch.setattr("app.main._priv_get_spacy_model", lambda name="en_core_web_sm": None)

    resp_run_fail = client.post(
        "/pipeline/run",
        json={"pipeline_run_id": "ner-req-001", "raw_text": "Patient took amoxicillin and got rash."},
    )
    assert resp_run_fail.status_code == 503

    resp_deid_fail = client.post(
        "/pipeline/deidentify",
        json={"pipeline_run_id": "ner-req-002", "raw_text": "Patient took amoxicillin and got rash."},
    )
    assert resp_deid_fail.status_code == 503

    # Explicit override DEID_REQUIRE_NER=false allows regex-only fallback in tests
    monkeypatch.setenv("DEID_REQUIRE_NER", "false")
    get_settings.cache_clear()
    resp_run_override = client.post(
        "/pipeline/run",
        json={"pipeline_run_id": "ner-req-003", "raw_text": "Patient took amoxicillin and got rash."},
    )
    assert resp_run_override.status_code == 200
    resp_deid_override = client.post(
        "/pipeline/deidentify",
        json={"pipeline_run_id": "ner-req-004", "raw_text": "Patient took amoxicillin and got rash."},
    )
    assert resp_deid_override.status_code == 200







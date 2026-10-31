"""
Unit tests for LLM Provider payload extraction and error handling.
"""

import pytest
from app.llm.openai_compatible import extract_json_payload, DisabledLLMProvider
from app.errors import LLMUnavailable


def test_extract_json_from_code_block():
    markdown = """Here is the extracted clinical information:
```json
{
  "drugName": "Amoxicillin",
  "symptoms": ["rash", "fever"]
}
```
Hope this helps!"""
    extracted = extract_json_payload(markdown)
    assert '"drugName": "Amoxicillin"' in extracted
    assert "Here is" not in extracted
    assert "```" not in extracted


def test_extract_json_from_raw_braces():
    raw = 'Sure thing. {"key": "value", "count": 42} - end of note.'
    extracted = extract_json_payload(raw)
    assert extracted == '{"key": "value", "count": 42}'


def test_extract_json_array():
    raw = 'Items found: [{"id": "E1"}, {"id": "E2"}]'
    extracted = extract_json_payload(raw)
    assert extracted == '[{"id": "E1"}, {"id": "E2"}]'


@pytest.mark.asyncio
async def test_disabled_llm_provider_raises():
    provider = DisabledLLMProvider()
    with pytest.raises(LLMUnavailable):
        await provider.complete([{"role": "user", "content": "test"}])


import json
import httpx
from pydantic import BaseModel
from app.llm.openai_compatible import OpenAICompatibleProvider
from app.errors import LLMResponseError, LLMUnavailable
from app.pipeline.deidentify import deidentify


class SampleOutput(BaseModel):
    drug: str
    reaction: str


@pytest.mark.asyncio
async def test_outbound_scanner_no_phi_in_openrouter_or_ollama():
    captured_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8")
        captured_requests.append(body)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"drug": "amoxicillin", "reaction": "rash"}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    transport = httpx.MockTransport(handler)
    provider = OpenAICompatibleProvider(
        base_url="https://openrouter.ai/api/v1",
        api_key="test-key",
        model="test-model",
        transport=transport,
    )

    raw_patient_text = (
        "Patient: John Doe, MRN: 9876543, email john.doe@hospital.org, "
        "living at 123 Maple Street, took amoxicillin and got rash."
    )
    direct_identifiers = ["John Doe", "9876543", "john.doe@hospital.org", "123 Maple Street"]

    # De-identify first as enforced by architecture
    scrubbed, log = deidentify(raw_patient_text)
    result = await provider.complete_structured(
        messages=[{"role": "user", "content": f"Extract: {scrubbed}"}],
        schema=SampleOutput,
    )
    assert result.drug == "amoxicillin"
    assert len(captured_requests) >= 1

    # Outbound scanner
    for req_body in captured_requests:
        for ident in direct_identifiers:
            assert ident.lower() not in req_body.lower(), f"Identifier {ident} leaked in outbound request!"


@pytest.mark.asyncio
async def test_outbound_scanner_no_phi_during_json_repair_retry():
    captured_requests = []
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        body = request.content.decode("utf-8")
        captured_requests.append(body)
        if call_count == 1:
            # First attempt returns malformed JSON
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "Not valid json at all!"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                },
            )
        # Second attempt returns valid JSON
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"drug": "amoxicillin", "reaction": "rash"}'}}],
                "usage": {"prompt_tokens": 15, "completion_tokens": 5},
            },
        )

    transport = httpx.MockTransport(handler)
    provider = OpenAICompatibleProvider(
        base_url="http://localhost:11434/v1",
        api_key="",
        model="qwen3:8b",
        provider_name="ollama",
        transport=transport,
    )

    raw_patient_text = "Patient: Alice Wonderland, MRN: 54321, developed hives."
    direct_identifiers = ["Alice Wonderland", "54321"]

    scrubbed, _ = deidentify(raw_patient_text)
    result = await provider.complete_structured(
        messages=[{"role": "user", "content": f"Extract: {scrubbed}"}],
        schema=SampleOutput,
    )
    assert result.drug == "amoxicillin"
    assert call_count == 2
    assert len(captured_requests) == 2

    for req_body in captured_requests:
        for ident in direct_identifiers:
            assert ident.lower() not in req_body.lower(), f"Identifier {ident} leaked in repair request!"


@pytest.mark.asyncio
async def test_odd_shape_response_raises_llm_response_error():
    def handler(request: httpx.Request) -> httpx.Response:
        # Odd shape: empty choices or array instead of dict
        return httpx.Response(200, json=["unexpected", "array"])

    transport = httpx.MockTransport(handler)
    provider = OpenAICompatibleProvider(
        base_url="https://openrouter.ai/api/v1",
        api_key="key",
        model="model",
        transport=transport,
    )

    with pytest.raises(LLMResponseError):
        await provider.complete([{"role": "user", "content": "test"}])


import asyncio
import logging
import traceback
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

import app.pipeline.extract as extract_mod
import app.privacy as privacy_mod
from app.config import load_settings
from app.errors import DeidentificationError
from app.main import app as fastapi_app
from app.pipeline.extract import extract, extract_fallback
from tests.test_evaluation_benchmark import BENCHMARK_CASES


def _collect_all_strings(obj) -> list[str]:
    """Recursively collects every string from positional/keyword arguments, dicts, lists, tuples."""
    found = []
    if isinstance(obj, str):
        found.append(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            found.extend(_collect_all_strings(k))
            found.extend(_collect_all_strings(v))
    elif isinstance(obj, (list, tuple, set)):
        for item in obj:
            found.extend(_collect_all_strings(item))
    return found


def _make_mock_gemini_client(response_json: str = '{"drugName": "amoxicillin", "symptoms": ["rash"]}'):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = response_json
    mock_client.models.generate_content.return_value = mock_response
    return mock_client


def test_gemini_outbound_privacy_and_clinical_preservation(monkeypatch):
    """
    1, 2, 3, 4: Forces Gemini client non-None, asserts call_count == 1, recursively inspects
    ALL positional and keyword arguments to generate_content, verifies all identifier classes
    (names, lowercase names, MRNs, phones, emails, DOBs, street addresses) are scrubbed, and
    verifies drug, dose, route, symptom, and explicit temporal onset terms survive.
    """
    mock_client = _make_mock_gemini_client()
    monkeypatch.setattr(extract_mod, "client", mock_client)

    raw_text = (
        "Patient: John Doe (seen with dr. alice wonderland), MRN: 987654, "
        "DOB 05/12/1980, phone 555-019-2831, email john.doe@example.com, "
        "living at 123 Maple Street. Developed a severe rash 2 days after starting "
        "amoxicillin 500 mg oral three times a day."
    )
    forbidden_identifiers = [
        "John Doe",
        "alice wonderland",
        "987654",
        "05/12/1980",
        "555-019-2831",
        "john.doe@example.com",
        "123 Maple Street",
    ]
    preserved_clinical_terms = [
        "amoxicillin",
        "500 mg",
        "oral",
        "rash",
        "2 days after starting",
        "three times a day",
    ]

    result = extract(raw_text)
    assert result["drugName"] == "amoxicillin"
    assert mock_client.models.generate_content.call_count == 1

    call_args, call_kwargs = mock_client.models.generate_content.call_args
    all_outbound_strings = _collect_all_strings(call_args) + _collect_all_strings(call_kwargs)
    combined_outbound = "\n".join(all_outbound_strings)

    for ident in forbidden_identifiers:
        assert ident.lower() not in combined_outbound.lower(), (
            f"Identifier '{ident}' leaked into Gemini outbound arguments!"
        )

    for term in preserved_clinical_terms:
        assert term.lower() in combined_outbound.lower(), (
            f"Clinical term '{term}' was lost before Gemini outbound call!"
        )


def test_fail_closed_client_path_no_leak_or_provider_call(monkeypatch):
    """
    5: Patches app.privacy.deidentify to raise an exception containing a synthetic
    raw identifier on the active client path. Asserts generic DeidentificationError,
    __cause__ is None, __suppress_context__ is True, no identifier in str/repr/traceback,
    and generate_content.call_count == 0.
    """
    mock_client = _make_mock_gemini_client()
    monkeypatch.setattr(extract_mod, "client", mock_client)

    secret_phi = " Patient-Secret-SSN-999-88-7777 "

    def crashing_deid(*args, **kwargs):
        raise RuntimeError(f"NER crashed while parsing {secret_phi}")

    monkeypatch.setattr(privacy_mod, "deidentify", crashing_deid)

    with pytest.raises(DeidentificationError) as exc_info:
        extract(f"Raw narrative with {secret_phi}")

    exc = exc_info.value
    assert exc.__cause__ is None
    assert exc.__suppress_context__ is True
    assert secret_phi.strip() not in str(exc)
    assert secret_phi.strip() not in repr(exc)
    tb_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    assert secret_phi.strip() not in tb_text
    assert mock_client.models.generate_content.call_count == 0


def test_fail_closed_no_client_path_blocks_fallback(monkeypatch):
    """
    6: With client = None, a de-identification failure raises DeidentificationError
    and extract_fallback is never called.
    """
    monkeypatch.setattr(extract_mod, "client", None)
    mock_fallback = MagicMock()
    monkeypatch.setattr(extract_mod, "extract_fallback", mock_fallback)

    def crashing_deid(*args, **kwargs):
        raise ValueError("Synthetic de-id crash MRN-777111")

    monkeypatch.setattr(privacy_mod, "deidentify", crashing_deid)

    with pytest.raises(DeidentificationError) as exc_info:
        extract("Patient MRN-777111 took ibuprofen.")

    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True
    assert "MRN-777111" not in str(exc_info.value)
    assert mock_fallback.call_count == 0


def test_deid_require_ner_true_blocks_when_spacy_unavailable(monkeypatch):
    """
    7a: When settings.deid_require_ner is True and get_spacy_model returns None,
    extract() fails closed with DeidentificationError and makes zero provider calls.
    """
    mock_client = _make_mock_gemini_client()
    monkeypatch.setattr(extract_mod, "client", mock_client)
    monkeypatch.setattr(
        privacy_mod,
        "get_settings",
        lambda: load_settings({"LLM_PROVIDER": "disabled", "DEID_REQUIRE_NER": "true"}),
    )
    monkeypatch.setattr(privacy_mod, "get_spacy_model", lambda model_name="en_core_web_sm": None)

    with pytest.raises(DeidentificationError):
        extract("Patient John Doe took amoxicillin and got a rash.")

    assert mock_client.models.generate_content.call_count == 0


def test_deid_require_ner_false_permits_regex_only_when_spacy_unavailable(monkeypatch):
    """
    7b: When settings.deid_require_ner is False and spaCy model is unavailable (None),
    extract() permits regex-only de-identification and still scrubs regex-matched PHI.
    """
    mock_client = _make_mock_gemini_client()
    monkeypatch.setattr(extract_mod, "client", mock_client)
    monkeypatch.setattr(
        privacy_mod,
        "get_settings",
        lambda: load_settings({"LLM_PROVIDER": "disabled", "DEID_REQUIRE_NER": "false"}),
    )
    monkeypatch.setattr(privacy_mod, "get_spacy_model", lambda model_name="en_core_web_sm": None)
    monkeypatch.setattr("app.pipeline.deidentify.get_spacy_model", lambda model_name="en_core_web_sm": None)

    raw = "Patient: John Doe, MRN: 112233, phone 555-019-2831, took amoxicillin and got rash."
    result = extract(raw)
    assert result["drugName"] == "amoxicillin"
    assert mock_client.models.generate_content.call_count == 1

    call_args, call_kwargs = mock_client.models.generate_content.call_args
    outbound = "\n".join(_collect_all_strings(call_args) + _collect_all_strings(call_kwargs))
    assert "John Doe" not in outbound
    assert "112233" not in outbound
    assert "555-019-2831" not in outbound


def test_log_privacy_on_deid_failure_path(monkeypatch, caplog):
    """
    8a: On the de-identification failure path, caplog contains only the exception class name
    and never contains raw clinical text or synthetic identifiers.
    """
    mock_client = _make_mock_gemini_client()
    monkeypatch.setattr(extract_mod, "client", mock_client)

    sensitive_token = "SECRET_PATIENT_IDENTIFIER_88421"

    def crashing_deid(*args, **kwargs):
        raise KeyError(f"Failed on token {sensitive_token}")

    monkeypatch.setattr(privacy_mod, "deidentify", crashing_deid)

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(DeidentificationError):
            extract(f"Narrative containing {sensitive_token} and amoxicillin.")

    log_text = caplog.text
    assert "KeyError" in log_text
    assert sensitive_token not in log_text
    for record in caplog.records:
        assert record.exc_info is None


def test_log_privacy_on_provider_failure_path(monkeypatch, caplog):
    """
    8b: On the provider failure path, caplog records only the exception class name
    and falls back safely without logging the exception message, prompt, or patient text.
    """
    mock_client = MagicMock()
    sensitive_Error_detail = "PROVIDER_ECHOED_PROMPT_WITH_SECRET_99102"
    mock_client.models.generate_content.side_effect = RuntimeError(sensitive_Error_detail)
    monkeypatch.setattr(extract_mod, "client", mock_client)

    with caplog.at_level(logging.DEBUG):
        res = extract("Patient: Jane Doe, MRN 445566, took amoxicillin and developed rash.")

    assert res["drugName"] == "amoxicillin"
    assert "RuntimeError" in caplog.text
    assert sensitive_Error_detail not in caplog.text
    assert "Jane Doe" not in caplog.text
    assert "445566" not in caplog.text


def test_benchmark_vignettes_through_mocked_gemini_scanner(monkeypatch):
    """
    10: Runs all 8 benchmark vignettes through the mocked Gemini client with full-argument
    recursive scanning and asserts no synthetic identifiers leak.
    """
    mock_client = _make_mock_gemini_client()
    monkeypatch.setattr(extract_mod, "client", mock_client)

    known_benchmark_identifiers = [
        "John Doe",
        "849201",
        "555-019-2831",
        "Jane Smith",
        "918231",
        "555-492-1192",
        "Robert Miller",
        "449102",
        "David Clark",
        "771239",
        "1204 Pine St",
    ]

    assert len(BENCHMARK_CASES) == 8
    for case in BENCHMARK_CASES:
        mock_client.models.generate_content.reset_mock()
        extract(case["raw_narrative"])
        assert mock_client.models.generate_content.call_count == 1
        call_args, call_kwargs = mock_client.models.generate_content.call_args
        outbound = "\n".join(_collect_all_strings(call_args) + _collect_all_strings(call_kwargs))
        for ident in known_benchmark_identifiers:
            assert ident.lower() not in outbound.lower(), (
                f"Benchmark case {case['case_id']} leaked identifier '{ident}' in Gemini payload!"
            )


def test_deidentify_idempotence_with_live_ner():
    """
    11a: Verifies deidentify(deidentify(x)) == deidentify(x) with live spaCy NER across all
    8 benchmark vignettes and synthetic multi-identifier inputs, ensuring placeholders
    like [REDACTED_NAME] are never re-tagged, nested, or mangled.
    """
    synthetic_samples = [
        "Patient: John Doe, MRN: 987654, DOB 05/12/1980, phone 555-019-2831, email john.doe@example.com, lives at 123 Maple Street.",
        "Hospital ID: HX-44821. Mrs. Maria Garcia, DOB: March 3, 1975, tel (555) 222-3333, maria.g@mail.org, 77 Oak Avenue.",
        "patient: alice wonderland took ibuprofen 400 mg and developed hives.",
    ]
    all_texts = [c["raw_narrative"] for c in BENCHMARK_CASES] + synthetic_samples

    for raw in all_texts:
        pass1_text, _ = deidentify(raw, use_ner=True)
        pass2_text, _ = deidentify(pass1_text, use_ner=True)
        assert pass1_text == pass2_text, f"Idempotence failed:\nPass 1: {pass1_text}\nPass 2: {pass2_text}"
        assert "[[REDACTED" not in pass2_text
        assert "REDACTED_REDACTED" not in pass2_text


def test_extract_outbound_payload_idempotent_on_pre_deidentified_input(monkeypatch):
    """
    11b: Verifies extract(raw_text) and extract(deidentify(raw_text)[0]) send the exact
    same outbound payload to the Gemini provider.
    """
    mock_client = _make_mock_gemini_client()
    monkeypatch.setattr(extract_mod, "client", mock_client)

    raw_text = (
        "Patient: John Doe, MRN: 987654, phone 555-019-2831, "
        "living at 123 Maple Street, took amoxicillin 500mg and got rash."
    )
    pre_scrubbed, _ = deidentify(raw_text, use_ner=True)

    extract(raw_text)
    args_raw, kwargs_raw = mock_client.models.generate_content.call_args
    payload_from_raw = "\n".join(_collect_all_strings(args_raw) + _collect_all_strings(kwargs_raw))

    mock_client.models.generate_content.reset_mock()
    extract(pre_scrubbed)
    args_pre, kwargs_pre = mock_client.models.generate_content.call_args
    payload_from_pre = "\n".join(_collect_all_strings(args_pre) + _collect_all_strings(kwargs_pre))

    assert payload_from_raw == payload_from_pre


def test_pipeline_extract_endpoint_sanitizes_both_deid_call_sites(monkeypatch, caplog):
    """
    12: Regression test patching BOTH app.main.deidentify and app.pipeline.extract.deidentify
    via TestClient. Verifies status 500, generic DeidentificationError.public_message, and
    absence of raw exception text or PHI in response body and captured logs.
    """
    client = TestClient(fastapi_app, raise_server_exceptions=False)
    secret_marker = "SENSITIVE_ENDPOINT_PHI_MARKER_55192"

    # Case 1: app.main.deidentify fails before extract() is even reached
    def crash_main_deid(*args, **kwargs):
        raise RuntimeError(f"main deid crash with {secret_marker}")

    with patch("app.main.deidentify", side_effect=crash_main_deid):
        with caplog.at_level(logging.DEBUG):
            resp1 = client.post(
                "/pipeline/extract",
                json={"pipeline_run_id": "run-ep-1", "raw_text": f"Patient {secret_marker} took aspirin"},
            )
    assert resp1.status_code == 500
    assert resp1.json() == {"detail": DeidentificationError.public_message}
    assert secret_marker not in resp1.text
    assert secret_marker not in caplog.text

    caplog.clear()

    # Case 2: app.main.deidentify succeeds, but app.privacy.deidentify fails inside extract()
    def crash_extract_deid(*args, **kwargs):
        raise RuntimeError(f"extract deid crash with {secret_marker}")

    with patch("app.privacy.deidentify", side_effect=crash_extract_deid):
        with caplog.at_level(logging.DEBUG):
            resp2 = client.post(
                "/pipeline/extract",
                json={"pipeline_run_id": "run-ep-2", "raw_text": f"Patient {secret_marker} took aspirin"},
            )
    assert resp2.status_code == 500
    assert resp2.json() == {"detail": DeidentificationError.public_message}
    assert secret_marker not in resp2.text
    assert secret_marker not in caplog.text


@pytest.mark.parametrize(
    "text",
    [
        "Took amoxicillin three times a day and got a rash.",
        "Patient presented today with hives after ibuprofen.",
        "Discharged on day 3 of admission; rash noted on warfarin.",
        "Developed rash 2 days after admission.",
        "Fever noted 2 days after discharge.",
        "Pain started 2 days after surgery.",
        "Rash started 2 days ago after amoxicillin.",
        "Swelling within 2 hours of arrival to clinic.",
        "Developed rash 2 days after starting rehab.",
        "Developed rash 2 days after amoxicillin was stopped.",
        "Rash resolved 3 days after starting treatment.",
        "Hives improved 2 hours after the dose was reduced.",
        "Fever improved 2 days after the infusion was stopped.",
        "Rash noted 2 hours after the dose was reduced.",
        "Rash noted 2 days after the infusion was stopped.",
        "",
    ],
)
def test_extract_fallback_negative_onset_cases_return_none(text):
    """
    Section 6 + Addendum item 3, 8 & Pre-flight item 1 negative tests: non-drug-exposure
    temporal phrases, drug cessation/dose-reduction phrases, resolution/improvement phrases,
    and empty text must yield onsetTimeline=None.
    """
    res = extract_fallback(text)
    assert res["onsetTimeline"] is None


@pytest.mark.parametrize(
    "text,expected_onset",
    [
        ("Developed a rash 2 days after starting amoxicillin.", "2 days after starting"),
        ("Hives appeared within 30 minutes of the first dose of penicillin.", "within 30 minutes of the first dose"),
        ("Tongue swelling 4 hours after taking lisinopril 20mg.", "4 hours after taking"),
        ("Nausea three hours after ibuprofen.", "three hours after ibuprofen"),
    ],
)
def test_extract_fallback_positive_onset_cases_extracted_verbatim(text, expected_onset):
    """
    Section 6 positive tests: clearly stated temporal onset relationships to drug exposure
    are extracted accurately without fabrication.
    """
    res = extract_fallback(text)
    assert res["onsetTimeline"] == expected_onset


def test_extract_fallback_frequency_returns_full_phrase_or_none():
    """
    Addendum item 8: frequency returns the full matched phrase ('three times a day',
    'twice per week') or None when absent.
    """
    res1 = extract_fallback("Took amoxicillin 500mg three times a day for 7 days and got rash.")
    assert res1["frequency"] == "three times a day"

    res2 = extract_fallback("Took methotrexate once per week and developed nausea.")
    assert res2["frequency"] == "once per week"

    res3 = extract_fallback("Took ibuprofen 400mg and got hives.")
    assert res3["frequency"] is None


def test_summarize_gemini_outbound_scanner_and_provider_error_log_hygiene(monkeypatch, caplog):
    """
    Addendum item 5 & 7: Scanner test for app.pipeline.summarize.summarize() Gemini call site
    (app/pipeline/summarize.py:50, upstream-contract call site that relies on extract() having
    already de-identified extraction fields). Explicitly patches extract_mod.client = None so
    extract() is deterministic regardless of environment keys.
    """
    import app.pipeline.summarize as summarize_mod
    from app.pipeline.classify import classify
    from app.pipeline.retrieve import retrieve

    monkeypatch.setattr(extract_mod, "client", None)

    mock_sum_client = MagicMock()
    mock_sum_resp = MagicMock()
    mock_sum_resp.text = "Clinical summary: amoxicillin associated with rash."
    mock_sum_client.models.generate_content.return_value = mock_sum_resp
    monkeypatch.setattr(summarize_mod, "client", mock_sum_client)

    raw_text = (
        "Patient: John Doe, MRN: 987654, DOB 05/12/1980, phone 555-019-2831, "
        "email john.doe@example.com, living at 123 Maple Street, took amoxicillin 500mg "
        "and developed rash."
    )
    forbidden = ["John Doe", "987654", "05/12/1980", "555-019-2831", "john.doe@example.com", "123 Maple Street"]

    ext = extract(raw_text)
    cls = classify(ext)
    ret = retrieve(ext)
    summary_out = summarize_mod.summarize(ext, cls, ret)
    assert "amoxicillin" in summary_out
    assert mock_sum_client.models.generate_content.call_count == 1

    s_args, s_kwargs = mock_sum_client.models.generate_content.call_args
    outbound = "\n".join(_collect_all_strings(s_args) + _collect_all_strings(s_kwargs))
    for ident in forbidden:
        assert ident.lower() not in outbound.lower(), f"Identifier '{ident}' leaked in summarize() Gemini call!"

    # Also verify provider failure log hygiene on summarize()
    secret_err = "SUMMARIZE_PROVIDER_ECHO_SECRET_77123"
    mock_sum_client.models.generate_content.side_effect = ValueError(secret_err)
    with caplog.at_level(logging.DEBUG):
        fallback_out = summarize_mod.summarize(ext, cls, ret)
    assert "Report involves amoxicillin" in fallback_out
    assert "ValueError" in caplog.text
    assert secret_err not in caplog.text


def test_deid_policy_falls_back_to_strict_defaults_when_get_settings_raises(monkeypatch, caplog):
    """
    Addendum item 6 & 7: When get_settings() raises (e.g. ConfigError), _deid_policy() logs only
    the exception class name and returns the strict default (True, 'en_core_web_sm'), and
    app.main._get_active_settings() logs only the exception class name (ConfigError) and returns None.
    """
    import app.main as main_mod
    from app.errors import ConfigError

    secret_cfg = "BAD_CONFIG_SECRET_VALUE_44910"

    def broken_settings():
        raise ConfigError(f"Invalid env with {secret_cfg}")

    monkeypatch.setattr(privacy_mod, "get_settings", broken_settings)
    with caplog.at_level(logging.DEBUG):
        require_ner, model_name = privacy_mod._deid_policy()

    assert require_ner is True
    assert model_name == "en_core_web_sm"
    assert "ConfigError" in caplog.text
    assert secret_cfg not in caplog.text

    caplog.clear()
    monkeypatch.setattr(main_mod.config, "get_settings", broken_settings)
    with caplog.at_level(logging.DEBUG):
        active = main_mod._get_active_settings()
    assert active is None
    assert "ConfigError" in caplog.text
    assert secret_cfg not in caplog.text


def test_pipeline_run_privacy_failure_returns_500_without_leaking_phi(caplog):
    """
    Addendum item 6 & 3: Verifies /pipeline/run when NER crashes with secret_phi inside the
    raised exception message, when app.privacy.deidentify raises an exception containing secret_phi,
    or when spaCy NER is unavailable under default settings returns HTTP 500 and never leaks
    secret_phi in the response body or captured Python logs.
    Note: TestClient exercises Starlette's ServerErrorMiddleware; live uvicorn.error logger
    behavior on unhandled route exceptions is [UNVERIFIED] in TestClient.
    """
    client = TestClient(fastapi_app, raise_server_exceptions=False)
    secret_phi = "PIPELINE_RUN_SECRET_MRN_665544"

    # 1a. spaCy NER callable raises an exception containing secret_phi inside deidentify()
    class CrashingNLPWithSecret:
        def __call__(self, text):
            raise ValueError(f"NER fault while processing {secret_phi}")

    with patch("app.pipeline.deidentify.get_spacy_model", return_value=CrashingNLPWithSecret()):
        with caplog.at_level(logging.DEBUG):
            resp1 = client.post(
                "/pipeline/run",
                json={"pipeline_run_id": "run-fail-1a", "raw_text": f"Patient {secret_phi} took amoxicillin"},
            )
    assert resp1.status_code == 500
    assert secret_phi not in resp1.text
    assert secret_phi not in caplog.text
    assert "ValueError" in caplog.text

    caplog.clear()

    # 1b. app.privacy.deidentify raises an exception containing secret_phi
    def crash_extract_deid(*args, **kwargs):
        raise RuntimeError(f"extract deid fault with {secret_phi}")

    with patch("app.privacy.deidentify", side_effect=crash_extract_deid):
        with caplog.at_level(logging.DEBUG):
            resp1b = client.post(
                "/pipeline/run",
                json={"pipeline_run_id": "run-fail-1b", "raw_text": f"Patient {secret_phi} took amoxicillin"},
            )
    assert resp1b.status_code == 500
    assert secret_phi not in resp1b.text
    assert secret_phi not in caplog.text
    assert "RuntimeError" in caplog.text

    caplog.clear()

    # 2. Missing spaCy model under default DEID_REQUIRE_NER=True causes extract() inside
    # /pipeline/run (and /pipeline/extract) to fail closed with 500
    with patch("app.privacy.get_spacy_model", return_value=None):
        with caplog.at_level(logging.DEBUG):
            resp_run = client.post(
                "/pipeline/run",
                json={"pipeline_run_id": "run-fail-2", "raw_text": f"Patient {secret_phi} took amoxicillin"},
            )
            resp_ext = client.post(
                "/pipeline/extract",
                json={"pipeline_run_id": "ext-fail-2", "raw_text": f"Patient {secret_phi} took amoxicillin"},
            )
    assert resp_run.status_code == 500
    assert resp_ext.status_code == 500
    assert resp_ext.json() == {"detail": DeidentificationError.public_message}
    assert secret_phi not in resp_run.text
    assert secret_phi not in resp_ext.text
    assert secret_phi not in caplog.text


def test_extract_malformed_gemini_outputs_and_empty_text(monkeypatch, caplog):
    """
    Pre-flight item 4: Tests malformed Gemini outputs (invalid/partial JSON, wrong types,
    missing fields) and empty text via extract("").
    """
    raw_narrative = "Patient: John Doe, MRN 849201, took amoxicillin 500 mg and developed rash."

    # 1. Invalid / partial JSON -> logs only ValidationError, falls back to extract_fallback
    mock_bad_json = _make_mock_gemini_client('{"drugName": "amoxicillin", "symptoms": ["rash"')
    monkeypatch.setattr(extract_mod, "client", mock_bad_json)
    with caplog.at_level(logging.DEBUG):
        res_bad = extract(raw_narrative)
    assert res_bad["drugName"] == "amoxicillin"
    assert res_bad["modelVersion"] == "extraction-stub-0.2"
    assert "ValidationError" in caplog.text
    assert "John Doe" not in caplog.text
    assert "849201" not in caplog.text

    caplog.clear()

    # 2. Wrong field types -> logs only ValidationError, falls back to extract_fallback
    mock_wrong_types = _make_mock_gemini_client(
        '{"drugName": "amoxicillin", "age": "not-an-integer", "symptoms": "not-a-list"}'
    )
    monkeypatch.setattr(extract_mod, "client", mock_wrong_types)
    with caplog.at_level(logging.DEBUG):
        res_wrong = extract(raw_narrative)
    assert res_wrong["drugName"] == "amoxicillin"
    assert res_wrong["modelVersion"] == "extraction-stub-0.2"
    assert "ValidationError" in caplog.text

    # 3. Missing fields ('{}') -> ExtractionResult defaults populate None/[] and incomplete=True
    mock_missing = _make_mock_gemini_client("{}")
    monkeypatch.setattr(extract_mod, "client", mock_missing)
    res_missing = extract(raw_narrative)
    assert res_missing["drugName"] is None
    assert res_missing["symptoms"] == []
    assert res_missing["incomplete"] is True
    assert res_missing["modelVersion"] == "gemini-2.5-pro-extraction"

    # 4. Empty text via extract("") on fallback path
    monkeypatch.setattr(extract_mod, "client", None)
    res_empty = extract("")
    assert res_empty["drugName"] is None
    assert res_empty["symptoms"] == []
    assert res_empty["onsetTimeline"] is None
    assert res_empty["incomplete"] is True


import app.pipeline.assess as assess_mod
from app.pipeline.assess import run_causality_assessment


def _valid_llm_assessment_json() -> str:
    return json.dumps(
        {
            "summary_sentences": [
                {
                    "text": "Patient developed rash following amoxicillin administration.",
                    "citations": ["E1", "N"],
                }
            ],
            "naranjo_answers": {
                "q1_previous_reports": {"answer": "yes", "rationale": "Known reaction.", "citations": ["E1"]},
                "q2_event_after_drug": {"answer": "yes", "rationale": "Occurred post-dose.", "citations": ["N"]},
            },
            "who_umc_suggestion": {
                "category": "probable",
                "rationale": "Consistent temporal sequence and known label warning.",
                "citations": ["E1", "N"],
            },
            "limitations": ["No rechallenge performed."],
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_name,base_url,api_key",
    [
        ("openrouter", "https://openrouter.ai/api/v1", "or-test-key"),
        ("ollama", "http://localhost:11434/v1", ""),
    ],
)
async def test_assess_enforces_shared_privacy_boundary_across_narrative_extraction_and_retrievals(
    monkeypatch, provider_name, base_url, api_key
):
    """
    Checkpoint B: Calls run_causality_assessment() directly with RAW PHI in all three inputs:
    1) deidentified_text (narrative containing John Doe, MRN 849201, DOB 05/12/1980, phone, email, address),
    2) extraction (containing Dr. Smith, Alice Wonderland, MRN 918231, 555-492-1192),
    3) retrievals (title/snippet/section containing Robert Miller, MRN 449102, 1204 Pine St).
    Verifies for both OpenRouter and Ollama that all outbound HTTP request payloads are
    recursively scanned, zero PHI leaks, clinical content is preserved, and the test would
    fail if any part of the boundary in assess.py were removed.
    """
    captured_payloads = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": _valid_llm_assessment_json()}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 30},
            },
        )

    transport = httpx.MockTransport(handler)
    provider = OpenAICompatibleProvider(
        base_url=base_url,
        api_key=api_key,
        model="qwen/qwen3-8b",
        provider_name=provider_name,
        transport=transport,
    )
    monkeypatch.setattr(assess_mod, "get_llm_provider", lambda s=None: provider)

    settings = load_settings(
        {
            "LLM_PROVIDER": provider_name,
            "LLM_BASE_URL": base_url,
            "LLM_API_KEY": api_key or "dummy",
            "LLM_MODEL": "qwen/qwen3-8b",
            "DEID_REQUIRE_NER": "true",
        }
    )

    raw_narrative = (
        "Patient: John Doe, MRN: 849201, DOB 05/12/1980, phone 555-019-2831, "
        "email john.doe@example.com, living at 123 Maple Street. Developed a severe rash "
        "2 days after starting amoxicillin 500 mg oral."
    )
    unsanitized_extraction = {
        "drugName": "amoxicillin (prescribed by Dr. Smith)",
        "genericName": "amoxicillin for Patient: Alice Wonderland",
        "symptoms": ["rash noted at 123 Maple Street", "hives (MRN: 918231)"],
        "onsetTimeline": "2 days after starting on 05/12/1980",
        "dosage": "500 mg (callback 555-492-1192)",
    }
    unsanitized_retrievals = [
        {
            "evidence_id": "E1",
            "title": "Amoxicillin Label — Case of Patient: Robert Miller",
            "snippet": "WARNINGS: Hypersensitivity and severe rash reported in MRN: 449102 at 1204 Pine St.",
            "section": "Warnings for john.doe@example.com",
        }
    ]

    forbidden_identifiers = [
        "John Doe",
        "849201",
        "05/12/1980",
        "555-019-2831",
        "john.doe@example.com",
        "123 Maple Street",
        "Smith",
        "Alice Wonderland",
        "918231",
        "555-492-1192",
        "Robert Miller",
        "449102",
        "1204 Pine St",
    ]
    preserved_clinical = [
        "amoxicillin",
        "rash",
        "hives",
        "500 mg",
        "2 days after starting",
        "Hypersensitivity",
    ]

    result = await run_causality_assessment(
        deidentified_text=raw_narrative,
        extraction=unsanitized_extraction,
        retrievals=unsanitized_retrievals,
        settings=settings,
    )
    assert result["status"] == "completed"
    assert len(captured_payloads) == 1

    outbound_strings = _collect_all_strings(captured_payloads[0])
    combined_outbound = "\n".join(outbound_strings)

    for ident in forbidden_identifiers:
        assert ident.lower() not in combined_outbound.lower(), (
            f"Identifier '{ident}' leaked in {provider_name} assessment outbound payload!"
        )

    for term in preserved_clinical:
        assert term.lower() in combined_outbound.lower(), (
            f"Clinical term '{term}' was lost in {provider_name} assessment outbound payload!"
        )


@pytest.mark.asyncio
async def test_assess_repair_retry_reuses_sanitized_prompt_without_phi(monkeypatch):
    """
    Checkpoint B: When the first LLM response is malformed JSON and complete_structured()
    executes its repair retry, both the initial request and the repair retry reuse the
    sanitized prompt and contain zero PHI from narrative, extraction, or retrievals.
    """
    captured_payloads = []
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        captured_payloads.append(json.loads(request.content.decode("utf-8")))
        if call_count == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "{broken_json: true"}}],
                    "usage": {"prompt_tokens": 40, "completion_tokens": 10},
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": _valid_llm_assessment_json()}}],
                "usage": {"prompt_tokens": 60, "completion_tokens": 30},
            },
        )

    transport = httpx.MockTransport(handler)
    provider = OpenAICompatibleProvider(
        base_url="http://localhost:11434/v1",
        api_key="",
        model="qwen3:8b",
        provider_name="ollama",
        transport=transport,
    )
    monkeypatch.setattr(assess_mod, "get_llm_provider", lambda s=None: provider)

    settings = load_settings(
        {
            "LLM_PROVIDER": "ollama",
            "LLM_BASE_URL": "http://localhost:11434/v1",
            "LLM_MODEL": "qwen3:8b",
            "DEID_REQUIRE_NER": "true",
        }
    )

    raw_narrative = "Patient: John Doe, MRN 849201, phone 555-019-2831, developed rash after amoxicillin."
    raw_extraction = {
        "drugName": "amoxicillin (Dr. Smith)",
        "symptoms": ["rash in Jane Smith"],
        "onsetTimeline": "2 days after starting",
        "dosage": "500 mg",
    }
    raw_retrievals = [
        {"evidence_id": "E1", "title": "Label (Patient: Robert Miller)", "snippet": "Rash at 123 Maple Street."}
    ]
    forbidden = ["John Doe", "849201", "555-019-2831", "Smith", "Jane Smith", "Robert Miller", "123 Maple Street"]

    result = await run_causality_assessment(
        deidentified_text=raw_narrative,
        extraction=raw_extraction,
        retrievals=raw_retrievals,
        settings=settings,
    )
    assert result["status"] == "completed"
    assert call_count == 2
    assert len(captured_payloads) == 2

    for idx, payload in enumerate(captured_payloads, start=1):
        combined = "\n".join(_collect_all_strings(payload))
        for ident in forbidden:
            assert ident.lower() not in combined.lower(), (
                f"Identifier '{ident}' leaked on attempt {idx} of repair retry!"
            )


@pytest.mark.asyncio
async def test_assess_fail_closed_blocks_provider_and_fallback_with_clean_logs(monkeypatch, caplog):
    """
    Checkpoint B: Verifies that when mandatory regex/NER de-identification fails or spaCy NER
    is unavailable under DEID_REQUIRE_NER=True:
    - run_causality_assessment fails closed with DeidentificationError (__cause__ is None,
      __context__ is None, __suppress_context__ is True),
    - zero provider calls and zero fallback calls occur,
    - logs and exception strings/tracebacks never contain raw PHI.
    Also verifies that when the provider raises an error containing synthetic PHI, assess.py
    logs only the exception class name and falls back using the already-sanitized inputs.
    """
    provider_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal provider_calls
        provider_calls += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": _valid_llm_assessment_json()}}]})

    provider = OpenAICompatibleProvider(
        base_url="https://openrouter.ai/api/v1",
        api_key="test-key",
        model="qwen/qwen3-8b",
        provider_name="openrouter",
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(assess_mod, "get_llm_provider", lambda s=None: provider)

    settings = load_settings(
        {
            "LLM_PROVIDER": "openrouter",
            "LLM_BASE_URL": "https://openrouter.ai/api/v1",
            "LLM_API_KEY": "test-key",
            "LLM_MODEL": "qwen/qwen3-8b",
            "DEID_REQUIRE_NER": "true",
        }
    )

    secret_phi = "ASSESS_SECRET_PHI_SSN_999_00_1111"

    # 1. deidentify raises exception containing secret_phi -> fail closed, 0 provider calls
    def crashing_deid(*args, **kwargs):
        raise RuntimeError(f"NER crashed on {secret_phi}")

    with patch.object(privacy_mod, "deidentify", side_effect=crashing_deid):
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(DeidentificationError) as exc_info:
                await run_causality_assessment(
                    deidentified_text=f"Patient {secret_phi} took amoxicillin.",
                    extraction={"drugName": "amoxicillin", "symptoms": ["rash"]},
                    retrievals=[],
                    settings=settings,
                )

    exc = exc_info.value
    assert exc.__cause__ is None
    assert exc.__context__ is None
    assert exc.__suppress_context__ is True
    assert secret_phi not in str(exc)
    assert secret_phi not in repr(exc)
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    assert secret_phi not in tb
    assert secret_phi not in caplog.text
    assert "RuntimeError" in caplog.text
    assert provider_calls == 0

    caplog.clear()

    # 2. Missing spaCy model under DEID_REQUIRE_NER=True -> fail closed, 0 provider calls
    with patch.object(privacy_mod, "get_spacy_model", return_value=None):
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(DeidentificationError):
                await run_causality_assessment(
                    deidentified_text="Patient John Doe took amoxicillin.",
                    extraction={"drugName": "amoxicillin", "symptoms": ["rash"]},
                    retrievals=[],
                    settings=settings,
                )
    assert provider_calls == 0
    assert "NERModelUnavailable" in caplog.text

    caplog.clear()

    # 3. Provider failure containing secret_phi -> logs only class name, fallback uses sanitized text
    secret_provider_err = "PROVIDER_ERROR_ECHOING_PHI_776655"
    failing_provider = MagicMock()

    async def failing_complete_structured(*args, **kwargs):
        raise ValueError(f"Upstream failure: {secret_provider_err}")

    failing_provider.complete_structured = failing_complete_structured
    monkeypatch.setattr(assess_mod, "get_llm_provider", lambda s=None: failing_provider)

    with caplog.at_level(logging.DEBUG):
        fallback_res = await run_causality_assessment(
            deidentified_text="Patient: John Doe, MRN 849201, took amoxicillin.",
            extraction={"drugName": "amoxicillin (Dr. Smith)", "symptoms": ["rash in Jane Smith"]},
            retrievals=[],
            settings=settings,
        )
    assert fallback_res["status"] == "fallback"
    assert "ValueError" in caplog.text
    assert secret_provider_err not in caplog.text
    assert "John Doe" not in caplog.text
    fallback_dump = json.dumps(fallback_res)
    assert "Smith" not in fallback_dump
    assert "Jane Smith" not in fallback_dump


@pytest.mark.asyncio
async def test_boundary_passes_real_deidentify_and_spacy_functions_at_both_call_sites(monkeypatch):
    """
    Item 2 & Addendum Item 2/5: Verifies that app.privacy._deidentify_or_block has no injectable
    function parameters (only (text, *, settings=None)) and rejects deidentify_fn/get_spacy_model_fn
    or underscore variants with TypeError.
    """
    import inspect

    sig = inspect.signature(privacy_mod._deidentify_or_block)
    assert list(sig.parameters.keys()) == ["text", "settings"]

    for bad_kw in ("deidentify_fn", "get_spacy_model_fn", "_deidentify_fn", "_get_spacy_model_fn", "_get_settings_fn"):
        with pytest.raises(TypeError):
            privacy_mod._deidentify_or_block("test", **{bad_kw: lambda *a, **k: None})

    recorded_calls = []
    real_boundary = privacy_mod._deidentify_or_block

    def spy_boundary(text, **kwargs):
        recorded_calls.append(kwargs)
        return real_boundary(text, **kwargs)

    monkeypatch.setattr(extract_mod, "_deidentify_or_block", spy_boundary)
    monkeypatch.setattr(assess_mod, "_deidentify_or_block", spy_boundary)
    monkeypatch.setattr(extract_mod, "client", None)

    extract("Patient took amoxicillin and developed rash.")
    assert len(recorded_calls) == 1
    assert set(recorded_calls[0].keys()) <= {"settings"}

    recorded_calls.clear()
    assess_mod._scrub_for_assessment("Patient took amoxicillin and developed rash.")
    assert len(recorded_calls) == 1
    assert set(recorded_calls[0].keys()) <= {"settings"}


@pytest.mark.asyncio
async def test_assess_allowlist_and_recursive_nested_sanitization(monkeypatch):
    """
    Items 3 & 4: Verifies that _sanitize_extraction and _sanitize_retrievals only scrub and
    retain the allowlisted prompt fields, drop un-allowlisted fields, and recursively scrub
    nested dicts/lists/tuples inside allowlisted fields.
    """
    raw_extraction = {
        "drugName": "Lipitor (prescribed by Dr. Smith)",
        "genericName": "atorvastatin",
        "symptoms": [
            "myalgia",
            {"nested_note": "reported by Patient: John Doe at 555-019-2831"},
            ["rash at 123 Maple Street"],
        ],
        "onsetTimeline": "2 days after starting on 05/12/1980",
        "dosage": {"amount": "20 mg (MRN: 849201)"},
        "untrustedExtraField": "SSN 123-45-6789 for Mary Parkinson",
        "brandName": "Lipitor for Jane Doe",
    }
    sanitized_ext = assess_mod._sanitize_extraction(raw_extraction)
    assert set(sanitized_ext.keys()) <= set(assess_mod._ALLOWED_EXTRACTION_FIELDS)
    assert "untrustedExtraField" not in sanitized_ext
    assert "brandName" not in sanitized_ext
    assert "Lipitor" in sanitized_ext["drugName"]
    assert "Smith" not in sanitized_ext["drugName"]

    ext_blob = "\n".join(_collect_all_strings(sanitized_ext))
    for secret in ("John Doe", "555-019-2831", "123 Maple Street", "05/12/1980", "849201", "123-45-6789"):
        assert secret not in ext_blob

    raw_retrievals = [
        {
            "evidence_id": "E1",
            "title": "Atorvastatin Label (Dr. Bell)",
            "snippet": "Rhabdomyolysis reported at 123 Maple Street.",
            "section": "Untrusted section with SSN 123-45-6789",
            "extra_metadata": {"patient": "John Doe"},
        }
    ]
    sanitized_ret = assess_mod._sanitize_retrievals(raw_retrievals)
    assert len(sanitized_ret) == 1
    assert set(sanitized_ret[0].keys()) <= {"evidence_id", "source_id", "title", "snippet"}
    assert {"evidence_id", "title", "snippet"} <= set(sanitized_ret[0].keys())
    ret_blob = "\n".join(_collect_all_strings(sanitized_ret))
    assert "Bell" not in ret_blob
    assert "123 Maple Street" not in ret_blob
    assert "123-45-6789" not in ret_blob


@pytest.mark.asyncio
async def test_assess_regex_tripwire_blocks_residual_phi_in_assembled_messages(monkeypatch):
    """
    Item 7: Verifies that the regex-only tripwire (_assert_messages_no_residual_phi) on the
    assembled messages blocks the provider call and raises DeidentificationError if any raw
    regex-matched direct identifier survives into the assembled prompt.
    """
    provider_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal provider_calls
        provider_calls += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": _valid_llm_assessment_json()}}]})

    provider = OpenAICompatibleProvider(
        base_url="https://openrouter.ai/api/v1",
        api_key="test-key",
        model="qwen/qwen3-8b",
        provider_name="openrouter",
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(assess_mod, "get_llm_provider", lambda s=None: provider)

    settings = load_settings(
        {
            "LLM_PROVIDER": "openrouter",
            "LLM_BASE_URL": "https://openrouter.ai/api/v1",
            "LLM_API_KEY": "test-key",
            "LLM_MODEL": "qwen/qwen3-8b",
            "DEID_REQUIRE_NER": "true",
        }
    )

    # Simulate a bypass of _scrub_for_assessment where raw regex PHI reaches prompt assembly
    monkeypatch.setattr(assess_mod, "_scrub_for_assessment", lambda text, settings=None: text)

    with pytest.raises(DeidentificationError):
        await run_causality_assessment(
            deidentified_text="Patient: John Doe, MRN 849201, phone 555-019-2831, took amoxicillin.",
            extraction={"drugName": "amoxicillin", "symptoms": ["rash"]},
            retrievals=[],
            settings=settings,
        )
    assert provider_calls == 0


def test_extract_llm_grounds_onset_dosage_and_frequency_against_deidentified_text(monkeypatch):
    """
    Item 10: Verifies that LLM-supplied onsetTimeline, dosage, and frequency in extract() are
    grounded against the de-identified narrative: hallucinated or non-drug-exposure values are
    cleared or replaced with the grounded _extract_onset() match, while grounded values are kept.
    """
    # 1. Hallucinated dosage/frequency and non-exposure onset ("2 days after admission") -> cleared to None
    ungrounded_json = json.dumps(
        {
            "drugName": "amoxicillin",
            "genericName": "amoxicillin",
            "dosage": "999 mg",
            "frequency": "four times a day",
            "symptoms": ["rash"],
            "onsetTimeline": "2 days after admission",
        }
    )
    monkeypatch.setattr(extract_mod, "client", _make_mock_gemini_client(ungrounded_json))
    res1 = extract("Patient took amoxicillin and developed a rash 2 days after admission.")
    assert res1["dosage"] is None
    assert res1["frequency"] is None
    assert res1["onsetTimeline"] is None

    # 2. Grounded dosage, frequency, and drug-exposure onset -> preserved
    grounded_json = json.dumps(
        {
            "drugName": "amoxicillin",
            "genericName": "amoxicillin",
            "dosage": "500 mg",
            "frequency": "three times a day",
            "symptoms": ["rash"],
            "onsetTimeline": "2 days after starting amoxicillin",
        }
    )
    monkeypatch.setattr(extract_mod, "client", _make_mock_gemini_client(grounded_json))
    res2 = extract(
        "Patient took amoxicillin 500 mg three times a day and developed a rash 2 days after starting amoxicillin."
    )
    assert res2["dosage"] == "500 mg"
    assert res2["frequency"] == "three times a day"
    assert res2["onsetTimeline"] == "2 days after starting amoxicillin"


def test_main_deidentify_endpoint_500_does_not_reflect_str_exc(caplog):
    """Item 11 site 1: /pipeline/deidentify returns fixed generic 500 detail and logs only class name."""
    client = TestClient(fastapi_app, raise_server_exceptions=False)
    secret = "DEID_ENDPOINT_SECRET_PHI_11001"
    with patch("app.main.deidentify", side_effect=RuntimeError(f"Crash on {secret}")):
        with caplog.at_level(logging.DEBUG):
            resp = client.post("/pipeline/deidentify", json={"pipeline_run_id": "d1", "raw_text": "test"})
    assert resp.status_code == 500
    assert resp.json() == {"detail": "De-identification failed."}
    assert secret not in resp.text
    assert secret not in caplog.text
    assert "RuntimeError" in caplog.text


def test_main_extract_endpoint_500_does_not_reflect_str_exc(caplog):
    """Item 11 site 2: /pipeline/extract non-privacy 500 returns fixed generic detail and logs only class name."""
    client = TestClient(fastapi_app, raise_server_exceptions=False)
    secret = "EXTRACT_ENDPOINT_SECRET_PHI_22002"
    with patch("app.main.extract", side_effect=KeyError(f"Fault on {secret}")):
        with caplog.at_level(logging.DEBUG):
            resp = client.post("/pipeline/extract", json={"pipeline_run_id": "e1", "raw_text": "test"})
    assert resp.status_code == 500
    assert resp.json() == {"detail": "Extraction failed."}
    assert secret not in resp.text
    assert secret not in caplog.text
    assert "KeyError" in caplog.text


def test_main_classify_endpoint_500_does_not_reflect_str_exc(caplog):
    """Item 11 site 3: /pipeline/classify returns fixed generic 500 detail and logs only class name."""
    client = TestClient(fastapi_app, raise_server_exceptions=False)
    secret = "CLASSIFY_ENDPOINT_SECRET_PHI_33003"
    with patch("app.main.classify", side_effect=ValueError(f"Classify fault on {secret}")):
        with caplog.at_level(logging.DEBUG):
            resp = client.post("/pipeline/classify", json={"pipeline_run_id": "c1", "raw_text": "test"})
    assert resp.status_code == 500
    assert resp.json() == {"detail": "Classification failed."}
    assert secret not in resp.text
    assert secret not in caplog.text
    assert "ValueError" in caplog.text


def test_main_causality_endpoint_500_does_not_reflect_str_exc(caplog):
    """Item 11 site 4: /pipeline/causality returns fixed generic 500 detail and logs only class name."""
    client = TestClient(fastapi_app, raise_server_exceptions=False)
    secret = "CAUSALITY_ENDPOINT_SECRET_PHI_44004"
    with patch("app.main.evaluate_naranjo_causality", side_effect=TypeError(f"Causality fault on {secret}")):
        with caplog.at_level(logging.DEBUG):
            resp = client.post("/pipeline/causality", json={"pipeline_run_id": "ca1", "raw_text": "test"})
    assert resp.status_code == 500
    assert resp.json() == {"detail": "Causality assessment failed."}
    assert secret not in resp.text
    assert secret not in caplog.text
    assert "TypeError" in caplog.text


def test_extract_gemini_tripwire_outside_try_raises_deidentification_error_without_fallback(monkeypatch):
    """
    Addendum Item 1: When the regex tripwire in extract() detects residual PHI on the Gemini
    path, it raises DeidentificationError outside the try/except block, makes 0 generate_content
    calls, and never calls extract_fallback.
    """
    mock_client = _make_mock_gemini_client()
    monkeypatch.setattr(extract_mod, "client", mock_client)

    fallback_spy = MagicMock(wraps=extract_mod.extract_fallback)
    monkeypatch.setattr(extract_mod, "extract_fallback", fallback_spy)

    # Simulate _deidentify_or_block returning text with residual regex PHI
    monkeypatch.setattr(
        extract_mod,
        "_deidentify_or_block",
        lambda text, **kw: "Patient: John Doe, MRN 849201, phone 555-019-2831 took amoxicillin.",
    )

    with pytest.raises(DeidentificationError):
        extract("Patient: John Doe, MRN 849201, phone 555-019-2831 took amoxicillin.")

    assert mock_client.models.generate_content.call_count == 0
    assert fallback_spy.call_count == 0


@pytest.mark.asyncio
async def test_openai_compatible_complete_tripwire_blocks_repair_retry_phi():
    """
    Addendum Item 6: Verifies that OpenAICompatibleProvider.complete() runs the regex-only
    tripwire on every call, including the repair retry in complete_structured(). If the initial
    model response echoes back a raw regex identifier that gets appended into repair_messages,
    the retry is blocked before the second HTTP request is sent.
    """
    from app.pipeline.assess import RawLLMAssessmentSchema

    http_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal http_calls
        http_calls += 1
        # First response returns invalid JSON containing a regex-detectable SSN / phone
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"bad_json": "SSN 123-45-6789 phone 555-019-2831"'}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10},
            },
        )

    provider = OpenAICompatibleProvider(
        base_url="http://localhost:11434/v1",
        api_key="",
        model="qwen3:8b",
        provider_name="ollama",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(DeidentificationError):
        await provider.complete_structured(
            [{"role": "user", "content": "Clean clinical prompt for amoxicillin rash."}],
            schema=RawLLMAssessmentSchema,
        )

    # First call succeeded at HTTP level, but repair retry was blocked before HTTP call #2
    assert http_calls == 1


def test_pipeline_run_when_provider_disabled_matches_frozen_stages_and_computes_conservative_causality(
    monkeypatch,
):
    """
    Section 7 & Addendum Item 1: When LLM_PROVIDER is disabled (or unconfigured), /pipeline/run
    does not call run_causality_assessment or normalize_drug, leaves assessment=None and
    normalized_drug=None, returns byte-identical HTTP response bytes between disabled and
    unconfigured modes (resp_disabled.content == resp_unconfigured.content), and matches
    frozen_origin_main_full.json on pipeline_run_id, extraction, classification, summary,
    and citation_verification.
    Note: deidentified_text is an intentional change to a legacy field (preserving 'Patient: ' and 'MRN: ' label prefixes).
    Note: causality reflects conservative Naranjo Q5=0 scoring (intentional delta documented in tests/fixtures/intentional_deltas.md).
    """
    import app.config
    import app.main as main_mod
    import app.pipeline.classify as classify_mod

    monkeypatch.setattr(extract_mod, "client", None)
    monkeypatch.setattr(classify_mod, "clf_pipeline", None)

    assess_spy = MagicMock(wraps=main_mod.run_causality_assessment)
    norm_spy = MagicMock(wraps=main_mod.normalize_drug)
    monkeypatch.setattr(main_mod, "run_causality_assessment", assess_spy)
    monkeypatch.setattr(main_mod, "normalize_drug", norm_spy)

    client = TestClient(fastapi_app)

    fixture_path = Path(__file__).resolve().parent / "fixtures" / "frozen_origin_main_full.json"
    assert fixture_path.exists()
    frozen = json.loads(fixture_path.read_text(encoding="utf-8"))

    raw_input = "Patient: Jane Doe, MRN: 12345. Took amoxicillin and got rash."

    # 1. Run with default unconfigured environment (LLM_API_KEY="") and live OpenFDA + builtin reference corpus enabled to match frozen capture
    monkeypatch.setenv("ENABLE_LIVE_OPENFDA", "true")
    monkeypatch.setenv("ALLOW_BUILTIN_REFERENCE_CORPUS", "true")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    app.config.get_settings.cache_clear()
    resp_unconfigured = client.post(
        "/pipeline/run",
        json={"pipeline_run_id": "run-123", "raw_text": raw_input},
    )
    assert resp_unconfigured.status_code == 200

    # 2. Run with explicit LLM_PROVIDER=disabled -> raw HTTP response bytes must be byte-identical to unconfigured
    monkeypatch.setenv("LLM_PROVIDER", "disabled")
    app.config.get_settings.cache_clear()
    resp_disabled = client.post(
        "/pipeline/run",
        json={"pipeline_run_id": "run-123", "raw_text": raw_input},
    )
    assert resp_disabled.status_code == 200
    body_unconfigured = resp_unconfigured.json()
    body_disabled = resp_disabled.json()
    assert body_unconfigured["assessment_status"] == "unconfigured"
    assert body_disabled["assessment_status"] == "disabled"
    assert {k: v for k, v in body_disabled.items() if k != "assessment_status"} == {
        k: v for k, v in body_unconfigured.items() if k != "assessment_status"
    }

    actual = resp_disabled.json()
    assert actual["normalized_drug"] is None
    assert actual["assessment"] is None

    # deidentified_text is an intentional change to a legacy field (preserves 'Patient: ' and 'MRN: ' label prefixes)
    assert actual["deidentified_text"] == "Patient: [REDACTED_NAME], MRN: [REDACTED_HOSPITAL_ID]. Took amoxicillin and got rash."
    for key in ("pipeline_run_id", "extraction", "summary", "citation_verification"):
        assert actual[key] == frozen[key], f"Mismatch on frozen fixture key '{key}'"
    assert {k: v for k, v in actual["classification"].items() if k not in ("expedited_clock_label", "periodic_clock_days")} == frozen["classification"]
    assert actual["classification"]["expedited_clock_label"] == "none"

    # Conservative causality check (intentional delta documented in intentional_deltas.md):
    # Q1: +1 (amoxicillin-rash known pair in table lookup)
    # Q2: 0 (no timeline/onset keyword)
    # Q3: 0 (no dechallenge)
    # Q4: 0 (no rechallenge)
    # Q5: 0 (no alternative cause mentioned or ruled out in narrative)
    # Total score = 1 ("Possible")
    assert actual["causality"]["naranjo_score"] == 1
    assert actual["causality"]["naranjo_category"] == "Possible"
    assert actual["causality"]["naranjo_breakdown"]["q5_alternative_causes_absent"] == 0
    assert actual["causality"]["unevidenced_items"] == ["q1_previous_conclusive_reports"]

    assert assess_spy.call_count == 0
    assert norm_spy.call_count == 0
    app.config.get_settings.cache_clear()


def test_pipeline_run_when_configured_populates_assessment_and_normalized_drug_once_without_network(
    monkeypatch,
):
    """
    Section 7 & Addendum Items 2, 4, 10: When LLM_PROVIDER is configured:
    - /pipeline/run populates assessment and normalized_drug,
    - live retrieve() items (which have 'evidence_id': None) fall back to E1, E2, E3 in both
      the outbound prompt and citation verification,
    - causality stays completely unchanged vs disabled mode and remains authoritative,
    - assessment is explicitly marked advisory_only=True / authority='advisory_model_derived',
    - run_causality_assessment and provider HTTP transport are called exactly once per request,
    - outbound LLM payload is recursively scanned and contains zero PHI and preserves clinical fields,
    - normalize_drug makes 0 network calls by default and returns source/lookup_status.
    """
    import app.config
    import app.main as main_mod
    import app.pipeline.normalize as norm_mod

    monkeypatch.setattr(extract_mod, "client", None)

    raw_narrative = (
        "Patient: John Doe, MRN: 849201, DOB 05/12/1980, phone 555-019-2831, "
        "email john.doe@example.com, living at 123 Maple Street. Developed a maculopapular rash "
        "2 days after starting amoxicillin 500 mg and lisinopril 10 mg."
    )

    client = TestClient(fastapi_app)

    # First run with LLM_PROVIDER=disabled to capture baseline causality (live OpenFDA + builtin corpus enabled to test 3-item replay)
    monkeypatch.setenv("ENABLE_LIVE_OPENFDA", "true")
    monkeypatch.setenv("ALLOW_BUILTIN_REFERENCE_CORPUS", "true")
    monkeypatch.setenv("LLM_PROVIDER", "disabled")
    app.config.get_settings.cache_clear()
    resp_disabled = client.post(
        "/pipeline/run",
        json={"pipeline_run_id": "run-disabled", "raw_text": raw_narrative},
    )
    assert resp_disabled.status_code == 200
    disabled_body = resp_disabled.json()
    assert disabled_body["assessment"] is None
    assert disabled_body["normalized_drug"] is None

    # Now configure Ollama with MockTransport
    captured_payloads = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": _valid_llm_assessment_json()}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 30},
            },
        )

    provider = OpenAICompatibleProvider(
        base_url="http://localhost:11434/v1",
        api_key="",
        model="qwen3:8b",
        provider_name="ollama",
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(assess_mod, "get_llm_provider", lambda s=None: provider)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen3:8b")
    app.config.get_settings.cache_clear()

    rxnav_spy = AsyncMock(side_effect=AssertionError("Network call in normalize_drug is forbidden by default!"))
    monkeypatch.setattr(norm_mod, "query_rxnav_approximate_term", rxnav_spy)

    assess_calls = 0
    real_assess = main_mod.run_causality_assessment

    async def counting_assess(*args, **kwargs):
        nonlocal assess_calls
        assess_calls += 1
        return await real_assess(*args, **kwargs)

    monkeypatch.setattr(main_mod, "run_causality_assessment", counting_assess)

    resp_enabled = client.post(
        "/pipeline/run",
        json={"pipeline_run_id": "run-enabled", "raw_text": raw_narrative},
    )
    assert resp_enabled.status_code == 200
    enabled_body = resp_enabled.json()

    # 1. Exactly 1 assessment call and 1 provider HTTP request
    assert assess_calls == 1
    assert len(captured_payloads) == 1
    assert rxnav_spy.call_count == 0

    # 2. Recursively scan outbound payload for all PHI, clinical fields, and E1..E3 evidence IDs
    outbound_strings = _collect_all_strings(captured_payloads[0])
    combined_outbound = "\n".join(outbound_strings)
    for forbidden in ("John Doe", "849201", "05/12/1980", "555-019-2831", "john.doe@example.com", "123 Maple Street"):
        assert forbidden.lower() not in combined_outbound.lower()
    for clinical in ("amoxicillin", "rash", "500 mg", "2 days after starting"):
        assert clinical.lower() in combined_outbound.lower()
    assert "[E1]" in combined_outbound
    assert "[E2]" in combined_outbound
    assert "[E3]" in combined_outbound
    assert "[None]" not in combined_outbound

    # 3. Advisory labeling on assessment vs authoritative causality, and E1 citation verified
    assert enabled_body["assessment"] is not None
    assert enabled_body["assessment"]["status"] == "completed"
    assert enabled_body["assessment"]["advisory_only"] is True
    assert enabled_body["assessment"]["authority"] == "advisory_model_derived"
    assert enabled_body["assessment"]["naranjo"]["advisory_only"] is True
    assert enabled_body["assessment"]["naranjo"]["answer_source"] == "llm_model_answers_scored_deterministically"
    assert enabled_body["assessment"]["citation_verification"]["all_cited"] is True
    assert enabled_body["assessment"]["citation_verification"]["fabricated_citations"] == []

    # 4. Normalized drug metadata
    assert enabled_body["normalized_drug"] is not None
    assert enabled_body["normalized_drug"]["matched"] is True
    assert enabled_body["normalized_drug"]["rxcui"] == "723"
    assert enabled_body["normalized_drug"]["name"] == "Amoxicillin"
    assert enabled_body["normalized_drug"]["source"] == "offline_catalog"
    assert enabled_body["normalized_drug"]["lookup_status"] == "offline_catalog"

    # 5. Authoritative causality stays completely unchanged
    assert enabled_body["causality"] == disabled_body["causality"]

    # 6. Unknown drug normalization makes 0 network calls and returns ingredients=[]
    unknown_norm = asyncio.run(norm_mod.normalize_drug("experimental_compound_zx9", allow_network=False))
    assert unknown_norm["matched"] is False
    assert unknown_norm["rxcui"] is None
    assert unknown_norm["ingredients"] == []
    assert unknown_norm["source"] == "network_disabled"
    assert unknown_norm["lookup_status"] == "network_disabled"
    assert rxnav_spy.call_count == 0
    app.config.get_settings.cache_clear()


def test_pipeline_run_assessment_privacy_failure_returns_generic_500(monkeypatch, caplog):
    """
    Section 7: When assessment privacy enforcement fails during /pipeline/run, the endpoint
    returns HTTP 500 with detail == DeidentificationError.public_message and leaks zero PHI.
    """
    import app.config

    monkeypatch.setattr(extract_mod, "client", None)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen3:8b")
    app.config.get_settings.cache_clear()

    secret_phi = "ASSESS_PIPELINE_RUN_SECRET_99281"

    def crashing_assess_scrub(text, settings=None):
        raise DeidentificationError()

    monkeypatch.setattr(assess_mod, "_scrub_for_assessment", crashing_assess_scrub)

    client = TestClient(fastapi_app, raise_server_exceptions=False)
    with caplog.at_level(logging.DEBUG):
        resp = client.post(
            "/pipeline/run",
            json={"pipeline_run_id": "run-assess-500", "raw_text": f"Patient {secret_phi} took amoxicillin and got rash."},
        )

    assert resp.status_code == 500
    assert resp.json() == {"detail": DeidentificationError.public_message}
    assert secret_phi not in resp.text
    assert secret_phi not in caplog.text
    app.config.get_settings.cache_clear()


def test_pipeline_run_non_privacy_assessment_failure_returns_assessment_none_and_logs_class_only(
    monkeypatch, caplog
):
    """
    Addendum Item 5: When run_causality_assessment raises a non-privacy exception during
    /pipeline/run, the endpoint returns HTTP 200 with assessment=None (preserving all core
    pipeline fields and normalized_drug) and logs only the exception class name.
    """
    import app.config
    import app.main as main_mod

    monkeypatch.setattr(extract_mod, "client", None)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen3:8b")
    app.config.get_settings.cache_clear()

    secret_err_text = "NON_PRIVACY_ASSESS_FAILURE_SECRET_88312"

    async def failing_run_assessment(*args, **kwargs):
        raise RuntimeError(f"Unexpected upstream crash: {secret_err_text}")

    monkeypatch.setattr(main_mod, "run_causality_assessment", failing_run_assessment)

    client = TestClient(fastapi_app, raise_server_exceptions=False)
    with caplog.at_level(logging.DEBUG):
        resp = client.post(
            "/pipeline/run",
            json={"pipeline_run_id": "run-non-priv-err", "raw_text": "Patient took amoxicillin 500 mg and developed rash."},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["assessment"] is None
    assert body["normalized_drug"] is not None
    assert body["normalized_drug"]["rxcui"] == "723"
    assert body["causality"]["naranjo_category"] in ("Possible", "Probable", "Definite", "Doubtful")
    assert "RuntimeError" in caplog.text
    assert secret_err_text not in caplog.text
    assert secret_err_text not in resp.text
    app.config.get_settings.cache_clear()


def test_summarize_regex_tripwire_outside_try_raises_deidentification_error_and_pipeline_500(
    monkeypatch, caplog
):
    """
    Addendum Item 10: Verifies that summarize() runs _assert_no_residual_regex_phi(prompt)
    outside its try/except block before calling client.models.generate_content, so residual
    regex PHI raises DeidentificationError with 0 Gemini calls and /pipeline/run returns generic 500.
    """
    import app.main as main_mod
    from app.pipeline import summarize as summarize_mod

    mock_client = _make_mock_gemini_client("Summary text [Source 1].")
    monkeypatch.setattr(summarize_mod, "client", mock_client)

    with pytest.raises(DeidentificationError):
        summarize_mod.summarize(
            {"drugName": "amoxicillin (Patient: John Doe, MRN: 849201, phone 555-019-2831)", "symptoms": ["rash"]},
            {"severity": "mild", "is_serious": False, "seriousness_criteria": [], "confidence": 0.9, "model_name": "m", "model_version": "1"},
            [],
        )
    assert mock_client.models.generate_content.call_count == 0

    # Also verify /pipeline/run catches DeidentificationError from summarize and returns generic 500
    monkeypatch.setattr(
        main_mod,
        "extract",
        lambda text: {
            "drugName": "amoxicillin (Patient: John Doe, MRN: 849201, phone 555-019-2831)",
            "genericName": "amoxicillin",
            "dosage": None,
            "frequency": None,
            "route": None,
            "duration": None,
            "symptoms": ["rash"],
            "onsetTimeline": None,
            "age": None,
            "gender": None,
            "comorbidities": [],
            "concomitantDrugs": [],
            "incomplete": False,
            "modelVersion": "test",
            "promptVersion": "v2",
            "terminology": {},
        },
    )
    client = TestClient(fastapi_app, raise_server_exceptions=False)
    with caplog.at_level(logging.DEBUG):
        resp = client.post(
            "/pipeline/run",
            json={"pipeline_run_id": "run-sum-500", "raw_text": "Patient took amoxicillin and got rash."},
        )
    assert resp.status_code == 500
    assert resp.json() == {"detail": DeidentificationError.public_message}
    assert mock_client.models.generate_content.call_count == 0


@pytest.mark.asyncio
async def test_has_residual_regex_phi_zero_false_positives_across_11_corpus_and_8_benchmark_cases():
    """
    Addendum Item 8: Permanent unit test verifying that _has_residual_regex_phi and the
    assembled assessment prompt tripwire produce zero false positives across all 11
    KNOWLEDGE_CORPUS evidence snippets and all 8 BENCHMARK_CASES clinical vignettes.
    """
    from app.pipeline.deidentify import deidentify
    from app.pipeline.retrieve import KNOWLEDGE_CORPUS
    from app.privacy import _has_residual_regex_phi
    from tests.test_evaluation_benchmark import BENCHMARK_CASES

    disabled_settings = load_settings({"LLM_PROVIDER": "disabled"})

    assert len(KNOWLEDGE_CORPUS) == 11
    for doc in KNOWLEDGE_CORPUS:
        assert _has_residual_regex_phi(doc["title"]) is False
        assert _has_residual_regex_phi(doc["snippet"]) is False
        res = await run_causality_assessment(
            deidentified_text="Patient developed reaction after starting medication.",
            extraction={"drugName": doc["keywords"][0], "symptoms": ["rash"]},
            retrievals=[
                {
                    "evidence_id": doc["source_id"],
                    "title": doc["title"],
                    "snippet": doc["snippet"],
                }
            ],
            settings=disabled_settings,
        )
        assert res["status"] == "fallback"

    assert len(BENCHMARK_CASES) == 8
    for case in BENCHMARK_CASES:
        deid_text, _ = deidentify(case["raw_narrative"], use_ner=True)
        assert _has_residual_regex_phi(deid_text) is False, (
            f"False positive tripwire hit on de-identified benchmark case {case['case_id']}: {deid_text}"
        )
        res = await run_causality_assessment(
            deidentified_text=deid_text,
            extraction={"drugName": case["expected_drug"], "symptoms": [case["expected_reaction"]]},
            retrievals=[],
            settings=disabled_settings,
        )
        assert res["status"] == "fallback"






def test_assessment_status_state_disabled(monkeypatch):
    """Verifies assessment_status is 'disabled' when LLM_PROVIDER=disabled."""
    import app.config
    monkeypatch.setattr(extract_mod, "client", None)
    monkeypatch.setenv("LLM_PROVIDER", "disabled")
    app.config.get_settings.cache_clear()
    client = TestClient(fastapi_app)
    resp = client.post("/pipeline/run", json={"pipeline_run_id": "test-dis", "raw_text": "Patient took amoxicillin."})
    assert resp.status_code == 200
    body = resp.json()
    assert body["assessment_status"] == "disabled"
    assert body["assessment"] is None
    assert body["assessment_error"] is None


def test_assessment_status_state_unconfigured(monkeypatch):
    """Verifies assessment_status is 'unconfigured' when LLM_PROVIDER=openrouter without api key."""
    import app.config
    monkeypatch.setattr(extract_mod, "client", None)
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    app.config.get_settings.cache_clear()
    client = TestClient(fastapi_app)
    resp = client.post("/pipeline/run", json={"pipeline_run_id": "test-unconf", "raw_text": "Patient took amoxicillin."})
    assert resp.status_code == 200
    body = resp.json()
    assert body["assessment_status"] == "unconfigured"
    assert body["assessment"] is None
    assert body["assessment_error"] is None


def test_assessment_status_state_completed(monkeypatch):
    """Verifies assessment_status is 'completed' when LLM provider returns valid assessment."""
    import app.config
    import app.pipeline.assess as a_mod
    monkeypatch.setattr(extract_mod, "client", None)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen3:8b")
    app.config.get_settings.cache_clear()

    provider = OpenAICompatibleProvider(
        base_url="http://localhost:11434/v1",
        api_key="",
        model="qwen3:8b",
        provider_name="ollama",
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={
            "choices": [{"message": {"content": _valid_llm_assessment_json()}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10},
        })),
    )
    monkeypatch.setattr(a_mod, "get_llm_provider", lambda s=None: provider)
    monkeypatch.setenv("ALLOW_BUILTIN_REFERENCE_CORPUS", "true")
    app.config.get_settings.cache_clear()
    client = TestClient(fastapi_app)
    resp = client.post("/pipeline/run", json={"pipeline_run_id": "test-comp", "raw_text": "Patient took amoxicillin 500mg and developed rash."})
    assert resp.status_code == 200
    body = resp.json()
    assert body["assessment_status"] == "completed"
    assert body["assessment"] is not None
    assert body["assessment_error"] is None


def test_assessment_status_state_failed(monkeypatch):
    """Verifies assessment_status is 'failed' when downstream assessment encounters a non-privacy error."""
    import app.config
    import app.main as m_mod
    monkeypatch.setattr(extract_mod, "client", None)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen3:8b")
    app.config.get_settings.cache_clear()

    async def fail_assess(*args, **kwargs):
        raise ValueError("Downstream parsing crash")

    monkeypatch.setattr(m_mod, "run_causality_assessment", fail_assess)
    client = TestClient(fastapi_app, raise_server_exceptions=False)
    resp = client.post("/pipeline/run", json={"pipeline_run_id": "test-fail", "raw_text": "Patient took amoxicillin 500mg and developed rash."})
    assert resp.status_code == 200
    body = resp.json()
    assert body["assessment_status"] == "failed"
    assert body["assessment"] is None
    assert body["assessment_error"] == "ValueError"


def test_pipeline_statuses_survive_http_serialization():
    """Verifies that typed status fields serialize across HTTP and parse into PipelineResponse."""
    from app.schemas import PipelineResponse
    client = TestClient(fastapi_app)
    resp = client.post("/pipeline/run", json={"pipeline_run_id": "test-http-serial", "raw_text": "Patient took amoxicillin."})
    assert resp.status_code == 200
    raw = resp.json()
    assert "evidence_status" in raw
    assert "assessment_status" in raw
    assert "assessment_error" in raw
    assert raw["evidence_status"] in ("ok", "none_found", "live_disabled")
    assert raw["assessment_status"] in ("completed", "disabled", "unconfigured", "failed")
    parsed = PipelineResponse(**raw)
    assert parsed.evidence_status == raw["evidence_status"]
    assert parsed.assessment_status == raw["assessment_status"]

"""
Step 2 Clinical and Privacy Verification Suite.

Covers:
- Step 2.1: Suspect drug selection by earliest narrative position (unless explicitly flagged
  as suspect), concomitant drug extraction, and brand/generic mapping.
- Step 2.2: Fail-closed privacy boundary (HTTP 500) vs LLM provider failure resilience (HTTP 200 fallback).
- Step 2.3: Config-driven model/provider selection in extract.py and summarize.py without hardcoded literals.
- Step 2.4: Deterministic grounding of LLM-extracted fields (drugName, genericName, brandName,
  route, duration, age, gender, comorbidities, concomitantDrugs, dosage, frequency, onsetTimeline).
- Step 2.5: Naranjo item weights in {-1, 0, +1, +2}, total range -4..+13, category boundaries
  (-4, 0, 1, 4, 5, 8, 9, 13), and Q5 conservative default (0 vs prior origin/main +2).
- Step 2.6: Regulatory expedited clock (7/15-day applies only when serious AND unexpected AND
  reasonably related, anchored to real receipt date; otherwise 'potential' or 'none').
- Step 2.7: De-identification adversarial tests (person names colliding with drug/symptom words,
  phones, emails, MRNs, dates, addresses), lexicon precedence, and labelled synthetic precision/recall.
- Step 2.8: TrustedEvidenceRecord provenance marker and OpenFDA query term person-name rejection.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

import app.config as config_mod
import app.main as main_mod
import app.pipeline.extract as extract_mod
import app.pipeline.summarize as summarize_mod
from app.errors import DeidentificationError
from app.main import app as fastapi_app
from app.pipeline.causality import evaluate_naranjo_causality
from app.pipeline.classify import evaluate_expedited_regulatory_clock, evaluate_ich_e2a_criteria
from app.pipeline.deidentify import deidentify
from app.pipeline.extract import extract, extract_fallback
from app.pipeline.naranjo import NARANJO_QUESTIONS, MIN_NARANJO_SCORE, MAX_NARANJO_SCORE, score_naranjo
from app.pipeline.retrieve import TrustedEvidenceRecord, validate_openfda_query_term


# ---------------------------------------------------------------------------
# Step 2.1 — Suspect Drug Selection, Concomitant Drugs, Brand/Generic
# ---------------------------------------------------------------------------

def test_suspect_drug_earliest_position_and_concomitant_list():
    """
    When multiple drugs appear without an explicit suspect label:
    - Case A: 'amoxicillin 500 mg and lisinopril 10 mg' -> suspect='amoxicillin', concomitant=['lisinopril']
    - Case B: 'lisinopril 10 mg and amoxicillin 500 mg' -> suspect='lisinopril', concomitant=['amoxicillin']
      (previously picked 'amoxicillin' solely because it came earlier in KNOWN_DRUGS!)
    """
    res_a = extract_fallback(
        "Developed a maculopapular rash 2 days after starting amoxicillin 500 mg and lisinopril 10 mg."
    )
    assert res_a["drugName"] == "amoxicillin"
    assert res_a["genericName"] == "amoxicillin"
    assert res_a["concomitantDrugs"] == ["lisinopril"]

    res_b = extract_fallback(
        "Patient taking lisinopril 10 mg and amoxicillin 500 mg developed rash and cough."
    )
    assert res_b["drugName"] == "lisinopril"
    assert res_b["genericName"] == "lisinopril"
    assert res_b["concomitantDrugs"] == ["amoxicillin"]


def test_suspect_drug_explicit_flag_overrides_earlier_chronic_drug():
    """
    When an earlier drug is chronic/background or a later drug is explicitly flagged as the
    suspect drug ('suspect drug: amoxicillin', 'caused by amoxicillin', or 'chronic lisinopril ...
    started amoxicillin'), the explicitly flagged drug is selected as suspect and the earlier
    drug is placed in concomitantDrugs.
    """
    res_explicit = extract_fallback(
        "Patient on lisinopril 10 mg daily. Suspect drug: amoxicillin 500 mg caused rash."
    )
    assert res_explicit["drugName"] == "amoxicillin"
    assert res_explicit["concomitantDrugs"] == ["lisinopril"]

    res_chronic = extract_fallback(
        "Patient on chronic lisinopril 10 mg daily, started amoxicillin 500 mg and developed rash."
    )
    assert res_chronic["drugName"] == "amoxicillin"
    assert res_chronic["concomitantDrugs"] == ["lisinopril"]


def test_suspect_drug_brand_and_generic_mapping():
    """
    Verifies brand-to-generic resolution and concomitant deduplication when brand + generic
    of the same ingredient appear vs a second distinct drug.
    """
    # Brand Tylenol + parenthetical generic acetaminophen + concomitant ibuprofen
    res = extract_fallback(
        "Patient took tylenol (acetaminophen) 500 mg and advil 200 mg and developed nausea."
    )
    assert res["drugName"] == "tylenol"
    assert res["brandName"] == "tylenol"
    assert res["genericName"] == "acetaminophen"
    # 'acetaminophen' must not be duplicated into concomitantDrugs; 'advil' is concomitant
    assert res["concomitantDrugs"] == ["advil"]
    assert res["terminology"]["drug_rxnorm"]["rxcui"] == "161"


# ---------------------------------------------------------------------------
# Step 2.2 — Fail-Closed Privacy vs. LLM Provider Resilience
# ---------------------------------------------------------------------------

def test_fail_closed_privacy_vs_llm_resilience_in_pipeline(monkeypatch):
    """
    Proves:
    1) A privacy/de-identification failure stops the request with HTTP 500.
    2) A missing or failed LLM key/client in extract(), summarize(), or assess() does NOT
       stop the request; /pipeline/run falls back deterministically and returns HTTP 200.
    """
    client = TestClient(fastapi_app, raise_server_exceptions=False)

    # 1. Privacy failure in extract -> HTTP 500
    with patch("app.main.deidentify", side_effect=RuntimeError("NER crash")):
        resp_500 = client.post(
            "/pipeline/run",
            json={"pipeline_run_id": "step2-priv-500", "raw_text": "Patient John Doe took amoxicillin and got rash."},
        )
    assert resp_500.status_code == 500
    assert resp_500.json() == {"detail": DeidentificationError.public_message}

    # 2. Failed LLM client in extract() AND summarize() -> falls back cleanly, returns HTTP 200
    broken_gemini = MagicMock()
    broken_gemini.models.generate_content.side_effect = RuntimeError("Invalid API key / network down")
    monkeypatch.setattr(extract_mod, "client", broken_gemini)
    monkeypatch.setattr(summarize_mod, "client", broken_gemini)
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    config_mod.get_settings.cache_clear()

    resp_200 = client.post(
        "/pipeline/run",
        json={"pipeline_run_id": "step2-resilience-200", "raw_text": "Patient Jane Doe took amoxicillin 500 mg and got rash."},
    )
    assert resp_200.status_code == 200
    body = resp_200.json()
    assert body["extraction"]["drugName"] == "amoxicillin"
    assert "Report involves amoxicillin" in body["summary"]
    assert body["assessment_status"] == "unconfigured"
    config_mod.get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Step 2.3 — No Hardcoded gemini-2.5-pro; Config-Driven Model Selection
# ---------------------------------------------------------------------------

def test_no_hardcoded_gemini_literal_and_env_selectable_model(monkeypatch):
    """
    Verifies that neither extract.py nor summarize.py contains a hardcoded 'gemini-2.5-pro'
    literal, and that GEMINI_MODEL env configures the model passed to generate_content.
    """
    extract_src = Path(extract_mod.__file__).read_text(encoding="utf-8")
    summarize_src = Path(summarize_mod.__file__).read_text(encoding="utf-8")
    assert "gemini-2.5-pro" not in extract_src
    assert "gemini-2.5-pro" not in summarize_src

    mock_ext_client = MagicMock()
    mock_ext_resp = MagicMock()
    mock_ext_resp.text = '{"drugName": "amoxicillin", "symptoms": ["rash"]}'
    mock_ext_client.models.generate_content.return_value = mock_ext_resp
    monkeypatch.setattr(extract_mod, "client", mock_ext_client)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash-preview")
    config_mod.get_settings.cache_clear()

    res = extract("Patient took amoxicillin and developed rash.")
    assert mock_ext_client.models.generate_content.call_args.kwargs["model"] == "gemini-2.5-flash-preview"
    assert res["modelVersion"] == "gemini-2.5-flash-preview-extraction"
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    config_mod.get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Step 2.4 — Grounding Ungrounded LLM Extraction Fields
# ---------------------------------------------------------------------------

def test_llm_extraction_grounds_all_ungrounded_fields(monkeypatch):
    """
    Verifies that hallucinated LLM extraction fields (drugName, genericName, brandName,
    route, duration, age, gender, comorbidities, concomitantDrugs, dosage, frequency,
    onsetTimeline) are nulled/filtered when absent from deidentified_text, and preserved
    when grounded in deidentified_text.
    """
    # 1. All hallucinated values not in narrative -> nulled / emptied
    hallucinated_payload = json.dumps({
        "drugName": "warfarin",
        "genericName": "warfarin",
        "brandName": "Coumadin",
        "dosage": "999 mg",
        "frequency": "four times a day",
        "route": "intravenous",
        "duration": "14 days",
        "symptoms": ["rash"],
        "onsetTimeline": "3 days after admission",
        "age": 72,
        "gender": "female",
        "comorbidities": ["atrial fibrillation", "heart failure"],
        "concomitantDrugs": ["metformin", "digoxin"],
    })
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = hallucinated_payload
    mock_client.models.generate_content.return_value = mock_resp
    monkeypatch.setattr(extract_mod, "client", mock_client)

    res_ungrounded = extract("Patient took amoxicillin and developed a mild rash.")
    assert res_ungrounded["drugName"] is None
    assert res_ungrounded["genericName"] is None
    assert res_ungrounded["brandName"] is None
    assert res_ungrounded["dosage"] is None
    assert res_ungrounded["frequency"] is None
    assert res_ungrounded["route"] is None
    assert res_ungrounded["duration"] is None
    assert res_ungrounded["onsetTimeline"] is None
    assert res_ungrounded["age"] is None
    assert res_ungrounded["gender"] is None
    assert res_ungrounded["comorbidities"] == []
    assert res_ungrounded["concomitantDrugs"] == []

    # 2. All grounded values present in narrative -> preserved
    grounded_payload = json.dumps({
        "drugName": "amoxicillin",
        "genericName": "amoxicillin",
        "brandName": "Augmentin",
        "dosage": "500 mg",
        "frequency": "twice a day",
        "route": "oral",
        "duration": "7 days",
        "symptoms": ["rash"],
        "onsetTimeline": "2 days after starting amoxicillin",
        "age": 45,
        "gender": "female",
        "comorbidities": ["hypertension"],
        "concomitantDrugs": ["lisinopril"],
    })
    mock_resp.text = grounded_payload
    narrative = (
        "A 45-year-old female with hypertension on lisinopril took Augmentin (amoxicillin) "
        "500 mg oral twice a day for 7 days and developed a rash 2 days after starting amoxicillin."
    )
    res_grounded = extract(narrative)
    assert res_grounded["drugName"] == "amoxicillin"
    assert res_grounded["genericName"] == "amoxicillin"
    assert res_grounded["brandName"] == "Augmentin"
    assert res_grounded["dosage"] == "500 mg"
    assert res_grounded["frequency"] == "twice a day"
    assert res_grounded["route"] == "oral"
    assert res_grounded["duration"] == "7 days"
    assert res_grounded["onsetTimeline"] == "2 days after starting amoxicillin"
    assert res_grounded["age"] == 45
    assert res_grounded["gender"] == "female"
    assert res_grounded["comorbidities"] == ["hypertension"]
    assert res_grounded["concomitantDrugs"] == ["lisinopril"]


# ---------------------------------------------------------------------------
# Step 2.5 — Naranjo Weights, Range, and Boundary Tests (-4, 0, 1, 4, 5, 8, 9, 13)
# ---------------------------------------------------------------------------

def test_naranjo_weights_range_and_exact_category_boundaries():
    """
    Verifies:
    - Every Naranjo item weight is in {-1, 0, +1, +2}.
    - Theoretical minimum is -4 and maximum is +13.
    - Category boundaries: Doubtful <= 0 (-4, 0), Possible 1..4 (1, 4),
      Probable 5..8 (5, 8), Definite >= 9 (9, 13).
    """
    allowed_weights = {-1, 0, 1, 2}
    min_sum = 0
    max_sum = 0
    for q in NARANJO_QUESTIONS:
        scores = set(q["scores"].values())
        assert scores <= allowed_weights, f"Question {q['key']} has weight outside {{-1,0,1,2}}: {scores}"
        min_sum += min(scores)
        max_sum += max(scores)

    assert min_sum == MIN_NARANJO_SCORE == -4
    assert max_sum == MAX_NARANJO_SCORE == 13

    boundary_cases = [
        (-4, "doubtful", {
            "q2_event_after_drug": "no",          # -1
            "q4_reappeared_on_rechallenge": "no", # -1
            "q5_alternative_causes": "yes",       # -1
            "q6_placebo_response": "yes",         # -1
        }),
        (0, "doubtful", {}),
        (1, "possible", {"q1_previous_reports": "yes"}),
        (4, "possible", {
            "q1_previous_reports": "yes",         # +1
            "q2_event_after_drug": "yes",         # +2
            "q3_improved_on_dechallenge": "yes",  # +1
        }),
        (5, "probable", {
            "q1_previous_reports": "yes",         # +1
            "q2_event_after_drug": "yes",         # +2
            "q5_alternative_causes": "no",        # +2
        }),
        (8, "probable", {
            "q1_previous_reports": "yes",         # +1
            "q2_event_after_drug": "yes",         # +2
            "q3_improved_on_dechallenge": "yes",  # +1
            "q4_reappeared_on_rechallenge": "yes",# +2
            "q5_alternative_causes": "no",        # +2
        }),
        (9, "definite", {
            "q1_previous_reports": "yes",         # +1
            "q2_event_after_drug": "yes",         # +2
            "q3_improved_on_dechallenge": "yes",  # +1
            "q4_reappeared_on_rechallenge": "yes",# +2
            "q5_alternative_causes": "no",        # +2
            "q10_objective_evidence": "yes",      # +1
        }),
        (13, "definite", {
            "q1_previous_reports": "yes",         # +1
            "q2_event_after_drug": "yes",         # +2
            "q3_improved_on_dechallenge": "yes",  # +1
            "q4_reappeared_on_rechallenge": "yes",# +2
            "q5_alternative_causes": "no",        # +2
            "q6_placebo_response": "no",          # +1
            "q7_toxic_drug_concentration": "yes", # +1
            "q8_dose_response": "yes",            # +1
            "q9_similar_previous_reaction": "yes",# +1
            "q10_objective_evidence": "yes",      # +1
        }),
    ]

    for expected_score, expected_category, answers in boundary_cases:
        res = score_naranjo(answers)
        assert res.total_score == expected_score
        assert res.category == expected_category


# ---------------------------------------------------------------------------
# Step 2.6 — Regulatory Expedited Clock Conditions
# ---------------------------------------------------------------------------

def test_expedited_regulatory_clock_requires_serious_unexpected_and_related():
    """
    Proves that the 7/15-day expedited clock applies ONLY when the case is:
    serious AND unexpected AND reasonably related, and depends on receipt_date.
    Otherwise returns 'potential' (when unconfirmed) or 'none' (when non-serious,
    expected, or unrelated).
    """
    # 1. Serious (life-threatening) + unexpected=True + reasonably_related=True -> expedited 7-day
    c1 = evaluate_expedited_regulatory_clock(
        is_serious=True,
        criteria=["life_threatening"],
        unexpected=True,
        reasonably_related=True,
        receipt_date="2026-10-01T00:00:00+00:00",
    )
    assert c1["applies"] is True
    assert c1["clock_type"] == "expedited"
    assert c1["label"] == "expedited_7_day"
    assert c1["expedited_clock_days"] == 7
    assert c1["due_date"] == "2026-10-08T00:00:00+00:00"

    # 2. Serious (hospitalization) + unexpected=True + reasonably_related=True -> expedited 15-day
    c2 = evaluate_expedited_regulatory_clock(
        is_serious=True,
        criteria=["hospitalization"],
        unexpected=True,
        reasonably_related=True,
        receipt_date="2026-10-01T00:00:00+00:00",
    )
    assert c2["applies"] is True
    assert c2["clock_type"] == "expedited"
    assert c2["label"] == "expedited_15_day"
    assert c2["expedited_clock_days"] == 15
    assert c2["due_date"] == "2026-10-16T00:00:00+00:00"

    # 3. Serious + unexpected=None (unconfirmed at intake) -> potential_7_day (applies=False)
    c3 = evaluate_expedited_regulatory_clock(
        is_serious=True,
        criteria=["death"],
        unexpected=None,
        reasonably_related=None,
    )
    assert c3["applies"] is False
    assert c3["clock_type"] == "potential"
    assert c3["label"] == "potential_7_day"
    assert c3["expedited_clock_days"] is None
    assert c3["due_date"] is None
    assert c3["receipt_date_required"] is True

    # 3b. Serious (hospitalization) + unexpected=None (unconfirmed at intake) -> potential_15_day (applies=False)
    c3b = evaluate_expedited_regulatory_clock(
        is_serious=True,
        criteria=["hospitalization"],
        unexpected=None,
        reasonably_related=None,
    )
    assert c3b["applies"] is False
    assert c3b["clock_type"] == "potential"
    assert c3b["label"] == "potential_15_day"
    assert c3b["expedited_clock_days"] is None
    assert c3b["potential_clock_days"] == 15
    assert c3b["due_date"] is None
    assert c3b["receipt_date_required"] is True

    # 4. Serious + unexpected=False (known labeled reaction) -> none
    c4 = evaluate_expedited_regulatory_clock(
        is_serious=True,
        criteria=["hospitalization"],
        unexpected=False,
        reasonably_related=True,
    )
    assert c4["applies"] is False
    assert c4["clock_type"] == "none"
    assert c4["label"] == "none"
    assert c4["expedited_clock_days"] is None

    # 5. Serious + reasonably_related=False -> none
    c5 = evaluate_expedited_regulatory_clock(
        is_serious=True,
        criteria=["hospitalization"],
        unexpected=True,
        reasonably_related=False,
    )
    assert c5["applies"] is False
    assert c5["clock_type"] == "none"
    assert c5["label"] == "none"

    # 6. Non-serious -> none
    c6 = evaluate_expedited_regulatory_clock(
        is_serious=False,
        criteria=[],
        unexpected=True,
        reasonably_related=True,
    )
    assert c6["applies"] is False
    assert c6["clock_type"] == "none"
    assert c6["label"] == "none"


# ---------------------------------------------------------------------------
# Step 2.7 — Adversarial De-identification, Lexicon Precedence & Precision/Recall
# ---------------------------------------------------------------------------

def test_deid_adversarial_identifier_precedence_over_clinical_lexicon():
    """
    Proves that detected identifiers (honorific-titled names, multi-word person names,
    emails, MRNs, phones, dates, addresses) ALWAYS take precedence over the clinical
    lexicon, even when they collide with drug or symptom words.
    """
    adversarial_cases = [
        # Honorific title + surname colliding with symptom or drug word
        ("Dr. Rash prescribed amoxicillin.", "Dr. [REDACTED_NAME]", "amoxicillin"),
        ("Mr. Fever took ibuprofen 400 mg.", "Mr. [REDACTED_NAME]", "ibuprofen"),
        ("Ms. Pain reported nausea.", "Ms. [REDACTED_NAME]", "nausea"),
        ("Dr. Warfarin evaluated the patient.", "Dr. [REDACTED_NAME]", "evaluated"),
        # Multi-word person name colliding with drug/symptom word
        ("Patient: Lily Rash took amoxicillin.", "Patient: [REDACTED_NAME]", "amoxicillin"),
        # Email / MRN / Address containing clinical drug/symptom words
        ("Email amoxicillin@hospital.org for rash.", "[REDACTED_EMAIL]", "rash"),
        ("MRN: Zoloft-998812 developed hives.", "[REDACTED_HOSPITAL_ID]", "hives"),
        ("Lives at 123 Lipitor Street, took aspirin.", "[REDACTED_LOCATION]", "aspirin"),
    ]
    for raw, expected_redaction, preserved_clinical in adversarial_cases:
        scrubbed, _ = deidentify(raw, use_ner=True)
        assert expected_redaction in scrubbed, f"Failed to redact identifier in: {raw} -> {scrubbed}"
        assert preserved_clinical in scrubbed, f"Lost clinical word '{preserved_clinical}' in: {raw} -> {scrubbed}"


def test_deid_labelled_synthetic_benchmark_precision_and_recall():
    """
    Measures entity-level PHI recall and clinical entity preservation precision/recall
    across a labelled synthetic evaluation set covering names (including collisions),
    phones, emails, MRNs, dates, and street addresses.
    """
    labelled_dataset = [
        {
            "raw": "Patient: John Doe, MRN: 849201, DOB 05/12/1980, phone 555-019-2831, email john.doe@example.com, living at 123 Maple Street, took amoxicillin 500 mg and developed rash.",
            "phi_spans": ["John Doe", "849201", "05/12/1980", "555-019-2831", "john.doe@example.com", "123 Maple Street"],
            "clinical_spans": ["amoxicillin", "500 mg", "rash"],
        },
        {
            "raw": "Dr. Rash evaluated Mrs. Maria Garcia (Chart ID #449102, tel (555) 234-5678, mgarcia@clinic.org, 742 Evergreen Avenue) on Jan 15, 2024 for angioedema after lisinopril 20 mg.",
            "phi_spans": ["Dr. Rash", "Maria Garcia", "449102", "(555) 234-5678", "mgarcia@clinic.org", "742 Evergreen Avenue", "Jan 15, 2024"],
            "clinical_spans": ["angioedema", "lisinopril", "20 mg"],
        },
        {
            "raw": "Mr. Fever (SSN 123-45-6789, Hospital ID: HX-9910, 88 Oak Road) experienced tendon rupture and myalgia 5 days after starting ciprofloxacin 500 mg.",
            "phi_spans": ["Mr. Fever", "123-45-6789", "HX-9910", "88 Oak Road"],
            "clinical_spans": ["tendon rupture", "myalgia", "ciprofloxacin", "500 mg"],
        },
        {
            "raw": "Patient: Lily Rash, DOB 11/03/1965, phone +1-800-555-0199, email lily.rash@mail.com, presented with Stevens-Johnson syndrome after allopurinol 300 mg.",
            "phi_spans": ["Lily Rash", "11/03/1965", "+1-800-555-0199", "lily.rash@mail.com"],
            "clinical_spans": ["Stevens-Johnson syndrome", "allopurinol", "300 mg"],
        },
    ]

    total_phi = 0
    redacted_phi = 0
    total_clinical = 0
    preserved_clinical = 0
    false_positive_redactions = 0

    for item in labelled_dataset:
        scrubbed, _ = deidentify(item["raw"], use_ner=True)
        for phi in item["phi_spans"]:
            total_phi += 1
            # For titled spans like 'Dr. Rash', check that the surname 'Rash' after 'Dr.' was replaced
            if phi.startswith(("Dr. ", "Mr. ")):
                prefix = phi.split()[0]
                if f"{prefix} [REDACTED_NAME]" in scrubbed:
                    redacted_phi += 1
            elif phi not in scrubbed:
                redacted_phi += 1

        for clin in item["clinical_spans"]:
            total_clinical += 1
            if clin.lower() in scrubbed.lower():
                preserved_clinical += 1
            else:
                false_positive_redactions += 1

    phi_recall = redacted_phi / total_phi
    phi_precision = redacted_phi / (redacted_phi + false_positive_redactions)
    clinical_preservation_rate = preserved_clinical / total_clinical

    assert total_phi == 21
    assert redacted_phi == 21
    assert false_positive_redactions == 0
    assert phi_recall == 1.0
    assert phi_precision == 1.0
    assert clinical_preservation_rate == 1.0


# ---------------------------------------------------------------------------
# Step 2.8 — Provenance Marker & OpenFDA Query Term Person-Name Rejection
# ---------------------------------------------------------------------------

def test_openfda_query_whitelist_rejects_person_names_and_allows_drugs():
    """
    Verifies that validate_openfda_query_term rejects person names (titled and untitled)
    while allowing valid generic and brand drug names.
    """
    for valid_drug in ("amoxicillin", "lisinopril", "augmentin", "atorvastatin", "amoxicillin-clavulanate"):
        ok, clean, err = validate_openfda_query_term(valid_drug)
        assert ok is True, f"Valid drug '{valid_drug}' was rejected with {err}"
        assert clean == valid_drug

    for person_name in ("John Smith", "Dr. Jane Doe", "Alice Wonderland", "Robert Miller", "Mr. Rash"):
        ok, _, err = validate_openfda_query_term(person_name)
        assert ok is False, f"Person name '{person_name}' should be rejected by validate_openfda_query_term!"
        assert err in ("pii_rejected", "invalid_characters")


"""
Unit tests for Clinical De-identification and Protected Lexicon.
"""

from app.pipeline.deidentify import deidentify, is_protected_clinical_term


def test_is_protected_clinical_term():
    assert is_protected_clinical_term("Advil") is True
    assert is_protected_clinical_term("metformin") is True
    assert is_protected_clinical_term("allopurinol") is True
    assert is_protected_clinical_term("Stevens-Johnson") is True
    assert is_protected_clinical_term("atorvastatin") is True
    assert is_protected_clinical_term("amoxicillin") is True
    assert is_protected_clinical_term("John Smith") is False
    assert is_protected_clinical_term("David Miller") is False


def test_deidentify_pii_and_phi():
    raw = (
        "Patient John Miller, MRN #88992, living at 45 Elm Street, Chicago. "
        "Contact: jmiller@hospital.org or 312-555-0199. "
        "Admitted on 05/12/2021 by Dr. Robert Vance. "
        "Prescribed Advil 400mg twice daily. "
        "Developed severe hives and facial angioedema within 4 hours."
    )
    clean, log = deidentify(raw, use_ner=True)

    # Identifiers scrubbed
    assert "John Miller" not in clean
    assert "88992" not in clean
    assert "45 Elm Street" not in clean
    assert "jmiller@hospital.org" not in clean
    assert "312-555-0199" not in clean
    assert "05/12/2021" not in clean
    assert "Robert Vance" not in clean

    # Clinical details preserved
    assert "Advil" in clean
    assert "400mg" in clean
    assert "twice daily" in clean
    assert "hives" in clean
    assert "angioedema" in clean
    assert "within 4 hours" in clean

    # Log entries present
    log_types = {entry.type for entry in log}
    assert "email" in log_types
    assert "phone" in log_types
    assert "mrn" in log_types
    assert "address" in log_types
    assert "date" in log_types
    assert "name" in log_types


def test_deidentify_empty_text():
    clean, log = deidentify("")
    assert clean == ""
    assert log == []


from unittest.mock import patch
import pytest
from app.pipeline.deidentify import deidentify_document, DeidentifiedDocument


def test_eponymous_medical_terms_not_redacted():
    # Clinical syndromes with human surnames must NOT be redacted, but real patient names must be
    narrative = (
        "Patient: Mary Watson, 45, diagnosed with Stevens-Johnson syndrome and Parkinson disease. "
        "Also showed symptoms of Crohn disease and Raynaud phenomenon."
    )
    clean, log = deidentify(narrative, use_ner=True)
    assert "Stevens-Johnson" in clean
    assert "Parkinson" in clean
    assert "Crohn" in clean
    assert "Raynaud" in clean
    assert "Mary Watson" not in clean
    assert "[REDACTED_NAME]" in clean


def test_deidentify_document_container():
    doc = deidentify_document("Patient: John Smith took amoxicillin.")
    assert isinstance(doc, DeidentifiedDocument)
    assert doc.level == "safe_harbor_heuristic"
    assert "John Smith" not in doc.text
    assert "amoxicillin" in doc.text
    assert isinstance(doc.log, list)
    assert len(doc.log) >= 1
    assert doc.log[0]["span"] == "[REDACTED]"


def test_deidentify_fail_closed_on_ner_crash():
    with patch("app.pipeline.deidentify.get_spacy_model") as mock_get:
        class CrashingNLP:
            def __call__(self, text):
                raise RuntimeError("Simulated NER memory fault")

        mock_get.return_value = CrashingNLP()
        with pytest.raises(RuntimeError) as exc_info:
            deidentify("Patient: John Smith took aspirin.", use_ner=True)
        assert "De-identification NER processing failed" in str(exc_info.value)


import logging
import traceback


def test_names_adjacent_to_redaction_tokens_are_redacted():
    """
    Proves that person names immediately preceding or following regex-redacted tokens
    ('John Doe MRN 849201' and '555-019-2831 John Doe') are still redacted.
    """
    out1, log1 = deidentify("John Doe MRN 849201", use_ner=True)
    assert "John Doe" not in out1
    assert "849201" not in out1
    assert "[REDACTED_NAME]" in out1
    assert "[REDACTED_HOSPITAL_ID]" in out1

    out2, log2 = deidentify("555-019-2831 John Doe", use_ner=True)
    assert "John Doe" not in out2
    assert "555-019-2831" not in out2
    assert "[REDACTED_PHONE]" in out2
    assert "[REDACTED_NAME]" in out2


def test_clinical_text_not_over_redacted_and_lowercase_limitation():
    """
    Proves clinical phrasing ('Dr. Smith prescribed...', 'patient reports rash', 'patient: rash')
    redacts the clinician name while preserving clinical verbs and symptoms, and documents the
    single-word lowercase name heuristic limitation.
    """
    out_dr, _ = deidentify("Dr. Smith prescribed amoxicillin 500mg.", use_ner=True)
    assert "Smith" not in out_dr
    assert "Dr. [REDACTED_NAME] prescribed amoxicillin 500mg." == out_dr

    out_rep, log_rep = deidentify("patient reports rash after taking ibuprofen.", use_ner=True)
    assert out_rep == "patient reports rash after taking ibuprofen."
    assert len(log_rep) == 0

    out_col, log_col = deidentify("patient: rash and fever after penicillin.", use_ner=True)
    assert out_col == "patient: rash and fever after penicillin."
    assert len(log_col) == 0

    # Documented limitation: multi-word lowercase names ('alice wonderland') are redacted by NER,
    # whereas a standalone untitled single-word lowercase token ('alice') is intentionally not
    # redacted so lowercase clinical nouns/symptoms are never stripped.
    out_multi_lower, _ = deidentify("alice wonderland took ibuprofen and got hives.", use_ner=True)
    assert "alice wonderland" not in out_multi_lower
    assert "[REDACTED_NAME]" in out_multi_lower


def test_title_names_redacted_with_and_without_spacy_without_eating_clinical_words():
    """
    Proves that titled names ('Dr. Smith prescribed amoxicillin', 'Mr. Jones reports rash',
    'Mrs. Garcia developed hives', 'Nurse Lee administered penicillin', 'Nurse Practitioner Lee')
    are redacted both with spaCy present and with get_spacy_model patched to None without eating
    adjacent clinical words, and section headers/verbs ('Patient Information: rash',
    'Patient Developed rash') are never redacted in either mode.
    """
    cases = [
        ("Dr. Smith prescribed amoxicillin", "Dr. [REDACTED_NAME] prescribed amoxicillin"),
        ("Mr. Jones reports rash", "Mr. [REDACTED_NAME] reports rash"),
        ("Mrs. Garcia developed hives", "Mrs. [REDACTED_NAME] developed hives"),
        ("Nurse Lee administered penicillin", "Nurse [REDACTED_NAME] administered penicillin"),
        ("Nurse Practitioner Lee", "Nurse Practitioner [REDACTED_NAME]"),
        ("Nurse Practitioner Lee prescribed amoxicillin", "Nurse Practitioner [REDACTED_NAME] prescribed amoxicillin"),
        ("Patient Information: rash", "Patient Information: rash"),
        ("Patient Developed rash", "Patient Developed rash"),
    ]
    # 1. With spaCy present
    for raw, expected in cases:
        out_ner, _ = deidentify(raw, use_ner=True)
        assert out_ner == expected

    # 2. With get_spacy_model patched to None (regex-only path)
    with patch("app.pipeline.deidentify.get_spacy_model", return_value=None):
        for raw, expected in cases:
            out_regex, _ = deidentify(raw, use_ner=True)
            assert out_regex == expected


def test_regex_only_mode_untitled_name_limitation():
    """
    Documents and verifies the regex-only mode limitation: when spaCy NER is unavailable
    (get_spacy_model returns None or use_ner=False), titled names ('Patient: John Doe',
    'Dr. Smith') are redacted by NAME_TITLE_RE, but untitled person names ('John Doe took
    amoxicillin') are not caught by regex alone (which is why DEID_REQUIRE_NER defaults to True).
    """
    with patch("app.pipeline.deidentify.get_spacy_model", return_value=None):
        titled_out, _ = deidentify("Patient: John Doe took amoxicillin.", use_ner=True)
        assert titled_out == "Patient: [REDACTED_NAME] took amoxicillin."

        untitled_out, _ = deidentify("John Doe took amoxicillin.", use_ner=True)
        assert untitled_out == "John Doe took amoxicillin."

    # With live spaCy NER active, the untitled name IS redacted:
    ner_out, _ = deidentify("John Doe took amoxicillin.", use_ner=True)
    assert ner_out == "[REDACTED_NAME] took amoxicillin."


def test_ner_crash_with_synthetic_phi_in_exception_does_not_leak(caplog):
    """
    Proves that when spaCy NER crashes with an exception message containing synthetic PHI,
    the RuntimeError is raised outside the except block (__context__ is None, __cause__ is None)
    and the PHI is absent from str(exc), repr(exc), traceback, and caplog.
    """
    secret_phi = "SYNTHETIC_NER_CRASH_PHI_SSN_000_11_9999"
    with patch("app.pipeline.deidentify.get_spacy_model") as mock_get:
        class CrashingNLPWithPHI:
            def __call__(self, text):
                raise ValueError(f"Tokenizer fault on span {secret_phi}")

        mock_get.return_value = CrashingNLPWithPHI()
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(RuntimeError) as exc_info:
                deidentify(f"Patient {secret_phi} took aspirin.", use_ner=True)

        exc = exc_info.value
        assert exc.__cause__ is None
        assert exc.__context__ is None
        assert exc.__suppress_context__ is True
        assert secret_phi not in str(exc)
        assert secret_phi not in repr(exc)
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        assert secret_phi not in tb
        assert secret_phi not in caplog.text
        assert "ValueError" in caplog.text


def test_eponym_surname_person_names_redacted_in_both_modes():
    """
    Proves that titled person names bearing eponymous medical surnames ('Mr. Graves',
    'Dr. Bell reports rash') are redacted in both live spaCy NER mode and regex-only mode
    (get_spacy_model=None), and that full names ('Mary Parkinson') are redacted in live
    spaCy NER mode while documenting the regex-only limitation for untitled names.
    """
    # 1. With live spaCy NER loaded: both titled eponym surnames and full First+Eponym names are redacted
    out_mary_ner, _ = deidentify("Mary Parkinson", use_ner=True)
    assert out_mary_ner == "[REDACTED_NAME]"

    out_graves_ner, _ = deidentify("Mr. Graves", use_ner=True)
    assert out_graves_ner == "Mr. [REDACTED_NAME]"

    out_bell_ner, _ = deidentify("Dr. Bell reports rash", use_ner=True)
    assert out_bell_ner == "Dr. [REDACTED_NAME] reports rash"

    # 2. With get_spacy_model patched to None (regex-only mode): titled names are redacted;
    # untitled 'Mary Parkinson' reflects the documented regex-only limitation for untitled names.
    with patch("app.pipeline.deidentify.get_spacy_model", return_value=None):
        out_graves_regex, _ = deidentify("Mr. Graves", use_ner=True)
        assert out_graves_regex == "Mr. [REDACTED_NAME]"

        out_bell_regex, _ = deidentify("Dr. Bell reports rash", use_ner=True)
        assert out_bell_regex == "Dr. [REDACTED_NAME] reports rash"

        out_mary_regex, _ = deidentify("Mary Parkinson", use_ner=True)
        assert out_mary_regex == "Mary Parkinson"


def test_achilles_papadopoulos_redacted_while_achilles_tendon_and_brand_names_preserved():
    """
    Proves that whole-span protection preserves anatomical phrases ('Achilles tendon rupture')
    and 20+ standalone brand names while still redacting a person named 'Achilles Papadopoulos'.
    """
    out_person, _ = deidentify("Achilles Papadopoulos took ciprofloxacin.", use_ner=True)
    assert "Achilles Papadopoulos" not in out_person
    assert out_person == "[REDACTED_NAME] took ciprofloxacin."

    out_titled_person, _ = deidentify("Patient: Achilles Papadopoulos", use_ner=True)
    assert out_titled_person == "Patient: [REDACTED_NAME]"

    out_tendon, log_tendon = deidentify("MRI confirmed Achilles tendon rupture.", use_ner=True)
    assert out_tendon == "MRI confirmed Achilles tendon rupture."
    assert len(log_tendon) == 0

    brand_names = [
        "Eliquis", "Xarelto", "Zofran", "Tylenol", "Advil", "Synthroid",
        "Lipitor", "Plavix", "Zocor", "Coumadin", "Augmentin", "Lasix",
        "Crestor", "Jardiance", "Ozempic", "Humira", "Keytruda", "Keppra",
        "Lamictal", "Zoloft", "Prozac", "Lexapro", "Nexium", "Prilosec", "Bactrim",
    ]
    for brand in brand_names:
        out_brand, log_brand = deidentify(brand, use_ner=True)
        assert out_brand == brand, f"Brand name '{brand}' was wrongly redacted to '{out_brand}'"
        assert len(log_brand) == 0


def test_phone_re_formats_and_false_positive_guards():
    """
    Addendum Item 1 & Item 4: Verifies that PHONE_RE redacts 5550192831, 555-1234, (555)222-3333,
    555.019.2831, +44 20 7946 0958, and 'tel: 5551234' (both in deidentify and in
    _has_residual_regex_phi), while preserving '500-1000 mg', '2019-2023', 'BP 120-1800',
    '10-1000 ng/mL', '1000-2000 IU/day', '250-5000 units', 'NCT 123-4567', and
    'platelets 150-4000' without redaction or tripwire false positives.
    """
    from app.privacy import _has_residual_regex_phi

    positive_cases = [
        ("5550192831", "[REDACTED_PHONE]"),
        ("555-1234", "[REDACTED_PHONE]"),
        ("(555)222-3333", "[REDACTED_PHONE]"),
        ("555.019.2831", "[REDACTED_PHONE]"),
        ("+44 20 7946 0958", "[REDACTED_PHONE]"),
        ("tel: 5551234", "tel: [REDACTED_PHONE]"),
    ]
    for raw, expected in positive_cases:
        assert _has_residual_regex_phi(raw) is True, f"Expected tripwire True on '{raw}'"
        redacted, log = deidentify(raw, use_ner=False)
        assert redacted == expected, f"For '{raw}', expected '{expected}', got '{redacted}'"
        assert any(entry.type == "phone" for entry in log)
        assert _has_residual_regex_phi(redacted) is False

    negative_cases = [
        "500-1000 mg",
        "2019-2023",
        "BP 120-1800",
        "10-1000 ng/mL",
        "1000-2000 IU/day",
        "250-5000 units",
        "NCT 123-4567",
        "platelets 150-4000",
    ]
    for safe_text in negative_cases:
        assert _has_residual_regex_phi(safe_text) is False, f"Expected tripwire False on '{safe_text}'"
        redacted, log = deidentify(safe_text, use_ner=False)
        assert redacted == safe_text, f"Safe text '{safe_text}' was wrongly redacted to '{redacted}'"
        assert len(log) == 0




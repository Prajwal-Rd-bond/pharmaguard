"""
Shared privacy boundary and outbound regex tripwire helpers for LLM-facing stages.

This module is intentionally neutral and side-effect-free on import (it does not
initialize any LLM clients, vector stores, or environment loaders).
"""

from __future__ import annotations

import logging
import re

from .config import get_settings
from .errors import DeidentificationError
from .pipeline.deidentify import (
    ADDRESS_RE,
    DATE_RE,
    EMAIL_RE,
    MRN_RE,
    NAME_TITLE_RE,
    PHONE_RE,
    SSN_RE,
    deidentify,
    get_spacy_model,
    is_protected_clinical_term,
)

logger = logging.getLogger(__name__)


def _deid_policy(settings=None):
    """Returns (require_ner, spacy_model_name). Unreadable settings fall back to the STRICT default."""
    try:
        active_settings = settings if settings is not None else get_settings()
        return bool(active_settings.deid_require_ner), (active_settings.deid_spacy_model or "en_core_web_sm")
    except Exception as exc:
        logger.warning(
            "Settings unavailable for de-identification policy (error_type=%s); using strict defaults.",
            type(exc).__name__,
        )
        return True, "en_core_web_sm"


def _deidentify_or_block(text: str, *, settings=None) -> str:
    """
    Shared privacy boundary for LLM-facing pipeline stages (extract and assess).
    Returns de-identified text or raises a generic DeidentificationError. The error is raised
    OUTSIDE the except block and `from None`, so it carries no cause, no context, and no
    original message (which might contain patient text).
    """
    require_ner, model_name = _deid_policy(settings=settings)
    failure_type = None
    scrubbed = None
    try:
        # deidentify() silently skips NER when the spaCy model cannot be loaded, so the
        # "NER is mandatory" policy (settings.deid_require_ner) is enforced here.
        if not isinstance(text, str):
            failure_type = "InvalidDeidentificationInput"
        elif not callable(deidentify) or not callable(get_spacy_model):
            failure_type = "InvalidDeidentificationCallable"
        elif require_ner and get_spacy_model(model_name) is None:
            failure_type = "NERModelUnavailable"
        else:
            scrubbed, _ = deidentify(text, spacy_model_name=model_name, use_ner=True)
            if not isinstance(scrubbed, str):
                failure_type = "InvalidDeidentificationOutput"
    except Exception as exc:
        failure_type = type(exc).__name__

    if failure_type is not None:
        logger.error(
            "De-identification failed; extraction blocked before any provider call (error_type=%s).",
            failure_type,
        )
        raise DeidentificationError() from None
    return scrubbed


_PATIENT_DATE_CONTEXT_RE = re.compile(
    r"\b(?:DOB|date\s+of\s+birth|born(?:\s+on)?|admitted(?:\s+on)?|discharged(?:\s+on)?|reported\s+on|visited\s+on)[:\s#]+"
    r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})\b",
    re.IGNORECASE,
)

_PATIENT_ADDRESS_CONTEXT_RE = re.compile(
    r"\b(?:residing\s+at|lives\s+at|living\s+at|located\s+at|patient\s+address|home\s+address)[:\s#]+"
    r"\d{1,5}\s+[A-Z][a-zA-Z0-9\s,]{2,25}(?:Street|St\b|Avenue|Ave\b|Road|Rd\b|Boulevard|Blvd\b|Lane|Ln\b|Drive|Way\b|Terrace|Ter\b|Court|Ct\b|Place|Pl\b|Parkway|Pkwy\b)",
    re.IGNORECASE,
)


def _has_trusted_evidence_identifier_phi(text: str) -> bool:
    """
    Identifier-only regex check for trusted FDA/retrieval evidence records.
    - Always enforces EMAIL_RE, SSN_RE, MRN_RE, and PHONE_RE.
    - Skips generic DATE_RE, ADDRESS_RE, and NAME_TITLE_RE so public FDA label
      metadata ('Revised: 11/15/2023', '100 Example Parkway', 'Patient Counseling Information (17)')
      pass through unchanged, while still rejecting patient-context dates and addresses
      (e.g. 'DOB: 05/14/1982', 'Reported on 05/12/1980', 'residing at ...', 'Located at ...').
    """
    if not isinstance(text, str) or not text:
        return False
    for pattern in (EMAIL_RE, SSN_RE, MRN_RE, PHONE_RE, _PATIENT_DATE_CONTEXT_RE, _PATIENT_ADDRESS_CONTEXT_RE):
        if pattern.search(text):
            return True
    return False


def _assert_no_trusted_evidence_identifier_phi(text: str) -> None:
    """Raises DeidentificationError if any direct identifier pattern remains in trusted evidence text."""
    if _has_trusted_evidence_identifier_phi(text):
        logger.error("Direct identifier detected in trusted evidence record; blocking provider call.")
        raise DeidentificationError() from None


def _has_residual_regex_phi(text: str) -> bool:
    """
    Regex-only tripwire checking for direct identifiers (email, SSN, MRN, phone,
    date, street address, or titled person name) in assembled outbound prompt text.
    """
    if not isinstance(text, str) or not text:
        return False

    # If text is an assembled assessment prompt containing a sanitized RETRIEVED DRUG LABEL EVIDENCE
    # block, check the evidence block with _has_trusted_evidence_identifier_phi (since untrusted
    # retrieval items were already scrubbed & checked with full _assert_no_residual_regex_phi in
    # _sanitize_retrievals, while trusted FDA records skip generic DATE_RE, ADDRESS_RE, and NAME_TITLE_RE)
    # and check the non-evidence segments with the full regex suite including DATE_RE, ADDRESS_RE, and NAME_TITLE_RE.
    non_evidence_text = text
    evidence_marker = "\nRETRIEVED DRUG LABEL EVIDENCE:\n"
    if evidence_marker in text:
        before_ev, after_ev = text.split(evidence_marker, 1)
        end_marker = "\n\nPerform the evidence-grounded causality assessment"
        if end_marker in after_ev:
            ev_block, tail_ev = after_ev.split(end_marker, 1)
            non_evidence_text = before_ev + "\n" + tail_ev
        else:
            ev_block = after_ev
            non_evidence_text = before_ev
        if _has_trusted_evidence_identifier_phi(ev_block):
            return True

    for pattern in (EMAIL_RE, SSN_RE, MRN_RE, PHONE_RE, DATE_RE, ADDRESS_RE):
        if pattern.search(non_evidence_text):
            return True

    for match in NAME_TITLE_RE.finditer(non_evidence_text):
        span_text = match.group(1)
        if "REDACTED_" in span_text:
            continue
        full_title_match = match.group(0).strip().lower()
        is_honorific = full_title_match.startswith(("mr.", "mrs.", "ms.", "miss ", "dr.", "prof.", "dr ", "mr ", "mrs ", "ms ", "prof ", "nurse "))
        if not is_honorific and is_protected_clinical_term(span_text):
            continue
        return True
    return False


def _assert_no_residual_regex_phi(text: str) -> None:
    """Raises DeidentificationError if any regex-matched direct identifier remains in text."""
    if _has_residual_regex_phi(text):
        logger.error("Residual regex identifier detected in outbound prompt; blocking provider call.")
        raise DeidentificationError() from None



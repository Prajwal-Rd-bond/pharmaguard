"""
Module 3 — De-identification Engine.

Baseline implementation: regex/heuristic PII scrubbing (no external calls, works offline).
Swap in a clinical NER model (e.g. a fine-tuned spaCy/ClinicalBERT NER pipeline) for
production-grade recall; this is a functional starting point, not a compliance guarantee.
"""

import re

EMAIL_RE = re.compile(r"[\w\.\-]+@[\w\-]+\.[\w\.\-]+")
PHONE_RE = re.compile(r"(\+?\d[\d\-\s\(\)]{7,}\d)")
MRN_RE = re.compile(r"\b(MRN|Hospital ID|Patient ID)[:\s#]*([A-Za-z0-9\-]+)\b", re.IGNORECASE)
NAME_RE = re.compile(r"\b(Mr\.|Mrs\.|Ms\.|Dr\.|Patient:)\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)")
ADDRESS_RE = re.compile(r"\d{1,5}\s+[A-Z][a-zA-Z]+\s+(Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr)\b")


def deidentify(text: str):
    log = []

    def _redact(pattern, label, text, group=0):
        def repl(m):
            log.append({"type": label, "span": m.group(group)})
            return f"[REDACTED_{label.upper()}]"

        return pattern.sub(repl, text)

    text = _redact(EMAIL_RE, "email", text)
    text = _redact(PHONE_RE, "phone", text)
    text = _redact(MRN_RE, "hospital_id", text, group=2)
    text = _redact(NAME_RE, "name", text, group=2)
    text = _redact(ADDRESS_RE, "address", text)

    return text, log

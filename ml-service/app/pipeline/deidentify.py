"""
Module 3 — De-identification Engine.

Two passes, run in this order:
1. Regex catches structured formats (email, phone, MRN/hospital/patient IDs) that a narrative-text
   NER model tends to miss or fragment, since these follow a fixed shape rather than natural language.
2. A clinical de-identification NER model (obi/deid_roberta_i2b2, fine-tuned on the i2b2 2014
   de-identification challenge corpus) tags names, locations, professions, and other PHI spans
   directly from the (already partially-redacted) text.

Running regex first avoids the NER model fragmenting things like emails into spurious PATIENT
entities; running NER second means it only has to find what the regex pass couldn't.

AGE is a required clinical field downstream (Module 4 extraction schema), not identifying PII in
isolation, so it is kept as-is unless >=90 — matching HIPAA Safe Harbor, which permits ages 0-89
and requires only ages 90+ to be redacted/aggregated.

Redacted spans are logged (not displayed in normal UI paths) for audit, per Epic 3's AC.
"""

import os
import re
from functools import lru_cache

EMAIL_RE = re.compile(r"[\w\.\-]+@[\w\-]+\.[\w\.\-]+")
PHONE_RE = re.compile(r"(\+?\d[\d\-\s\(\)]{7,}\d)")
MRN_RE = re.compile(r"\b(MRN|Hospital ID|Patient ID)[:\s#]*([A-Za-z0-9\-]+)\b", re.IGNORECASE)

NER_MODEL_NAME = os.getenv("DEID_NER_MODEL", "obi/deid_roberta_i2b2")
AGE_REDACT_THRESHOLD = 90


@lru_cache(maxsize=1)
def _get_ner_pipeline():
    from transformers import pipeline

    return pipeline("ner", model=NER_MODEL_NAME, aggregation_strategy="simple")


def _regex_redact(pattern, label, text, group=0):
    log = []

    def repl(m):
        log.append({"type": label, "span": m.group(group)})
        return f"[REDACTED_{label.upper()}]"

    return pattern.sub(repl, text), log


def _merge_adjacent(entities):
    """Collapse consecutive same-type entities separated only by whitespace (tokenizer artifact)."""
    merged = []
    for ent in sorted(entities, key=lambda e: e["start"]):
        if merged and merged[-1]["entity_group"] == ent["entity_group"] and ent["start"] - merged[-1]["end"] <= 1:
            merged[-1]["end"] = ent["end"]
        else:
            merged.append(dict(ent))
    return merged


def _should_redact_age(span_text: str) -> bool:
    digits = re.search(r"\d+", span_text)
    return bool(digits) and int(digits.group()) >= AGE_REDACT_THRESHOLD


def _ner_redact(text: str):
    log = []
    try:
        entities = _get_ner_pipeline()(text)
    except Exception as exc:  # model unavailable/download failed — fail open, regex pass still ran
        return text, log, str(exc)

    entities = _merge_adjacent(entities)

    for ent in sorted(entities, key=lambda e: e["start"], reverse=True):
        label = ent["entity_group"].lower()
        span = text[ent["start"] : ent["end"]]

        if label == "age" and not _should_redact_age(span):
            continue

        log.append({"type": label, "span": span.strip()})
        text = text[: ent["start"]] + f"[REDACTED_{label.upper()}]" + text[ent["end"] :]

    log.reverse()  # restore left-to-right order for readable audit logs
    return text, log, None


def deidentify(text: str):
    log = []

    text, l = _regex_redact(EMAIL_RE, "email", text)
    log += l
    text, l = _regex_redact(PHONE_RE, "phone", text)
    log += l
    text, l = _regex_redact(MRN_RE, "hospital_id", text, group=2)
    log += l

    text, ner_log, error = _ner_redact(text)
    log += ner_log
    if error:
        log.append({"type": "deid_model_error", "span": error})

    return text, log

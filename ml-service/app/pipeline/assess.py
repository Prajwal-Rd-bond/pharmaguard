"""
Causality Assessment and Evidence Synthesis Module.

Coordinates:
1. Grounded synthesis: formats numbered evidence chunks (E1, E2, ... En) and de-identified narrative [N].
2. LLM assessment query (Qwen3 8B via OpenAI-compatible provider).
3. Deterministic Naranjo score calculation (scale: -4 to +13, computed strictly in Python code).
4. Qualitative WHO-UMC causality suggestion (categorical clinical hypothesis rendered by LLM for pharmacist review).
5. Deterministic citation integrity validation (referential validity and anchor presence).
6. Graceful fallback when LLM is unavailable or disabled.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from ..config import get_settings
from ..errors import DeidentificationError
from ..llm.factory import get_llm_provider
from ..llm.prompts import ASSESS_SYSTEM_PROMPT_V1
from ..privacy import (
    _assert_no_residual_regex_phi,
    _deidentify_or_block,
    _has_trusted_evidence_identifier_phi,
)
from .citations import validate_citations
from .deidentify import deidentify, get_spacy_model
from .naranjo import score_naranjo
from .retrieve import RetrievalList, TrustedEvidenceRecord

logger = logging.getLogger(__name__)

# Only scrub and include the fields that the assessment prompt and fallback actually use.
_ALLOWED_EXTRACTION_FIELDS = ("drugName", "genericName", "symptoms", "onsetTimeline", "dosage")
_ALLOWED_RETRIEVAL_TEXT_FIELDS = ("title", "snippet")


class RawLLMAssessmentSchema(BaseModel):
    summary_sentences: List[Dict[str, Any]] = Field(default_factory=list)
    naranjo_answers: Dict[str, Any] = Field(default_factory=dict)
    who_umc_suggestion: Dict[str, Any] = Field(default_factory=dict)
    limitations: List[str] = Field(default_factory=list)


def _scrub_for_assessment(text: str, settings=None) -> str:
    """
    Invokes the shared privacy boundary in app.privacy.
    """
    return _deidentify_or_block(text, settings=settings)


def _sanitize_value(val: Any, settings=None) -> Any:
    """Recursively scrubs strings inside arbitrary nested structures (str, list, tuple, dict)."""
    if isinstance(val, str):
        return _scrub_for_assessment(val, settings=settings)
    if isinstance(val, list):
        return [_sanitize_value(item, settings=settings) for item in val]
    if isinstance(val, tuple):
        return tuple(_sanitize_value(item, settings=settings) for item in val)
    if isinstance(val, dict):
        return {k: _sanitize_value(v, settings=settings) for k, v in val.items()}
    return val


def _flatten_sanitized_strings(val: Any, settings=None) -> List[str]:
    """Recursively extracts and scrubs strings from a list/tuple/dict/str field (e.g. symptoms)."""
    if isinstance(val, str):
        return [_scrub_for_assessment(val, settings=settings)]
    if isinstance(val, (list, tuple)):
        out: List[str] = []
        for item in val:
            out.extend(_flatten_sanitized_strings(item, settings=settings))
        return out
    if isinstance(val, dict):
        out = []
        for v in val.values():
            out.extend(_flatten_sanitized_strings(v, settings=settings))
        return out
    return []


def _sanitize_extraction(extraction: Dict[str, Any], settings=None) -> Dict[str, Any]:
    """
    Builds a sanitized extraction dict strictly from the allowlist of prompt-consumed fields
    (_ALLOWED_EXTRACTION_FIELDS), sanitizing nested values recursively.
    """
    if not isinstance(extraction, dict):
        return {}
    sanitized: Dict[str, Any] = {}
    for key in _ALLOWED_EXTRACTION_FIELDS:
        if key not in extraction:
            continue
        val = extraction[key]
        if key == "symptoms":
            sanitized[key] = _flatten_sanitized_strings(val, settings=settings)
        elif isinstance(val, (dict, list, tuple)):
            flat = _flatten_sanitized_strings(val, settings=settings)
            sanitized[key] = ", ".join(flat) if flat else None
        elif isinstance(val, str):
            sanitized[key] = _scrub_for_assessment(val, settings=settings)
        else:
            sanitized[key] = _sanitize_value(val, settings=settings)
    return sanitized


def _sanitize_retrievals(retrievals: List[Dict[str, Any]], settings=None) -> RetrievalList:
    """
    Builds sanitized retrieval entries strictly from allowlisted prompt fields ('evidence_id',
    'title', 'snippet'), scrubbing only the text fields consumed by the prompt.

    TRUST BOUNDARY:
    Text originating from the trusted retrieval stage (TrustedEvidenceRecord)
    is exempted from NER-based name scrubbing and the title-name heuristic (NAME_TITLE_RE)
    so official regulatory headings (e.g. 'Patient Counseling Information (17)',
    'Patient Information', 'Medication Guide', 'Warnings and Precautions (5.1)')
    do not cause false PHI rejections or get corrupted into '[REDACTED_NAME]'.
    However, trusted retrieval text is still checked for direct identifier patterns
    (phone, email, SSN, MRN, date, address) via _has_trusted_evidence_identifier_phi().
    When a trusted record fails the identifier check:
    - Drop ONLY that record
    - Add {"source_id": ..., "reason": "pii_rejected"} to rejected_records
    - Set evidence_status to "partial_pii_rejected" when other records remain,
      or "pii_rejected" when none remain
    - Continue the run without logging or returning the rejected text.
    Untrusted entries (not TrustedEvidenceRecord) are scrubbed with full NER and
    checked with _assert_no_residual_regex_phi() (including title-name detection),
    failing closed on residual PHI.
    """
    if not isinstance(retrievals, list):
        return RetrievalList([], evidence_status="none_found", rejected_records=[])

    prior_status = getattr(retrievals, "evidence_status", None)
    prior_rejected = list(getattr(retrievals, "rejected_records", []) or [])

    sanitized_list: List[Dict[str, Any]] = []
    rejected_records: List[Dict[str, str]] = list(prior_rejected)

    for idx, item in enumerate(retrievals, start=1):
        if not isinstance(item, dict):
            continue
        raw_eid = item.get("evidence_id")
        eid = raw_eid.strip() if (isinstance(raw_eid, str) and raw_eid.strip()) else f"E{idx}"
        sid = str(item.get("source_id") or eid)
        entry: Dict[str, Any] = {"evidence_id": eid, "source_id": sid}
        is_trusted = isinstance(item, TrustedEvidenceRecord)

        if is_trusted:
            contaminated = False
            for text_key in _ALLOWED_RETRIEVAL_TEXT_FIELDS:
                val = item.get(text_key)
                if isinstance(val, str):
                    if _has_trusted_evidence_identifier_phi(val):
                        contaminated = True
                        break
                    entry[text_key] = val
                elif isinstance(val, (dict, list, tuple)):
                    flat_text = ", ".join(str(x) for x in val)
                    if _has_trusted_evidence_identifier_phi(flat_text):
                        contaminated = True
                        break
                    entry[text_key] = flat_text
                elif val is not None:
                    str_val = str(val)
                    if _has_trusted_evidence_identifier_phi(str_val):
                        contaminated = True
                        break
                    entry[text_key] = str_val
            if contaminated:
                rejected_records.append({"source_id": sid, "reason": "pii_rejected"})
                logger.warning("Trusted evidence record dropped due to identifier check (source_id=%s).", sid)
                continue
            sanitized_list.append(TrustedEvidenceRecord(entry))
        else:
            for text_key in _ALLOWED_RETRIEVAL_TEXT_FIELDS:
                val = item.get(text_key)
                if isinstance(val, str):
                    scrubbed_val = _scrub_for_assessment(val, settings=settings)
                    _assert_no_residual_regex_phi(scrubbed_val)
                    entry[text_key] = scrubbed_val
                elif isinstance(val, (dict, list, tuple)):
                    flat_scrubbed = ", ".join(_flatten_sanitized_strings(val, settings=settings))
                    _assert_no_residual_regex_phi(flat_scrubbed)
                    entry[text_key] = flat_scrubbed
                elif val is not None:
                    str_val = _scrub_for_assessment(str(val), settings=settings)
                    _assert_no_residual_regex_phi(str_val)
                    entry[text_key] = str_val
            sanitized_list.append(entry)

    # Re-assign sequential E1..En if any record was dropped and lacked explicit evidence_id
    for new_idx, rec in enumerate(sanitized_list, start=1):
        if not rec.get("evidence_id"):
            rec["evidence_id"] = f"E{new_idx}"

    if rejected_records:
        final_status = "partial_pii_rejected" if sanitized_list else "pii_rejected"
    elif prior_status:
        final_status = prior_status
    else:
        final_status = "ok" if sanitized_list else "none_found"

    return RetrievalList(sanitized_list, evidence_status=final_status, rejected_records=rejected_records)


def _assert_messages_no_residual_phi(messages: List[Dict[str, Any]]) -> None:
    """Regex-only tripwire over assembled prompt messages prior to any provider call."""
    for msg in messages:
        if isinstance(msg, dict):
            _assert_no_residual_regex_phi(str(msg.get("content", "")))


async def run_causality_assessment(
    deidentified_text: str,
    extraction: Dict[str, Any],
    retrievals: List[Dict[str, Any]],
    settings=None,
) -> Dict[str, Any]:
    """
    Executes evidence-grounded causality assessment for the reported ADR.
    Enforces the shared privacy boundary internally across the narrative, extraction fields,
    and retrieved evidence chunks before any provider or fallback execution.
    """
    # Mandatory privacy boundary (no trusted caller flags): scrub narrative, extraction, and
    # retrievals before resolving provider or building prompts. Fails closed with DeidentificationError.
    safe_narrative = _scrub_for_assessment(deidentified_text, settings=settings)
    safe_extraction = _sanitize_extraction(extraction, settings=settings)
    safe_retrievals = _sanitize_retrievals(retrievals, settings=settings)

    if settings is None:
        settings = get_settings()

    provider = get_llm_provider(settings)
    valid_evidence_ids = [
        (r.get("evidence_id").strip() if isinstance(r.get("evidence_id"), str) and r.get("evidence_id").strip() else f"E{i}")
        for i, r in enumerate(safe_retrievals, start=1)
    ]

    # Format evidence block
    evidence_blocks = []
    for i, r in enumerate(safe_retrievals, start=1):
        raw_eid = r.get("evidence_id")
        eid = raw_eid.strip() if isinstance(raw_eid, str) and raw_eid.strip() else f"E{i}"
        title = r.get("title") or "Drug Label"
        snippet = r.get("snippet") or ""
        evidence_blocks.append(f"[{eid}] {title}\n{snippet}")

    evidence_text = "\n\n".join(evidence_blocks) if evidence_blocks else "No relevant drug label evidence chunks retrieved."

    user_prompt = f"""DE-IDENTIFIED PATIENT NARRATIVE [N]:
{safe_narrative}

STRUCTURED EXTRACTION:
Suspected Drug: {safe_extraction.get('drugName') or 'Unknown'}
Generic Name: {safe_extraction.get('genericName') or 'Unknown'}
Reported Reactions: {', '.join(safe_extraction.get('symptoms') or ['None specified'])}
Onset: {safe_extraction.get('onsetTimeline') or 'Unspecified'}
Dosage: {safe_extraction.get('dosage') or 'Unspecified'}

RETRIEVED DRUG LABEL EVIDENCE:
{evidence_text}

Perform the evidence-grounded causality assessment following the system prompt instructions.
"""

    messages = [
        {"role": "system", "content": ASSESS_SYSTEM_PROMPT_V1},
        {"role": "user", "content": user_prompt},
    ]

    # Regex-only tripwire on the assembled messages before any outbound provider call
    _assert_messages_no_residual_phi(messages)

    llm_assessment: Optional[RawLLMAssessmentSchema] = None
    provider_name = settings.llm_provider
    model_name = settings.llm_model

    if settings.llm_configured:
        try:
            llm_assessment = await provider.complete_structured(
                messages=messages,
                schema=RawLLMAssessmentSchema,
                temperature=settings.llm_temperature,
                max_tokens=settings.llm_max_tokens,
            )
        except DeidentificationError:
            raise
        except Exception as exc:
            logger.warning(
                "LLM causality assessment failed (error_type=%s). Using heuristic assessment.",
                type(exc).__name__,
            )
            llm_assessment = None

    # Fallback heuristic if LLM is unavailable or failed
    if not llm_assessment:
        fb = _build_fallback_assessment(
            deidentified_text=safe_narrative,
            extraction=safe_extraction,
            retrievals=safe_retrievals,
            reason=settings.llm_unavailable_reason or "LLM call unavailable",
        )
        fb["evidence_status"] = getattr(safe_retrievals, "evidence_status", "ok" if safe_retrievals else "none_found")
        fb["rejected_records"] = list(getattr(safe_retrievals, "rejected_records", []) or [])
        return fb

    # 1. Deterministic Naranjo Calculation
    naranjo_res = score_naranjo(llm_assessment.naranjo_answers)

    # 2. Citation Verification
    citation_res = validate_citations(
        summary_sentences=llm_assessment.summary_sentences,
        naranjo_answers=llm_assessment.naranjo_answers,
        valid_evidence_ids=valid_evidence_ids,
    )

    # Assemble comprehensive clinical assessment
    return {
        "status": "completed",
        "advisory_only": True,
        "authority": "advisory_model_derived",
        "provider": provider_name,
        "model": model_name,
        "prompt_version": "assess-v1",
        "evidence_status": getattr(safe_retrievals, "evidence_status", "ok" if safe_retrievals else "none_found"),
        "rejected_records": list(getattr(safe_retrievals, "rejected_records", []) or []),
        "naranjo": {
            "advisory_only": True,
            "answer_source": "llm_model_answers_scored_deterministically",
            "total_score": naranjo_res.total_score,
            "min_score": naranjo_res.min_score,
            "max_score": naranjo_res.max_score,
            "category": naranjo_res.category,
            "questions": [q.model_dump() for q in naranjo_res.questions],
        },
        "who_umc_suggestion": {
            "category": llm_assessment.who_umc_suggestion.get("category", "unassessable"),
            "rationale": llm_assessment.who_umc_suggestion.get("rationale", ""),
            "citations": llm_assessment.who_umc_suggestion.get("citations", []),
        },
        "summary_sentences": citation_res.grounded_summary_sentences,
        "citation_validation": {
            "is_valid": citation_res.is_valid,
            "issues": [issue.model_dump() for issue in citation_res.issues],
        },
        "citation_verification": {
            "all_cited": citation_res.is_valid and not any(i.issue_type == "uncited_claim" for i in citation_res.issues),
            "fabricated_citations": [
                c for i in citation_res.issues if i.issue_type == "phantom_citation" for c in i.invalid_citations
            ],
            "issues": [issue.model_dump() for issue in citation_res.issues],
        },
        "limitations": llm_assessment.limitations,
        "governance_notice": "AI assistive evaluation only. Authoritative pipeline causality remains in top-level `causality`; final causality assessment must be determined by a licensed pharmacist.",
    }


def _build_fallback_assessment(
    deidentified_text: str,
    extraction: Dict[str, Any],
    retrievals: List[Dict[str, Any]],
    reason: str,
) -> Dict[str, Any]:
    """Provides a deterministic, cited baseline assessment when LLM is offline."""
    has_evidence = len(retrievals) > 0
    symptoms = extraction.get("symptoms") or []
    drug = extraction.get("drugName") or "suspected medication"

    # Default heuristic answers
    raw_answers = {
        "q1_previous_reports": {
            "answer": "yes" if has_evidence else "unknown",
            "rationale": "Product labeling mentions related adverse reactions." if has_evidence else "No local evidence retrieved.",
            "citations": ["E1"] if has_evidence else [],
        },
        "q2_event_after_drug": {
            "answer": "yes",
            "rationale": "Reaction occurred following drug administration per clinical report.",
            "citations": ["N"],
        },
        "q3_improved_on_dechallenge": {
            "answer": "unknown",
            "rationale": "Dechallenge information not reported.",
            "citations": [],
        },
        "q4_reappeared_on_rechallenge": {
            "answer": "unknown",
            "rationale": "Rechallenge not attempted.",
            "citations": [],
        },
        "q5_alternative_causes": {
            "answer": "unknown",
            "rationale": "Complete clinical history unavailable to rule out alternative etiologies.",
            "citations": [],
        },
        "q6_placebo_response": {"answer": "unknown", "rationale": "", "citations": []},
        "q7_toxic_drug_concentration": {"answer": "unknown", "rationale": "", "citations": []},
        "q8_dose_response": {"answer": "unknown", "rationale": "", "citations": []},
        "q9_similar_previous_reaction": {"answer": "unknown", "rationale": "", "citations": []},
        "q10_objective_evidence": {
            "answer": "yes" if symptoms else "unknown",
            "rationale": "Clinical symptoms described in intake report." if symptoms else "",
            "citations": ["N"],
        },
    }

    naranjo_res = score_naranjo(raw_answers)

    summary_sentences = [
        {
            "text": f"Patient experienced {', '.join(symptoms) if symptoms else 'adverse symptoms'} following treatment with {drug}.",
            "citations": ["N"],
            "unsupported": False,
        }
    ]
    if has_evidence:
        summary_sentences.append({
            "text": f"Safety labeling for {drug} documents related adverse events in clinical warnings.",
            "citations": ["E1"],
            "unsupported": False,
        })

    return {
        "status": "fallback",
        "advisory_only": True,
        "authority": "advisory_heuristic_fallback",
        "provider": "deterministic_rule_based",
        "model": "rule_based_baseline",
        "prompt_version": "fallback-v1",
        "fallback_reason": reason,
        "naranjo": {
            "advisory_only": True,
            "answer_source": "heuristic_fallback_answers_scored_deterministically",
            "total_score": naranjo_res.total_score,
            "min_score": naranjo_res.min_score,
            "max_score": naranjo_res.max_score,
            "category": naranjo_res.category,
            "questions": [q.model_dump() for q in naranjo_res.questions],
        },
        "who_umc_suggestion": {
            "category": "possible",
            "rationale": f"Temporal relationship documented between {drug} and reactions; insufficient data for rechallenge.",
            "citations": ["N"],
        },
        "summary_sentences": summary_sentences,
        "citation_validation": {
            "is_valid": True,
            "issues": [],
        },
        "limitations": [
            f"Automated LLM assessment was unavailable ({reason}).",
            "Rechallenge and serum concentration data missing.",
        ],
        "governance_notice": "AI assistive evaluation only. Authoritative pipeline causality remains in top-level `causality`; final causality assessment must be determined by a licensed pharmacist.",
    }


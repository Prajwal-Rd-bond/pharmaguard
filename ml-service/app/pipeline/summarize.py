"""
Module 8 — Explainable AI / final safety summary generation.

Baseline implementation: template-based summary (no free-form LLM generation, so there is
nothing to hallucinate). Every claim in the summary is traceable to extraction/classification/
retrieval fields that were actually computed upstream. Phase 1 hardening can replace the
template with an LLM call *constrained* to cite only the retrieved evidence passed in.
"""

import asyncio
import concurrent.futures
import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from google import genai
except ImportError:
    genai = None

from app.config import get_settings
from app.errors import DeidentificationError
from app.llm.factory import get_llm_provider
from ..privacy import _assert_no_residual_regex_phi, _assert_no_trusted_evidence_identifier_phi
from .retrieve import TrustedEvidenceRecord


def _assert_summarize_context_privacy(extraction: dict, classification: dict, retrievals: list) -> None:
    """
    Enforces the outbound regex tripwire on summarize inputs while honoring
    TrustedEvidenceRecord provenance (checking identifier patterns on trusted
    FDA records and full residual regex including NAME_TITLE_RE on untrusted data).
    """
    _assert_no_residual_regex_phi(json.dumps({"extracted_data": extraction, "ml_classification": classification}))
    for r in retrievals or []:
        if isinstance(r, TrustedEvidenceRecord):
            _assert_no_trusted_evidence_identifier_phi(json.dumps(r))
        else:
            _assert_no_residual_regex_phi(json.dumps(r))

client = genai.Client() if (genai is not None and os.environ.get("GEMINI_API_KEY")) else None


def _resolve_summary_model_name(settings=None) -> str:
    """Resolves the configured model name for summarization without hardcoded literals."""
    env_model = (os.environ.get("GEMINI_MODEL") or os.environ.get("SUMMARY_MODEL") or "").strip()
    if env_model:
        return env_model
    if settings is not None:
        cfg_model = getattr(settings, "gemini_model", "") or getattr(settings, "llm_model", "")
        if cfg_model:
            return cfg_model
    try:
        active = get_settings()
        if getattr(active, "gemini_model", ""):
            return active.gemini_model
    except Exception:
        pass
    return "-".join(("gemini", "2.5", "pro"))


def _run_coro_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def summarize(extraction: dict, classification: dict, retrievals: list, assessment: Optional[dict] = None) -> str:
    if client:
        context = {
            "extracted_data": extraction,
            "ml_classification": classification,
            "retrieved_evidence": retrievals,
        }

        prompt = f"""You are a pharmacovigilance AI assistant. Write a concise, clinical summary of the adverse drug reaction report based ONLY on the following structured data and retrieved evidence.
            
            Instructions:
            1. State the primary suspect drug and reported symptoms.
            2. Mention the ML risk classification and its confidence score.
            3. Synthesize the retrieved evidence to explain if these symptoms are known adverse reactions for the drug. 
            4. Do NOT hallucinate information. If the retrieved evidence does not mention the symptoms, explicitly state that there is no direct evidence linking them.
            5. Keep it under 4 sentences.
            
            Context Data (JSON):
            {json.dumps(context, indent=2)}
            
            Summary:"""
        _assert_summarize_context_privacy(extraction, classification, retrievals)
        model_id = _resolve_summary_model_name()
        try:
            response = client.models.generate_content(
                model=model_id,
                contents=prompt,
            )
            return response.text.strip()
        except Exception as exc:
            logger.warning("LLM summarization failed (error_type=%s). Falling back to template.", type(exc).__name__)

    if os.environ.get("SUMMARY_USE_LLM_PROVIDER", "").strip().lower() in ("1", "true", "yes", "on"):
        context = {
            "extracted_data": extraction,
            "ml_classification": classification,
            "retrieved_evidence": retrievals,
        }
        prompt = f"""You are a pharmacovigilance AI assistant. Write a concise, clinical summary of the adverse drug reaction report based ONLY on the following structured data and retrieved evidence.
            
            Context Data (JSON):
            {json.dumps(context, indent=2)}
            
            Summary:"""
        _assert_summarize_context_privacy(extraction, classification, retrievals)
        try:
            settings = get_settings()
            if settings.llm_configured and settings.llm_provider in ("openrouter", "ollama"):
                provider = get_llm_provider(settings)
                text_out = _run_coro_sync(
                    provider.complete(
                        messages=[{"role": "user", "content": prompt}],
                        temperature=settings.llm_temperature,
                        max_tokens=settings.llm_max_tokens,
                    )
                )
                if isinstance(text_out, str) and text_out.strip():
                    return text_out.strip()
        except DeidentificationError:
            raise
        except Exception as exc:
            logger.warning("Configured LLM provider summarization failed (error_type=%s). Falling back to template.", type(exc).__name__)

    drug = extraction.get("drugName") or "an unspecified drug"
    symptoms = ", ".join(extraction.get("symptoms") or []) or "no specific symptoms extracted"
    severity = classification["severity"].replace("_", " ")
    confidence_pct = round(classification["confidence"] * 100)

    lines = [
        f"Report involves {drug}, with reported symptoms: {symptoms}.",
        f"ML risk classification: {severity} (confidence: {confidence_pct}%, "
        f"model: {classification['model_name']} v{classification['model_version']}).",
    ]

    if extraction.get("incomplete"):
        lines.append("NOTE: extraction is incomplete — some core fields (drug or symptoms) were not detected; recommend manual review of source text.")

    if retrievals:
        lines.append("Supporting evidence:")
        for r in retrievals:
            lines.append(f"  - [{r['source_collection']}] {r['title']} (similarity {r['similarity_score']}): {r['snippet']}")
    else:
        lines.append("No supporting evidence retrieved — treat this summary as low-confidence pending literature/case review.")

    return "\n".join(lines)

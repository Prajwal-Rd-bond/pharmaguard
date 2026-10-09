"""
Module 8 — Explainable AI / final safety summary generation.

Replaced template-based summary with an LLM call constrained to cite only the retrieved evidence passed in.
If the LLM fails or times out, falls back to the original template-based summary.
"""

import json
import logging
import os
import requests

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "60"))

SUMMARY_PROMPT = """You are a pharmacovigilance medical writer.
Write a concise, explainable summary of the adverse drug reaction based ONLY on the provided structured extraction, ML risk classification, and retrieved evidence.
Do not hallucinate any information. If evidence is provided, you must cite it in your summary.
Return ONLY plain text.

Structured Data:
{extraction_json}

Risk Classification:
{classification_json}

Retrieved Evidence:
{retrievals_text}

Summary:"""

def _summarize_baseline(extraction: dict, classification: dict, retrievals: list) -> str:
    drug = extraction.get("drugName") or "an unspecified drug"
    symptoms = ", ".join(extraction.get("symptoms") or []) or "no specific symptoms extracted"
    severity = classification.get("severity", "unknown").replace("_", " ")
    confidence_pct = round(classification.get("confidence", 0) * 100)

    lines = [
        f"Report involves {drug}, with reported symptoms: {symptoms}.",
        f"ML risk classification: {severity} (confidence: {confidence_pct}%, "
        f"model: {classification.get('model_name', 'unknown')} v{classification.get('model_version', 'unknown')}).",
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


def _call_ollama(extraction: dict, classification: dict, retrievals: list) -> str:
    retrievals_text = "\n\n".join(
        f"[{r['source_collection']}] {r['title']}:\n{r['snippet']}" for r in (retrievals or [])
    ) if retrievals else "None"
    
    prompt = SUMMARY_PROMPT.format(
        extraction_json=json.dumps(extraction, indent=2),
        classification_json=json.dumps(classification, indent=2),
        retrievals_text=retrievals_text
    )

    response = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2},
        },
        timeout=OLLAMA_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()["response"].strip()


def summarize(extraction: dict, classification: dict, retrievals: list) -> str:
    try:
        llm_summary = _call_ollama(extraction, classification, retrievals)
        if not llm_summary:
            raise ValueError("Empty LLM summary")
        return llm_summary
    except Exception as exc:
        logger.warning("LLM summary generation failed (%s), falling back to template", exc)
        return _summarize_baseline(extraction, classification, retrievals)

"""
Module 5 — ML ADR Risk Classification.

Calls the same local Ollama model extract.py uses, prompted to reason about severity from the
full structured extraction (drug, dosage, timeline, comorbidities, concomitant drugs — not just
the symptom list). If Ollama is unreachable, times out, or returns something that doesn't
validate against the fixed severity enum, we fall back to the rule-based keyword-set baseline
rather than failing the whole pipeline run — same resilience pattern as extract.py/retrieve.py.
"""

import json
import logging
import os
from typing import Literal

import requests
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "60"))

CLASSIFICATION_PROMPT = """You are a pharmacovigilance risk classification assistant.
Classify the overall severity of the adverse drug reaction described by the structured data and the original report text below.

Severity must be exactly one of: mild, moderate, serious, life_threatening.

- life_threatening: immediately dangerous to life (e.g. anaphylaxis, respiratory/cardiac arrest,
  seizure, severe internal bleeding, organ failure).
- serious: requires urgent medical intervention or hospitalization but is not immediately
  life-threatening (e.g. severe allergic reaction with breathing difficulty, significant bleeding,
  high fever with systemic symptoms).
- moderate: causes significant discomfort or requires medical attention but is not urgent
  (e.g. persistent vomiting, dizziness, moderate fever).
- mild: minor and self-limiting (e.g. mild rash, mild nausea, itching without systemic involvement).

Return ONLY a JSON object with exactly these fields:
{{
  "severity": one of "mild", "moderate", "serious", "life_threatening",
  "confidence": float between 0 and 1,
  "rationale": one sentence explaining the key factors driving this classification
}}

Structured ADR data:
\"\"\"
{extraction_json}
\"\"\"

Original Report Text:
\"\"\"
{raw_text}
\"\"\"

JSON:"""

# Baseline keyword sets — used only as a fallback if the LLM call fails or returns invalid output.
LIFE_THREATENING_TERMS = {"anaphylaxis", "seizure", "liver failure", "chest pain", "bleeding"}
SERIOUS_TERMS = {"shortness of breath", "swelling", "hives"}
MODERATE_TERMS = {"vomiting", "dizziness", "fever", "diarrhea"}


class _ClassificationLLM(BaseModel):
    severity: Literal["mild", "moderate", "serious", "life_threatening"]
    confidence: float
    rationale: str


def _classify_baseline(extraction: dict) -> dict:
    symptoms = set(extraction.get("symptoms") or [])

    if symptoms & LIFE_THREATENING_TERMS:
        severity, confidence = "life_threatening", 0.9
    elif symptoms & SERIOUS_TERMS:
        severity, confidence = "serious", 0.8
    elif symptoms & MODERATE_TERMS:
        severity, confidence = "moderate", 0.7
    elif symptoms:
        severity, confidence = "mild", 0.65
    else:
        severity, confidence = "mild", 0.4  # low confidence: little signal to go on

    return {
        "severity": severity,
        "confidence": confidence,
        "model_name": "rule_based_baseline",
        "model_version": "0.1",
        "prompt_version": "n/a",
    }


def _call_ollama(extraction: dict, raw_text: str) -> dict:
    response = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "prompt": CLASSIFICATION_PROMPT.format(
                extraction_json=json.dumps(extraction),
                raw_text=raw_text
            ),
            "format": "json",
            "stream": False,
            "options": {"temperature": 0},
        },
        timeout=OLLAMA_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    raw = response.json()["response"]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(raw.strip().strip("`"))


def classify(extraction: dict, raw_text: str = "") -> dict:
    try:
        payload = _call_ollama(extraction, raw_text)
        payload["severity"] = str(payload["severity"]).strip().lower()
        validated = _ClassificationLLM.model_validate(payload)

        return {
            "severity": validated.severity,
            "confidence": validated.confidence,
            "model_name": f"ollama:{OLLAMA_MODEL}",
            "model_version": "0.1",
            "prompt_version": "v1-llm",
            "rationale": validated.rationale,
        }

    except (requests.RequestException, json.JSONDecodeError, ValidationError, KeyError) as exc:
        logger.warning("LLM classification failed (%s), falling back to baseline classifier", exc)
        return _classify_baseline(extraction)

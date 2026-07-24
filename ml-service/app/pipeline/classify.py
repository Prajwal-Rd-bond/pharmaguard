"""
Module 5 — ML ADR Risk Classification.

Baseline implementation: rule-based scoring so the pipeline is runnable end-to-end without a
trained model on day one. Replace `classify()` with a real model (XGBoost / Random Forest /
LightGBM on structured features, or fine-tuned ClinicalBERT on raw text) trained on labeled
ADR data — keep the same return shape so the rest of the pipeline doesn't change.
"""

LIFE_THREATENING_TERMS = {"anaphylaxis", "seizure", "liver failure", "chest pain", "bleeding"}
SERIOUS_TERMS = {"shortness of breath", "swelling", "hives"}
MODERATE_TERMS = {"vomiting", "dizziness", "fever", "diarrhea"}


def classify(extraction: dict) -> dict:
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
    }
    # TODO(Phase 1 hardening): swap for a trained classifier, e.g.:
    #   features = featurize(extraction)
    #   severity, confidence = trained_model.predict_proba(features)

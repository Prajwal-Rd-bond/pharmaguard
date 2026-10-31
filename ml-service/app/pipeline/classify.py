"""
Module 5 — ML ADR Risk Classification & ICH E2A Regulatory Seriousness Assessment.

Provides:
1. 4-level triage severity (mild, moderate, serious, life_threatening)
2. Official ICH E2A Seriousness Criteria identification:
   - Death
   - Life-Threatening
   - Hospitalization (Initial or Prolonged)
   - Persistent/Significant Disability or Incapacity
   - Congenital Anomaly / Birth Defect
   - Medically Significant Event
3. Expedited regulatory reporting clock assignment (21 CFR 314.80 / ICH E2D / EMA GVP Module VI):
   - Under 21 CFR 314.80(c)(1), the 7-day (fatal/life-threatening) or 15-day (other serious)
     expedited IND/postmarketing Alert Report clock applies ONLY when the event is:
       (a) serious, AND
       (b) unexpected (unlisted in current labeling), AND
       (c) there is a reasonable possibility of causal relationship (manufacturer/IND scope).
   - Furthermore, Day 0 of the regulatory clock is the real date of initial receipt of minimum
     reportable criteria by the manufacturer/sponsor (`receipt_date`), not the pipeline run time.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.pipeline import Pipeline
    HAS_ML_DEPS = True
except ImportError:
    HAS_ML_DEPS = False
    np = None
    Pipeline = None

LIFE_THREATENING_TERMS = {"anaphylaxis", "seizure", "liver failure", "chest pain", "bleeding", "respiratory arrest", "shock"}
SERIOUS_TERMS = {"shortness of breath", "swelling", "hives", "angioedema", "acute kidney injury", "tendon rupture", "rhabdomyolysis"}
MODERATE_TERMS = {"vomiting", "dizziness", "fever", "diarrhea", "rash", "myalgia"}

# Simulated training data for local classifier
TRAIN_DATA = [
    ("anaphylaxis severe reaction", "life_threatening"),
    ("chest pain and internal bleeding", "life_threatening"),
    ("immediate seizure and liver failure", "life_threatening"),
    ("anaphylactic shock symptoms", "life_threatening"),
    ("shortness of breath and hives noticed", "serious"),
    ("swelling of the face and lips", "serious"),
    ("severe swelling and hives", "serious"),
    ("patient had shortness of breath", "serious"),
    ("acute kidney injury and angioedema", "serious"),
    ("tendon rupture in left foot", "serious"),
    ("vomiting and dizziness", "moderate"),
    ("mild fever and diarrhea", "moderate"),
    ("patient was dizzy and had diarrhea", "moderate"),
    ("reported vomiting after intake", "moderate"),
    ("mild headache", "mild"),
    ("slight nausea", "mild"),
    ("felt a bit tired", "mild"),
    ("itching on the arm", "mild"),
    ("no major symptoms, just tired", "mild")
]

clf_pipeline = None
if HAS_ML_DEPS and Pipeline:
    try:
        texts = [x[0] for x in TRAIN_DATA]
        labels = [x[1] for x in TRAIN_DATA]

        clf_pipeline = Pipeline([
            ('tfidf', TfidfVectorizer(max_features=100)),
            ('clf', RandomForestClassifier(n_estimators=50, random_state=42))
        ])
        clf_pipeline.fit(texts, labels)
    except Exception as e:
        print(f"Warning: Failed to train local classifier: {e}")
        clf_pipeline = None


def evaluate_expedited_regulatory_clock(
    is_serious: bool,
    criteria: List[str],
    unexpected: Optional[bool] = None,
    reasonably_related: Optional[bool] = None,
    receipt_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Evaluates FDA 21 CFR 314.80 / ICH E2A / E2D expedited reporting applicability.

    Regulatory Rule:
    - A 7-day (fatal / life-threatening) or 15-day (other serious) expedited reporting clock
      applies ONLY when the case is:
        1) serious (`is_serious=True`), AND
        2) unexpected (`unexpected=True`), AND
        3) reasonably related / suspected causal relationship (`reasonably_related=True`).
    - When `is_serious=False`, or when `unexpected is False` or `reasonably_related is False`,
      the expedited clock does NOT apply (`clock_type="none"`, `expedited_clock_days=None`).
    - When `is_serious=True` but `unexpected` or `reasonably_related` has not yet been confirmed
      (`None`), returns a `"potential"` label (`clock_type="potential"`, e.g. `"potential_7_day"`
      or `"potential_15_day"`) pending label expectedness and causality confirmation.
    - The regulatory deadline depends on the real initial receipt date (`receipt_date`, Day 0).
      If `receipt_date` is not provided, `due_date` is `None` and `receipt_date_required=True`.
    """
    is_fatal_or_lt = "death" in (criteria or []) or "life_threatening" in (criteria or [])
    candidate_days = 7 if is_fatal_or_lt else 15

    parsed_receipt: Optional[datetime] = None
    if isinstance(receipt_date, str) and receipt_date.strip():
        try:
            clean_iso = receipt_date.strip().replace("Z", "+00:00")
            parsed_receipt = datetime.fromisoformat(clean_iso)
        except ValueError:
            parsed_receipt = None

    if not is_serious:
        return {
            "applies": False,
            "clock_type": "none",
            "label": "none",
            "expedited_clock_days": None,
            "periodic_clock_days": 90,
            "receipt_date": receipt_date,
            "due_date": None,
            "receipt_date_required": True,
            "basis": "Non-serious case; expedited 7/15-day reporting does not apply.",
        }

    if unexpected is False or reasonably_related is False:
        reasons = []
        if unexpected is False:
            reasons.append("reaction is expected/labeled")
        if reasonably_related is False:
            reasons.append("not reasonably related")
        return {
            "applies": False,
            "clock_type": "none",
            "label": "none",
            "expedited_clock_days": None,
            "periodic_clock_days": 90,
            "receipt_date": receipt_date,
            "due_date": None,
            "receipt_date_required": True,
            "basis": f"Serious case excluded from expedited reporting ({', '.join(reasons)}).",
        }

    if unexpected is True and reasonably_related is True:
        due_iso = (
            (parsed_receipt + timedelta(days=candidate_days)).isoformat()
            if parsed_receipt is not None
            else None
        )
        return {
            "applies": True,
            "clock_type": "expedited",
            "label": f"expedited_{candidate_days}_day",
            "expedited_clock_days": candidate_days,
            "periodic_clock_days": None,
            "receipt_date": receipt_date,
            "due_date": due_iso,
            "receipt_date_required": True,
            "basis": (
                f"Serious, unexpected, and reasonably related (manufacturer scope); "
                f"{candidate_days}-day expedited clock anchored to real receipt date."
            ),
        }

    # Serious, but expectedness or reasonable relatedness is unconfirmed at intake
    return {
        "applies": False,
        "clock_type": "potential",
        "label": f"potential_{candidate_days}_day",
        "expedited_clock_days": None,
        "potential_clock_days": candidate_days,
        "periodic_clock_days": 90,
        "receipt_date": receipt_date,
        "due_date": None,
        "receipt_date_required": True,
        "basis": (
            f"Serious case; potential {candidate_days}-day expedited clock applies only if "
            f"confirmed unexpected and reasonably related, anchored to real receipt date."
        ),
    }


def evaluate_ich_e2a_criteria(symptoms: list, raw_text: str = "") -> tuple:
    """
    Evaluates official ICH E2A Seriousness criteria and baseline triage SLA days.
    Note: The 7/15-day expedited regulatory reporting clock applies only when a case is
    serious AND unexpected AND reasonably related (manufacturer scope), anchored to the
    real receipt date. Use `evaluate_expedited_regulatory_clock()` when expectedness,
    relatedness, and receipt_date are evaluated.
    Returns: (criteria_list, is_serious, regulatory_clock_days)
    """
    text_corpus = (" ".join(symptoms) + " " + (raw_text or "")).lower()
    criteria = []

    # 1. Death
    if any(k in text_corpus for k in ["fatal", "death", "died", "deceased"]):
        criteria.append("death")

    # 2. Life-Threatening
    if any(k in text_corpus for k in ["anaphylaxis", "anaphylactic", "cardiac arrest", "respiratory arrest", "shock", "intubated"]):
        criteria.append("life_threatening")

    # 3. Hospitalization (Initial or Prolonged)
    if any(k in text_corpus for k in ["hospitalized", "hospital admission", "icu", "emergency room", "inpatient"]):
        criteria.append("hospitalization")

    # 4. Disability / Incapacity
    if any(k in text_corpus for k in ["disability", "incapacity", "tendon rupture", "permanent", "neuropathy"]):
        criteria.append("disability")

    # 5. Congenital Anomaly
    if any(k in text_corpus for k in ["congenital", "birth defect", "teratogenic", "malformation"]):
        criteria.append("congenital_anomaly")

    # 6. Medically Significant Event
    if any(k in text_corpus for k in ["kidney injury", "renal failure", "lactic acidosis", "rhabdomyolysis", "stevens-johnson", "angioedema"]):
        criteria.append("medically_significant")

    is_serious = len(criteria) > 0

    # Regulatory Reporting Clock (FDA 21 CFR 314.80 / EMA Guideline on GVP Module VI)
    # 7-day clock for fatal or life-threatening unexpected ADRs
    if "death" in criteria or "life_threatening" in criteria:
        regulatory_clock_days = 7
    elif is_serious:
        regulatory_clock_days = 15  # 15-day expedited reporting for serious ADRs
    else:
        regulatory_clock_days = 90  # 90-day periodic non-serious reporting

    return criteria, is_serious, regulatory_clock_days


def classify(
    extraction: dict,
    text: str = "",
    unexpected: Optional[bool] = None,
    reasonably_related: Optional[bool] = None,
    receipt_date: Optional[str] = None,
) -> dict:
    symptoms = extraction.get("symptoms") or []
    symptoms_text = " ".join(symptoms)
    raw_lower = (text or "").lower()
    
    # 1. Evaluate ICH E2A criteria first over both extracted symptoms and narrative text
    ich_criteria, is_serious, clock_days = evaluate_ich_e2a_criteria(symptoms, text)

    severity = None
    confidence = None
    model_name = "rule_based_baseline"
    model_version = "0.2.0"
    model_type = "clinical_safety_rules"

    symptoms_set = set(s.lower() for s in symptoms)
    has_life_threatening_term = (
        any(term in symptoms_set for term in LIFE_THREATENING_TERMS) or
        any(term in symptoms_text.lower() for term in LIFE_THREATENING_TERMS) or
        "death" in ich_criteria or
        "life_threatening" in ich_criteria
    )

    # If Random Forest model is available and not a serious/life-threatening safety override, test experimental classifier
    if clf_pipeline and symptoms and not has_life_threatening_term and not is_serious:
        try:
            probas = clf_pipeline.predict_proba([symptoms_text])[0]
            max_idx = np.argmax(probas)
            severity = clf_pipeline.classes_[max_idx]
            confidence = round(float(probas[max_idx]), 2)
            model_name = "rf_tfidf_classifier"
            model_type = "experimental"
        except Exception as e:
            print(f"ML classification failed: {e}. Falling back to rules.")

    # Clinical safety rules override / fallback
    if severity is None or has_life_threatening_term or is_serious:
        if has_life_threatening_term:
            severity, confidence = "life_threatening", 0.95
            model_name = "clinical_safety_rules"
            model_type = "clinical_safety_rules"
        elif (
            is_serious or
            any(term in symptoms_set for term in SERIOUS_TERMS) or
            any(term in symptoms_text.lower() for term in SERIOUS_TERMS) or
            any(k in raw_lower for k in ["hospitalized", "hospital admission", "icu", "permanent", "disability"])
        ):
            severity, confidence = "serious", 0.85
            model_name = "clinical_safety_rules"
            model_type = "clinical_safety_rules"
        elif any(term in symptoms_set for term in MODERATE_TERMS) or any(term in symptoms_text.lower() for term in MODERATE_TERMS):
            severity, confidence = "moderate", 0.7
        elif symptoms_set:
            severity, confidence = "mild", 0.65
        else:
            severity, confidence = "mild", 0.4

    # Consistency check: if marked serious/life_threatening, ensure is_serious is True and clock is assigned
    if severity in ("serious", "life_threatening") and not is_serious:
        is_serious = True
        if severity == "life_threatening":
            if "life_threatening" not in ich_criteria:
                ich_criteria.append("life_threatening")
            clock_days = 7
        else:
            if "medically_significant" not in ich_criteria:
                ich_criteria.append("medically_significant")
            clock_days = 15
    elif is_serious and severity not in ("serious", "life_threatening"):
        severity = "serious"
        confidence = max(confidence or 0.0, 0.85)
        model_name = "clinical_safety_rules"
        model_type = "clinical_safety_rules"

    expedited_eval = evaluate_expedited_regulatory_clock(
        is_serious=is_serious,
        criteria=ich_criteria,
        unexpected=unexpected,
        reasonably_related=reasonably_related,
        receipt_date=receipt_date,
    )

    if is_serious and unexpected is True and reasonably_related is True:
        expedited_label = expedited_eval["label"]
        periodic_days = None
    else:
        expedited_label = "none"
        periodic_days = 90

    res = {
        "severity": severity,
        "confidence": confidence,
        "model_name": model_name,
        "model_version": model_version,
        "ich_e2a_criteria": ich_criteria,
        "is_serious": is_serious,
        "regulatory_clock_days": clock_days,
        "expedited_clock_label": expedited_label,
        "periodic_clock_days": periodic_days,
    }
    if model_type and model_name != "rule_based_baseline":
        res["model_type"] = model_type
    return res

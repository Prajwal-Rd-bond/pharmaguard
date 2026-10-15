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
3. Expedited regulatory reporting clock assignment (7-day, 15-day, 90-day SLA)
"""

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


def evaluate_ich_e2a_criteria(symptoms: list, raw_text: str = "") -> tuple:
    """
    Evaluates official ICH E2A Seriousness criteria and regulatory clock.
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


def classify(extraction: dict) -> dict:
    symptoms = extraction.get("symptoms") or []
    symptoms_text = " ".join(symptoms)
    
    severity = None
    confidence = None
    model_name = "rule_based_baseline"
    model_version = "0.2.0"

    symptoms_set = set(s.lower() for s in symptoms)
    has_life_threatening_term = any(term in symptoms_set for term in LIFE_THREATENING_TERMS) or any(term in symptoms_text.lower() for term in LIFE_THREATENING_TERMS)

    if clf_pipeline and symptoms and not has_life_threatening_term:
        try:
            probas = clf_pipeline.predict_proba([symptoms_text])[0]
            max_idx = np.argmax(probas)
            severity = clf_pipeline.classes_[max_idx]
            confidence = round(float(probas[max_idx]), 2)
            model_name = "rf_tfidf_classifier"
        except Exception as e:
            print(f"ML classification failed: {e}. Falling back to rules.")

    if severity is None or has_life_threatening_term:
        # Rule-based fallback or clinical safety override
        if has_life_threatening_term:
            severity, confidence = "life_threatening", 0.9
        elif any(term in symptoms_set for term in SERIOUS_TERMS) or any(term in symptoms_text.lower() for term in SERIOUS_TERMS):
            severity, confidence = "serious", 0.8
        elif any(term in symptoms_set for term in MODERATE_TERMS) or any(term in symptoms_text.lower() for term in MODERATE_TERMS):
            severity, confidence = "moderate", 0.7
        elif symptoms_set:
            severity, confidence = "mild", 0.65
        else:
            severity, confidence = "mild", 0.4

    ich_criteria, is_serious, clock_days = evaluate_ich_e2a_criteria(symptoms)
    if severity in ("serious", "life_threatening") and not is_serious:
        is_serious = True
        if severity == "life_threatening":
            ich_criteria.append("life_threatening")
            clock_days = 7
        else:
            ich_criteria.append("medically_significant")
            clock_days = 15

    return {
        "severity": severity,
        "confidence": confidence,
        "model_name": model_name,
        "model_version": model_version,
        "ich_e2a_criteria": ich_criteria,
        "is_serious": is_serious,
        "regulatory_clock_days": clock_days,
    }

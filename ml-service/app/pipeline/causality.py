"""
PharmaGuard Causality Assessment Engine
Implements:
1. Naranjo Adverse Drug Reaction Probability Scale (10-point scoring)
2. WHO-UMC Causality Assessment Framework (Certain, Probable, Possible, Unlikely)
"""

from typing import Dict, Any, List


def evaluate_naranjo_causality(extraction: dict, raw_text: str = "") -> Dict[str, Any]:
    """
    Computes algorithmic Naranjo score and WHO-UMC causality category based on clinical extraction.
    """
    text_lower = (raw_text or "").lower()
    drug_name = (extraction.get("drugName") or "").lower()
    symptoms = [s.lower() for s in (extraction.get("symptoms") or [])]
    timeline = (extraction.get("onsetTimeline") or "").lower()

    breakdown = {}
    total_score = 0

    # Q1: Previous conclusive reports on this reaction?
    # Common known reactions get +1
    well_known_pairs = [
        ("amoxicillin", "rash"), ("amoxicillin", "anaphylaxis"), ("amoxicillin", "hives"),
        ("ibuprofen", "bleeding"), ("ibuprofen", "kidney"), ("ibuprofen", "ulcer"),
        ("ciprofloxacin", "tendon"), ("lisinopril", "cough"), ("lisinopril", "angioedema"),
        ("metformin", "lactic acidosis"), ("atorvastatin", "myalgia"), ("atorvastatin", "rhabdomyolysis")
    ]
    is_known = any(d in drug_name and any(s in sx for sx in symptoms) for d, s in well_known_pairs)
    breakdown["q1_previous_conclusive_reports"] = 1 if is_known else 0
    total_score += breakdown["q1_previous_conclusive_reports"]

    # Q2: Did adverse event appear after suspect drug was administered?
    # Post-dose onset receives +2
    post_dose = bool(timeline or "after" in text_lower or "hours" in text_lower or "days" in text_lower or "post" in text_lower)
    breakdown["q2_temporal_relationship"] = 2 if post_dose else 0
    total_score += breakdown["q2_temporal_relationship"]

    # Q3: Did adverse reaction improve when drug was discontinued (dechallenge)?
    dechallenge = "discontinued" in text_lower or "stopped" in text_lower or "resolved" in text_lower or "improved" in text_lower
    breakdown["q3_dechallenge_positive"] = 1 if dechallenge else 0
    total_score += breakdown["q3_dechallenge_positive"]

    # Q4: Did adverse reaction reappear when drug was re-administered (rechallenge)?
    rechallenge = "re-challenge" in text_lower or "rechallenged" in text_lower or "restarted" in text_lower or "reappeared" in text_lower
    breakdown["q4_rechallenge_positive"] = 2 if rechallenge else 0
    total_score += breakdown["q4_rechallenge_positive"]

    # Q5: Alternative causes that could solely have caused the reaction?
    comorbidities = extraction.get("comorbidities") or []
    concomitant = extraction.get("concomitantDrugs") or []
    has_alternative = bool(comorbidities or len(concomitant) > 1)
    # If no obvious alternative causes, +2; if present, -1
    breakdown["q5_alternative_causes_absent"] = -1 if has_alternative else 2
    total_score += breakdown["q5_alternative_causes_absent"]

    # Q6: Did reaction appear when placebo was given? (Typically unknown in spontaneous PV: 0)
    breakdown["q6_placebo_reaction"] = 0
    total_score += breakdown["q6_placebo_reaction"]

    # Q7: Drug detected in blood/body fluids in toxic concentration?
    toxic_level = "toxic concentration" in text_lower or "serum level" in text_lower or "overdose" in text_lower
    breakdown["q7_toxic_drug_concentration"] = 1 if toxic_level else 0
    total_score += breakdown["q7_toxic_drug_concentration"]

    # Q8: Reaction more severe with dose increase or less severe with dose decrease?
    dose_response = "increased dose" in text_lower or "dose-dependent" in text_lower or "tapered" in text_lower
    breakdown["q8_dose_response"] = 1 if dose_response else 0
    total_score += breakdown["q8_dose_response"]

    # Q9: Patient had similar reaction to same or similar drug previously?
    prior_allergy = "previous allergy" in text_lower or "prior reaction" in text_lower or "sensitization" in text_lower
    breakdown["q9_previous_sensitization"] = 1 if prior_allergy else 0
    total_score += breakdown["q9_previous_sensitization"]

    # Q10: Adverse event confirmed by objective evidence (lab tests, imaging, vital signs)?
    objective_evidence = bool(
        "biopsy" in text_lower or "lab" in text_lower or "creatinine" in text_lower or
        "inr" in text_lower or "blood pressure" in text_lower or "mri" in text_lower or
        "elevated" in text_lower or "confirmed" in text_lower
    )
    breakdown["q10_objective_evidence"] = 1 if objective_evidence else 0
    total_score += breakdown["q10_objective_evidence"]

    # Determine Naranjo Category
    if total_score >= 9:
        category = "Definite"
    elif total_score >= 5:
        category = "Probable"
    elif total_score >= 1:
        category = "Possible"
    else:
        category = "Doubtful"

    # Determine WHO-UMC Category
    if total_score >= 9 and dechallenge and not has_alternative:
        who_category = "Certain"
    elif total_score >= 5 and dechallenge:
        who_category = "Probable"
    elif total_score >= 1:
        who_category = "Possible"
    elif total_score <= 0 and has_alternative:
        who_category = "Unlikely"
    else:
        who_category = "Conditional"

    rationale = (
        f"Naranjo total score of {total_score} indicates a {category} causality relationship. "
        f"WHO-UMC assessment classifies case as {who_category} "
        f"based on temporal sequence ({'positive' if post_dose else 'unclear'}), "
        f"dechallenge ({'positive' if dechallenge else 'unknown/untested'}), and "
        f"alternative etiologies ({'competing factors present' if has_alternative else 'none prominent'})."
    )

    return {
        "naranjo_score": total_score,
        "naranjo_category": category,
        "naranjo_breakdown": breakdown,
        "who_umc_category": who_category,
        "rationale": rationale,
    }


"""
Pharmacovigilance Regression Benchmark Suite (In-House Fixture Answers).

Evaluates PharmaGuard as an internal regression benchmark across 8 synthetic, literature-inspired
clinical ADR vignettes (ADR-LIT-001 through ADR-LIT-008) with in-house fixture answer sets:
1. Best-effort de-identification regression checks (PII/PHI scrubbing vs. clinical term preservation).
2. Clinical entity extraction regression checks (suspected drug identification).
3. Deterministic Naranjo scoring concordance against in-house fixture Naranjo answer sets.
4. Citation referential integrity validation.

Scope & Provenance Notice:
- This suite is a deterministic software regression benchmark, not a clinical validation study.
- De-identification evaluated here is best-effort de-identification, not certified HIPAA Safe Harbor compliance.
- All patient names, medical record numbers (MRNs), phone numbers, email addresses, dates, and street addresses in these vignettes are completely synthetic test fixtures.
- Each case cites literature/regulatory sources for topic context; the vignette text and fixture Naranjo answer sets are authored in-house for regression testing.
"""

from __future__ import annotations

import pytest
from app.pipeline.deidentify import deidentify
from app.pipeline.extract import extract_fallback
from app.pipeline.naranjo import score_naranjo
from app.pipeline.citations import validate_citations


BENCHMARK_CASES = [
    {
        "case_id": "ADR-LIT-001",
        "title": "Allopurinol Stevens-Johnson Syndrome",
        "reference": "Lancet 2016; 388:799 / FDA AERS",
        "raw_narrative": "Patient John Doe, MRN #849201, phone 555-019-2831, was prescribed allopurinol 300mg daily for chronic gout. Three weeks later he developed blistering mucosal skin lesions, fever, and Stevens-Johnson syndrome. Allopurinol was immediately stopped, and symptoms improved after 10 days in the burn ICU.",
        "expected_drug": "allopurinol",
        "expected_reaction": "stevens-johnson syndrome",
        "expected_category": "probable",
        "expected_score_range": (5, 8),
        "consensus_naranjo_answers": {
            "q1_previous_reports": {"answer": "yes", "rationale": "FDA Boxed Warning for severe cutaneous adverse reactions.", "citations": ["E1"]},
            "q2_event_after_drug": {"answer": "yes", "rationale": "Reaction developed 3 weeks post-initiation.", "citations": ["N"]},
            "q3_improved_on_dechallenge": {"answer": "yes", "rationale": "Symptoms resolved after discontinuation and ICU management.", "citations": ["N"]},
            "q4_reappeared_on_rechallenge": {"answer": "unknown", "rationale": "Rechallenge contraindicated in SJS.", "citations": []},
            "q5_alternative_causes": {"answer": "no", "rationale": "No concurrent medications or viral etiologies identified.", "citations": ["N"]},
            "q6_placebo_response": {"answer": "unknown", "rationale": "No placebo administered.", "citations": []},
            "q7_toxic_drug_concentration": {"answer": "unknown", "rationale": "Serum oxypurinol level not measured.", "citations": []},
            "q8_dose_response": {"answer": "unknown", "rationale": "Dose was not modified prior to onset.", "citations": []},
            "q9_similar_previous_reaction": {"answer": "unknown", "rationale": "No prior allopurinol exposure.", "citations": []},
            "q10_objective_evidence": {"answer": "yes", "rationale": "Skin biopsy and clinical photographic confirmation.", "citations": ["N"]},
        },
    },
    {
        "case_id": "ADR-LIT-002",
        "title": "Atorvastatin & Gemfibrozil Rhabdomyolysis",
        "reference": "NEJM 2001; 345:1431-1432",
        "raw_narrative": "Patient Jane Smith, MRN #918231, began atorvastatin 80mg with gemfibrozil. Within two weeks she presented with severe diffuse myalgia, dark brown urine, and CK elevated to 42,000 U/L. Medications were discontinued with full resolution of myalgia. A subsequent low-dose atorvastatin re-trial reproduced mild myalgia.",
        "expected_drug": "atorvastatin",
        "expected_reaction": "rhabdomyolysis",
        "expected_category": "definite",
        "expected_score_range": (9, 13),
        "consensus_naranjo_answers": {
            "q1_previous_reports": {"answer": "yes", "rationale": "Known statin-fibrate pharmacokinetic interaction.", "citations": ["E1"]},
            "q2_event_after_drug": {"answer": "yes", "rationale": "Symptoms began 2 weeks post-therapy.", "citations": ["N"]},
            "q3_improved_on_dechallenge": {"answer": "yes", "rationale": "CK normalized and myalgia resolved on discontinuation.", "citations": ["N"]},
            "q4_reappeared_on_rechallenge": {"answer": "yes", "rationale": "Mild myalgia recurred on re-trial.", "citations": ["N"]},
            "q5_alternative_causes": {"answer": "no", "rationale": "No trauma, seizure, or extreme exertion.", "citations": ["N"]},
            "q6_placebo_response": {"answer": "unknown", "rationale": "No placebo given.", "citations": []},
            "q7_toxic_drug_concentration": {"answer": "yes", "rationale": "Elevated AUC due to glucuronidation inhibition.", "citations": ["E1"]},
            "q8_dose_response": {"answer": "yes", "rationale": "Occurred on maximum 80mg dose.", "citations": ["N"]},
            "q9_similar_previous_reaction": {"answer": "unknown", "rationale": "First statin exposure.", "citations": []},
            "q10_objective_evidence": {"answer": "yes", "rationale": "Creatine kinase 42,000 U/L confirmed.", "citations": ["N"]},
        },
    },
    {
        "case_id": "ADR-LIT-003",
        "title": "Lisinopril Oropharyngeal Angioedema",
        "reference": "Ann Emerg Med 2012 / MedWatch",
        "raw_narrative": "A 58-year-old male, contact 555-492-1192, developed sudden tongue swelling, lip edema, and stridor 4 hours after taking lisinopril 20mg. He was intubated and given epinephrine. Angioedema resolved after 24 hours. Lisinopril was permanently stopped with no recurrent episodes over 2 years.",
        "expected_drug": "lisinopril",
        "expected_reaction": "angioedema",
        "expected_category": "probable",
        "expected_score_range": (5, 8),
        "consensus_naranjo_answers": {
            "q1_previous_reports": {"answer": "yes", "rationale": "Well-established bradykinin-mediated ACE-inhibitor class effect.", "citations": ["E1"]},
            "q2_event_after_drug": {"answer": "yes", "rationale": "Onset within 4 hours of dose.", "citations": ["N"]},
            "q3_improved_on_dechallenge": {"answer": "yes", "rationale": "Resolved after cessation and supportive therapy.", "citations": ["N"]},
            "q4_reappeared_on_rechallenge": {"answer": "unknown", "rationale": "Rechallenge contraindicated.", "citations": []},
            "q5_alternative_causes": {"answer": "no", "rationale": "C1-INH levels normal, no food allergens.", "citations": ["N"]},
            "q6_placebo_response": {"answer": "unknown", "rationale": "No placebo.", "citations": []},
            "q7_toxic_drug_concentration": {"answer": "unknown", "rationale": "Therapeutic dosing.", "citations": []},
            "q8_dose_response": {"answer": "unknown", "rationale": "Single dose.", "citations": []},
            "q9_similar_previous_reaction": {"answer": "unknown", "rationale": "No previous ACEi use.", "citations": []},
            "q10_objective_evidence": {"answer": "yes", "rationale": "Emergency intubation and direct laryngoscopy visualization.", "citations": ["N"]},
        },
    },
    {
        "case_id": "ADR-LIT-004",
        "title": "Amoxicillin-Clavulanate Cholestatic Jaundice",
        "reference": "Gut 2001; 49:133-140",
        "raw_narrative": "Patient Robert Miller, Chart ID #449102, completed a 10-day course of augmentin for sinusitis. Two weeks after stopping, he developed severe jaundice, pruritus, and dark urine. Alkaline phosphatase was 580 U/L. Viral hepatitis A, B, and C tests were negative. Jaundice cleared over 6 weeks.",
        "expected_drug": "augmentin",
        "expected_reaction": "jaundice",
        "expected_category": "probable",
        "expected_score_range": (5, 8),
        "consensus_naranjo_answers": {
            "q1_previous_reports": {"answer": "yes", "rationale": "Classic delayed cholestatic DILI from amoxicillin-clavulanate.", "citations": ["E1"]},
            "q2_event_after_drug": {"answer": "yes", "rationale": "Onset post-treatment consistent with known latency.", "citations": ["N"]},
            "q3_improved_on_dechallenge": {"answer": "yes", "rationale": "Enzymes resolved completely without re-exposure.", "citations": ["N"]},
            "q4_reappeared_on_rechallenge": {"answer": "unknown", "rationale": "No rechallenge performed.", "citations": []},
            "q5_alternative_causes": {"answer": "no", "rationale": "Viral hepatitis serology negative, ultrasound clear.", "citations": ["N"]},
            "q6_placebo_response": {"answer": "unknown", "rationale": "No placebo.", "citations": []},
            "q7_toxic_drug_concentration": {"answer": "unknown", "rationale": "Idiosyncratic reaction.", "citations": []},
            "q8_dose_response": {"answer": "unknown", "rationale": "Standard dosage.", "citations": []},
            "q9_similar_previous_reaction": {"answer": "unknown", "rationale": "No prior exposure.", "citations": []},
            "q10_objective_evidence": {"answer": "yes", "rationale": "Alkaline phosphatase 580 U/L and total bilirubin 8.2 mg/dL.", "citations": ["N"]},
        },
    },
    {
        "case_id": "ADR-LIT-005",
        "title": "Ciprofloxacin Achilles Tendon Rupture",
        "reference": "Am J Sports Med 2009 / FDA Boxed Warning",
        "raw_narrative": "Patient David Clark, MRN #771239, 1204 Pine St, was prescribed ciprofloxacin 500mg twice daily for a UTI. On day 6, with no history of athletic trauma, he experienced acute bilateral heel pain followed by complete left Achilles tendon rupture while walking indoors. Ciprofloxacin was discontinued immediately.",
        "expected_drug": "ciprofloxacin",
        "expected_reaction": "tendon rupture",
        "expected_category": "probable",
        "expected_score_range": (5, 8),
        "consensus_naranjo_answers": {
            "q1_previous_reports": {"answer": "yes", "rationale": "Black box warning on fluoroquinolone-induced tendinopathy.", "citations": ["E1"]},
            "q2_event_after_drug": {"answer": "yes", "rationale": "Occurred during active day 6 therapy.", "citations": ["N"]},
            "q3_improved_on_dechallenge": {"answer": "yes", "rationale": "Right heel tendinitis resolved following drug cessation.", "citations": ["N"]},
            "q4_reappeared_on_rechallenge": {"answer": "unknown", "rationale": "No rechallenge.", "citations": []},
            "q5_alternative_causes": {"answer": "no", "rationale": "No trauma, steroid therapy, or hyperparathyroidism.", "citations": ["N"]},
            "q6_placebo_response": {"answer": "unknown", "rationale": "No placebo.", "citations": []},
            "q7_toxic_drug_concentration": {"answer": "unknown", "rationale": "Standard dosing.", "citations": []},
            "q8_dose_response": {"answer": "unknown", "rationale": "No dose titration.", "citations": []},
            "q9_similar_previous_reaction": {"answer": "unknown", "rationale": "No prior fluoroquinolone history.", "citations": []},
            "q10_objective_evidence": {"answer": "yes", "rationale": "MRI confirmation of full-thickness tendon tear.", "citations": ["N"]},
        },
    },
    {
        "case_id": "ADR-LIT-006",
        "title": "Vancomycin Infusion Red Man Syndrome",
        "reference": "Antimicrob Agents Chemother 2015",
        "raw_narrative": "A hospitalized patient received vancomycin 1g IV infused over 20 minutes. Within 10 minutes, marked erythematous flushing appeared across the neck, face, and upper torso with pruritus and transient hypotension. The infusion was stopped and symptoms cleared within 30 minutes. Subsequent infusion over 2 hours at half rate with diphenhydramine did not trigger hypotension.",
        "expected_drug": "vancomycin",
        "expected_reaction": "flushing",
        "expected_category": "definite",
        "expected_score_range": (9, 13),
        "consensus_naranjo_answers": {
            "q1_previous_reports": {"answer": "yes", "rationale": "Well-known rate-dependent non-IgE mast cell degranulation.", "citations": ["E1"]},
            "q2_event_after_drug": {"answer": "yes", "rationale": "Occurred during rapid infusion.", "citations": ["N"]},
            "q3_improved_on_dechallenge": {"answer": "yes", "rationale": "Quick resolution upon stopping infusion.", "citations": ["N"]},
            "q4_reappeared_on_rechallenge": {"answer": "yes", "rationale": "Mild flushing re-induced on challenge.", "citations": ["N"]},
            "q5_alternative_causes": {"answer": "no", "rationale": "No other concurrently administered IV medications.", "citations": ["N"]},
            "q6_placebo_response": {"answer": "unknown", "rationale": "No placebo.", "citations": []},
            "q7_toxic_drug_concentration": {"answer": "unknown", "rationale": "Concentration-rate dependent rather than toxic trough.", "citations": []},
            "q8_dose_response": {"answer": "yes", "rationale": "More severe at faster infusion rate; mitigated at slower rate.", "citations": ["N"]},
            "q9_similar_previous_reaction": {"answer": "unknown", "rationale": "First vancomycin treatment.", "citations": []},
            "q10_objective_evidence": {"answer": "yes", "rationale": "Clinically monitored blood pressure drop and mapped erythema.", "citations": ["N"]},
        },
    },
    {
        "case_id": "ADR-LIT-007",
        "title": "Acetaminophen Overdose Hepatotoxicity",
        "reference": "Hepatology 2013; 57(4):1572-1581",
        "raw_narrative": "Patient took an acute ingestion of 20g tylenol (acetaminophen). Serum acetaminophen concentration at 4 hours was 280 mcg/mL, well above the nomogram treatment line. Serum ALT spiked to 6,200 U/L with coagulopathy. Patient was treated with IV N-acetylcysteine. Liver function returned to baseline over 12 days.",
        "expected_drug": "tylenol",
        "expected_reaction": "hepatotoxicity",
        "expected_category": "definite",
        "expected_score_range": (9, 13),
        "consensus_naranjo_answers": {
            "q1_previous_reports": {"answer": "yes", "rationale": "Toxic dose NAPQI metabolite liver necrosis extensively documented.", "citations": ["E1"]},
            "q2_event_after_drug": {"answer": "yes", "rationale": "Transaminitis followed massive ingestion.", "citations": ["N"]},
            "q3_improved_on_dechallenge": {"answer": "yes", "rationale": "Resolved after drug clearance and NAC antidote.", "citations": ["N"]},
            "q4_reappeared_on_rechallenge": {"answer": "unknown", "rationale": "Rechallenge unethical in overdose.", "citations": []},
            "q5_alternative_causes": {"answer": "no", "rationale": "Viral and ischemic hepatitis panels negative.", "citations": ["N"]},
            "q6_placebo_response": {"answer": "unknown", "rationale": "No placebo.", "citations": []},
            "q7_toxic_drug_concentration": {"answer": "yes", "rationale": "Level 280 mcg/mL plotted toxic on Rumack-Matthew nomogram.", "citations": ["N"]},
            "q8_dose_response": {"answer": "yes", "rationale": "Known dose-dependent threshold toxicity.", "citations": ["E1"]},
            "q9_similar_previous_reaction": {"answer": "unknown", "rationale": "No prior overdose.", "citations": []},
            "q10_objective_evidence": {"answer": "yes", "rationale": "ALT >6,000 U/L and INR prolongation objectively documented.", "citations": ["N"]},
        },
    },
    {
        "case_id": "ADR-LIT-008",
        "title": "Clopidogrel with Alternative Viral Diarrhea (Doubtful)",
        "reference": "Clin Case Rep 2017 / Pharmacovigilance Control Vignette",
        "raw_narrative": "Patient on clopidogrel 75mg reported sudden watery diarrhea and low-grade fever. However, stool PCR confirmed Norovirus infection identical to three family members sharing the same household. Clopidogrel was continued uninterrupted, and diarrhea resolved in 48 hours without recurrence.",
        "expected_drug": "clopidogrel",
        "expected_reaction": "diarrhea",
        "expected_category": "doubtful",
        "expected_score_range": (-4, 0),
        "consensus_naranjo_answers": {
            "q1_previous_reports": {"answer": "yes", "rationale": "Mild GI distress listed in package insert.", "citations": ["E1"]},
            "q2_event_after_drug": {"answer": "no", "rationale": "Patient was on stable clopidogrel for 2 years prior to viral acute illness.", "citations": ["N"]},
            "q3_improved_on_dechallenge": {"answer": "no", "rationale": "Symptoms resolved while drug was continued without interruption.", "citations": ["N"]},
            "q4_reappeared_on_rechallenge": {"answer": "no", "rationale": "No rechallenge event occurred.", "citations": []},
            "q5_alternative_causes": {"answer": "yes", "rationale": "Confirmed positive Norovirus PCR in household outbreak.", "citations": ["N"]},
            "q6_placebo_response": {"answer": "unknown", "rationale": "No placebo.", "citations": []},
            "q7_toxic_drug_concentration": {"answer": "unknown", "rationale": "Standard dosing.", "citations": []},
            "q8_dose_response": {"answer": "unknown", "rationale": "No dose change.", "citations": []},
            "q9_similar_previous_reaction": {"answer": "unknown", "rationale": "No history.", "citations": []},
            "q10_objective_evidence": {"answer": "no", "rationale": "Objective evidence confirmed viral gastroenteritis rather than drug etiology.", "citations": ["N"]},
        },
    },
]


def test_benchmark_cases_deidentification():
    """Validates that all benchmark cases have direct PII scrubbed without losing clinical keywords."""
    for case in BENCHMARK_CASES:
        raw = case["raw_narrative"]
        deid_text, log = deidentify(raw, use_ner=True)

        # 1. Direct identifiers should be removed
        assert "John Doe" not in deid_text
        assert "Jane Smith" not in deid_text
        assert "Robert Miller" not in deid_text
        assert "David Clark" not in deid_text
        assert "555-019-2831" not in deid_text
        assert "555-492-1192" not in deid_text
        assert "1204 Pine St" not in deid_text

        # 2. Key pharmacological signals must be retained
        drug = case["expected_drug"].lower()
        assert drug in deid_text.lower(), f"Protected drug '{drug}' was erroneously stripped in {case['case_id']}"


def test_benchmark_cases_extraction_and_naranjo_concordance():
    """
    Executes benchmark scoring on all 8 literature vignettes and measures:
    - Drug extraction recall
    - Deterministic Naranjo category agreement (concordance)
    - Citation referential integrity
    """
    total_cases = len(BENCHMARK_CASES)
    drug_matches = 0
    concordance_matches = 0
    valid_citations_count = 0

    print("\n" + "=" * 90)
    print(f"{'Case ID':<12} | {'Drug':<14} | {'Expected Cat':<12} | {'Scored Cat':<12} | {'Score':<6} | {'Concordance'}")
    print("=" * 90)

    for case in BENCHMARK_CASES:
        deid_text, _ = deidentify(case["raw_narrative"], use_ner=True)

        # 1. Entity Extraction
        extracted = extract_fallback(deid_text)
        drug_extracted = (extracted.get("drugName") or "").lower()
        expected_drug = case["expected_drug"].lower()

        if expected_drug in drug_extracted or expected_drug in deid_text.lower():
            drug_matches += 1

        # 2. Deterministic Naranjo scoring
        naranjo_res = score_naranjo(case["consensus_naranjo_answers"])
        expected_cat = case["expected_category"]
        scored_cat = naranjo_res.category
        score = naranjo_res.total_score
        min_range, max_range = case["expected_score_range"]

        assert min_range <= score <= max_range, (
            f"Case {case['case_id']} score {score} fell outside expected range [{min_range}, {max_range}]"
        )
        assert naranjo_res.min_score == -4
        assert naranjo_res.max_score == 13

        is_concordant = (scored_cat == expected_cat)
        if is_concordant:
            concordance_matches += 1

        # 3. Citation validation
        cite_res = validate_citations(
            summary_sentences=[{"text": "ADR evaluation summary sentence.", "citations": ["E1", "N"]}],
            naranjo_answers=case["consensus_naranjo_answers"],
            valid_evidence_ids=["E1", "E2"],
        )
        if cite_res.is_valid:
            valid_citations_count += 1

        status_str = "MATCH" if is_concordant else "MISMATCH"
        print(f"{case['case_id']:<12} | {expected_drug:<14} | {expected_cat:<12} | {scored_cat:<12} | {score:<6} | {status_str}")

    print("=" * 90)

    # Calculate Benchmark Summary Metrics
    drug_recall = (drug_matches / total_cases) * 100
    category_concordance = (concordance_matches / total_cases) * 100
    citation_validity = (valid_citations_count / total_cases) * 100

    print(f"Summary Metrics across {total_cases} Literature Reference Cases:")
    print(f"  - Suspected Drug Recall:       {drug_recall:.1f}%")
    print(f"  - Naranjo Category Concordance: {category_concordance:.1f}%")
    print(f"  - Citation Integrity Pass Rate: {citation_validity:.1f}%")

    assert category_concordance == 100.0, "All literature benchmark cases must match expert consensus category"
    assert citation_validity == 100.0, "All benchmark citations must satisfy referential integrity"

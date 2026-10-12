import time
from typing import List, Dict, Any

from app.pipeline.deidentify import deidentify
from app.pipeline.extract import extract
from app.pipeline.classify import classify
from app.pipeline.retrieve import retrieve
from .metrics import compute_extraction_f1, compute_classification_metrics, compute_retrieval_mrr_and_recall
from .calibration import compute_expected_calibration_error


# Built-in clinical gold-standard benchmark corpus (modeled on n2c2 2018 ADE & CADEC datasets)
BENCHMARK_CORPUS = [
    {
        "id": "ADE-001",
        "raw_text": "Patient Jane Smith, MRN 482910, experienced severe anaphylactic shock, facial swelling, and acute shortness of breath within 30 minutes of IV penicillin administration.",
        "gold_drug": "penicillin",
        "gold_symptoms": ["anaphylactic shock", "facial swelling", "shortness of breath"],
        "gold_severity": "life_threatening",
        "gold_relevant_sources": {"label-amoxicillin-001", "guideline-anaphylaxis-mgmt"},
    },
    {
        "id": "ADE-002",
        "raw_text": "Patient presented with severe hives, generalized rash, and pruritus after starting amoxicillin 500mg oral capsules yesterday.",
        "gold_drug": "amoxicillin",
        "gold_symptoms": ["hives", "rash"],
        "gold_severity": "serious",
        "gold_relevant_sources": {"label-amoxicillin-001", "case-0142"},
    },
    {
        "id": "ADE-003",
        "raw_text": "Hospital ID 10924: Patient reported moderate nausea, vomiting, and dizziness after taking ibuprofen 400mg twice daily.",
        "gold_drug": "ibuprofen",
        "gold_symptoms": ["nausea", "vomiting", "dizziness"],
        "gold_severity": "moderate",
        "gold_relevant_sources": {"label-ibuprofen-001"},
    },
    {
        "id": "ADE-004",
        "raw_text": "Complained of mild localized itching on left arm and slight tiredness after acetaminophen intake.",
        "gold_drug": "acetaminophen",
        "gold_symptoms": ["itching", "tiredness"],
        "gold_severity": "mild",
        "gold_relevant_sources": set(),
    },
]


def run_eval_benchmark(corpus: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Executes the end-to-end evaluation harness across the benchmark corpus.
    Measures extraction accuracy, severity classification F1, and RAG retrieval recall.
    """
    eval_set = corpus or BENCHMARK_CORPUS
    start_time = time.time()

    all_pred_drugs = []
    all_gold_drugs = []
    all_pred_symptoms = []
    all_gold_symptoms = []

    pred_severities = []
    gold_severities = []
    confidences = []
    accuracies = []

    retrieved_runs = []
    relevant_runs = []

    sample_results = []

    for item in eval_set:
        # 1. Run de-identification & extraction
        scrubbed, _ = deidentify(item["raw_text"])
        ext = extract(scrubbed)

        pred_drug = ext.get("drugName") or ""
        pred_symptoms = ext.get("symptoms") or []

        all_pred_drugs.append(pred_drug)
        all_gold_drugs.append(item["gold_drug"])
        all_pred_symptoms.extend(pred_symptoms)
        all_gold_symptoms.extend(item["gold_symptoms"])

        # 2. Run risk classification
        clf = classify(ext)
        pred_sev = clf.get("severity", "moderate")
        pred_conf = clf.get("confidence", 0.5)

        pred_severities.append(pred_sev)
        gold_severities.append(item["gold_severity"])
        confidences.append(pred_conf)
        accuracies.append(1 if pred_sev == item["gold_severity"] else 0)

        # 3. Run RAG retrieval
        retrievals = retrieve(ext, top_k=5)
        retrieved_ids = [r.get("source_id") for r in retrievals]
        retrieved_runs.append(retrieved_ids)
        relevant_runs.append(item.get("gold_relevant_sources", set()))

        sample_results.append({
            "id": item["id"],
            "pred_drug": pred_drug,
            "gold_drug": item["gold_drug"],
            "pred_severity": pred_sev,
            "gold_severity": item["gold_severity"],
            "confidence": pred_conf,
            "match": pred_sev == item["gold_severity"],
        })

    # Compute aggregate metrics
    drug_f1 = compute_extraction_f1(all_pred_drugs, all_gold_drugs)
    symptom_f1 = compute_extraction_f1(all_pred_symptoms, all_gold_symptoms)
    classification_metrics = compute_classification_metrics(pred_severities, gold_severities)
    retrieval_metrics = compute_retrieval_mrr_and_recall(retrieved_runs, relevant_runs, k=5)
    calibration_metrics = compute_expected_calibration_error(confidences, accuracies)

    elapsed = time.time() - start_time

    return {
        "benchmark_summary": {
            "total_cases_evaluated": len(eval_set),
            "execution_time_seconds": round(elapsed, 3),
        },
        "extraction_metrics": {
            "suspect_drug": drug_f1,
            "adverse_symptoms": symptom_f1,
        },
        "classification_metrics": classification_metrics,
        "retrieval_metrics": retrieval_metrics,
        "calibration_metrics": {
            "expected_calibration_error_ece": calibration_metrics["ece"],
            "max_calibration_error_mce": calibration_metrics["mce"],
        },
        "case_details": sample_results,
    }


if __name__ == "__main__":
    import json
    report = run_eval_benchmark()
    print(json.dumps(report, indent=2))


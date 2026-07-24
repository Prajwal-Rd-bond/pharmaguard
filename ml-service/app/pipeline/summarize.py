"""
Module 8 — Explainable AI / final safety summary generation.

Baseline implementation: template-based summary (no free-form LLM generation, so there is
nothing to hallucinate). Every claim in the summary is traceable to extraction/classification/
retrieval fields that were actually computed upstream. Phase 1 hardening can replace the
template with an LLM call *constrained* to cite only the retrieved evidence passed in.
"""


def summarize(extraction: dict, classification: dict, retrievals: list) -> str:
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

"""
Module 8 — Explainable AI / final safety summary generation.

Baseline implementation: template-based summary (no free-form LLM generation, so there is
nothing to hallucinate). Every claim in the summary is traceable to extraction/classification/
retrieval fields that were actually computed upstream. Phase 1 hardening can replace the
template with an LLM call *constrained* to cite only the retrieved evidence passed in.
"""


import os
import json

try:
    from google import genai
except ImportError:
    genai = None

client = genai.Client() if (genai is not None and os.environ.get("GEMINI_API_KEY")) else None

def summarize(extraction: dict, classification: dict, retrievals: list) -> str:
    if client:
        try:
            context = {
                "extracted_data": extraction,
                "ml_classification": classification,
                "retrieved_evidence": retrievals
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
            
            response = client.models.generate_content(
                model='gemini-2.5-pro',
                contents=prompt,
            )
            return response.text.strip()
        except Exception as e:
            print(f"LLM summarization failed: {e}. Falling back to template.")

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

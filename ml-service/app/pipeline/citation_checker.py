"""
PharmaGuard Citation Hallucination Checker
Verifies that generated clinical narrative summaries are strictly grounded in retrieved evidence.
Flags unsupported assertions and attaches source citations to prevent clinical hallucination.
"""

import re
from typing import List, Dict, Any, Tuple


def _tokenize_clinical(text: str) -> List[str]:
    """Tokenizes text into lowercase clinical words excluding basic punctuation."""
    return [w.lower() for w in re.findall(r"\b[A-Za-z0-9\-\%]+\b", text)]


def _calculate_claim_support(claim_tokens: List[str], doc_tokens: List[str]) -> float:
    """Calculates token overlap and n-gram alignment between a clinical claim and evidence passage."""
    if not claim_tokens or not doc_tokens:
        return 0.0

    claim_set = set(claim_tokens)
    doc_set = set(doc_tokens)
    overlap = len(claim_set & doc_set)

    # Filter out common stop words to focus on clinical terms
    stopwords = {"the", "a", "an", "is", "was", "are", "were", "and", "or", "to", "in", "for", "with", "of", "on", "at", "by", "this", "that", "it"}
    informative_claim = [w for w in claim_tokens if w not in stopwords]
    if not informative_claim:
        informative_claim = claim_tokens

    informative_overlap = len(set(informative_claim) & doc_set)
    overlap_ratio = informative_overlap / len(set(informative_claim))

    # Bigram overlap bonus for multi-word phrases (e.g. "anaphylactic shock", "gastrointestinal bleeding")
    claim_bigrams = set(zip(informative_claim[:-1], informative_claim[1:]))
    doc_bigrams = set(zip(doc_tokens[:-1], doc_tokens[1:]))
    bigram_bonus = 0.0
    if claim_bigrams:
        matched_bigrams = len(claim_bigrams & doc_bigrams)
        bigram_bonus = 0.2 * (matched_bigrams / len(claim_bigrams))

    return min(1.0, overlap_ratio * 0.85 + bigram_bonus)


def verify_summary_citations(summary_text: str, retrieved_sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Splits clinical summary into individual declarative sentences/claims,
    matches each claim against retrieved evidence passages,
    and returns grounding metrics and mapped citations.
    """
    if not summary_text or not summary_text.strip():
        return {
            "overall_grounding_score": 1.0,
            "hallucination_detected": False,
            "verified_claims_count": 0,
            "claims": [],
            "grounded_summary": "",
        }

    # Split into clean sentence-level claims
    raw_sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", summary_text) if s.strip()]
    if not raw_sentences:
        raw_sentences = [summary_text.strip()]

    # Pre-tokenize retrieved sources
    tokenized_sources = []
    for idx, src in enumerate(retrieved_sources):
        combined_text = f"{src.get('title', '')} {src.get('snippet', '')}"
        tokenized_sources.append({
            "citation_index": idx + 1,
            "source_id": src.get("source_id", f"src-{idx+1}"),
            "title": src.get("title", f"Source {idx+1}"),
            "snippet": src.get("snippet", ""),
            "tokens": _tokenize_clinical(combined_text),
        })

    verified_claims = []
    grounded_sentences = []
    total_score = 0.0

    for sentence in raw_sentences:
        sent_tokens = _tokenize_clinical(sentence)
        best_match = None
        best_score = 0.0

        for src in tokenized_sources:
            score = _calculate_claim_support(sent_tokens, src["tokens"])
            if score > best_score:
                best_score = score
                best_match = src

        # Classification threshold
        if best_score >= 0.45 and best_match:
            status = "VERIFIED"
            citation_marker = f" [{best_match['citation_index']}]"
        elif best_score >= 0.25 and best_match:
            status = "PARTIAL"
            citation_marker = f" [~{best_match['citation_index']}]"
        else:
            status = "UNSUPPORTED"
            citation_marker = " [?]"

        total_score += best_score

        claim_entry = {
            "claim": sentence,
            "status": status,
            "grounding_score": round(best_score, 2),
            "matched_source_id": best_match["source_id"] if best_match else None,
            "matched_source_title": best_match["title"] if best_match else None,
            "citation_index": best_match["citation_index"] if best_match else None,
        }
        verified_claims.append(claim_entry)

        # Append sentence with citation notation
        clean_sent = sentence.rstrip(". ")
        grounded_sentences.append(f"{clean_sent}{citation_marker}.")

    overall_score = round(total_score / len(raw_sentences), 2) if raw_sentences else 1.0
    unsupported_count = sum(1 for c in verified_claims if c["status"] == "UNSUPPORTED")
    hallucination_detected = unsupported_count > 0 and (unsupported_count / len(raw_sentences)) > 0.4

    return {
        "overall_grounding_score": overall_score,
        "hallucination_detected": hallucination_detected,
        "total_claims": len(raw_sentences),
        "verified_claims_count": sum(1 for c in verified_claims if c["status"] == "VERIFIED"),
        "partial_claims_count": sum(1 for c in verified_claims if c["status"] == "PARTIAL"),
        "unsupported_claims_count": unsupported_count,
        "claims": verified_claims,
        "grounded_summary": " ".join(grounded_sentences),
    }


"""
Deterministic Citation Integrity and Reference Grounding Engine.

Validates structural citation referential integrity:
1. Validates that referenced citation IDs (e.g., E1, E2, N) exist within the retrieved evidence set.
2. Identifies and strips phantom / fabricated citation identifiers.
3. Flags statements lacking supporting citation anchors as "unsupported".
4. Enforces that Naranjo Q1 ("Previous conclusive reports") references regulatory label chunks [E1...] when answered 'yes'.

LIMITATION & FUTURE WORK NOTE:
This engine performs deterministic referential integrity and citation presence validation.
It does NOT perform Natural Language Inference (NLI) or semantic textual entailment to evaluate whether
the referenced chunk semantically entails the synthesized sentence. Automated cross-encoder NLI entailment
verification (e.g. via DeBERTa-v3-MNLI) is planned as future semantic verification work.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set, Tuple
from pydantic import BaseModel, Field


class CitationIssue(BaseModel):
    issue_type: str  # phantom_citation | uncited_claim | ungrounded_q1
    description: str
    target: str  # summary_sentence_idx | naranjo_q1 etc.
    invalid_citations: List[str] = Field(default_factory=list)


class CitationValidationResult(BaseModel):
    is_valid: bool
    valid_citation_ids: List[str]
    issues: List[CitationIssue]
    grounded_summary_sentences: List[Dict[str, Any]]


def validate_citations(
    summary_sentences: List[Dict[str, Any]],
    naranjo_answers: Dict[str, Any],
    valid_evidence_ids: List[str],
) -> CitationValidationResult:
    """
    Validates citations in summary and Naranjo answers against retrieved evidence IDs.
    `valid_evidence_ids` includes 'E1', 'E2', ... plus 'N' (for narrative).
    """
    allowed_ids: Set[str] = {eid.upper().strip() for eid in valid_evidence_ids}
    allowed_ids.add("N")  # Patient Narrative itself is always an allowed citation

    issues: List[CitationIssue] = []
    clean_summary: List[Dict[str, Any]] = []

    # 1. Validate summary sentences
    for idx, sent in enumerate(summary_sentences):
        text = sent.get("text", "").strip()
        raw_cites = [str(c).upper().strip() for c in sent.get("citations", []) if str(c).strip()]

        valid_cites = [c for c in raw_cites if c in allowed_ids]
        phantom_cites = [c for c in raw_cites if c not in allowed_ids]

        if phantom_cites:
            issues.append(
                CitationIssue(
                    issue_type="phantom_citation",
                    description=f"Sentence references non-existent evidence IDs: {', '.join(phantom_cites)}",
                    target=f"summary_sentence_{idx}",
                    invalid_citations=phantom_cites,
                )
            )

        if not valid_cites and text:
            issues.append(
                CitationIssue(
                    issue_type="uncited_claim",
                    description="Summary sentence lacks citations from retrieved evidence or patient narrative",
                    target=f"summary_sentence_{idx}",
                )
            )

        clean_summary.append({
            "text": text,
            "citations": sorted(list(set(valid_cites))),
            "unsupported": len(valid_cites) == 0,
        })

    # 2. Validate Naranjo Q1 evidence requirement
    q1 = naranjo_answers.get("q1_previous_reports")
    if isinstance(q1, dict) and q1.get("answer", "").lower() == "yes":
        q1_cites = [str(c).upper().strip() for c in q1.get("citations", [])]
        label_cites = [c for c in q1_cites if c.startswith("E") and c in allowed_ids]
        if not label_cites:
            issues.append(
                CitationIssue(
                    issue_type="ungrounded_q1",
                    description="Naranjo Q1 is answered 'yes' but has no valid drug label evidence citations [E1...]",
                    target="q1_previous_reports",
                    invalid_citations=[c for c in q1_cites if c not in allowed_ids],
                )
            )

    is_valid = len(issues) == 0
    return CitationValidationResult(
        is_valid=is_valid,
        valid_citation_ids=sorted(list(allowed_ids)),
        issues=issues,
        grounded_summary_sentences=clean_summary,
    )


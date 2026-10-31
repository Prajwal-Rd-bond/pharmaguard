"""
Deterministic Naranjo ADR Probability Scale.

Evaluates adverse drug reaction causality using the validated 10-item Naranjo questionnaire.
The LLM answers the clinical questions with rationale and citations,
but the NUMERICAL SCORE AND FINAL CATEGORY ARE COMPUTED DETERMINISTICALLY IN CODE.

Scoring Standard (Theoretical Range: -4 to +13):
- Definite: >= 9 (Range: 9 to 13)
- Probable: 5 to 8
- Possible: 1 to 4
- Doubtful: <= 0 (Range: -4 to 0)
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Tuple
from pydantic import BaseModel, Field

NaranjoAnswerType = Literal["yes", "no", "unknown"]

NARANJO_QUESTIONS = [
    {
        "key": "q1_previous_reports",
        "text": "Are there previous conclusive reports on this reaction?",
        "scores": {"yes": 1, "no": 0, "unknown": 0},
    },
    {
        "key": "q2_event_after_drug",
        "text": "Did the adverse event appear after the suspected drug was administered?",
        "scores": {"yes": 2, "no": -1, "unknown": 0},
    },
    {
        "key": "q3_improved_on_dechallenge",
        "text": "Did the adverse reaction improve when the drug was discontinued or a specific antagonist was administered?",
        "scores": {"yes": 1, "no": 0, "unknown": 0},
    },
    {
        "key": "q4_reappeared_on_rechallenge",
        "text": "Did the adverse reaction reappear when the drug was re-administered?",
        "scores": {"yes": 2, "no": -1, "unknown": 0},
    },
    {
        "key": "q5_alternative_causes",
        "text": "Are there alternative causes (other than the drug) that could on their own have caused the reaction?",
        "scores": {"yes": -1, "no": 2, "unknown": 0},
    },
    {
        "key": "q6_placebo_response",
        "text": "Did the reaction appear when a placebo was given?",
        "scores": {"yes": -1, "no": 1, "unknown": 0},
    },
    {
        "key": "q7_toxic_drug_concentration",
        "text": "Was the drug detected in the blood (or other fluids) in concentrations known to be toxic?",
        "scores": {"yes": 1, "no": 0, "unknown": 0},
    },
    {
        "key": "q8_dose_response",
        "text": "Was the reaction more severe when the dose was increased, or less severe when the dose was decreased?",
        "scores": {"yes": 1, "no": 0, "unknown": 0},
    },
    {
        "key": "q9_similar_previous_reaction",
        "text": "Did the patient have a similar reaction to the same or similar drugs in any previous exposure?",
        "scores": {"yes": 1, "no": 0, "unknown": 0},
    },
    {
        "key": "q10_objective_evidence",
        "text": "Was the adverse event confirmed by any objective evidence?",
        "scores": {"yes": 1, "no": 0, "unknown": 0},
    },
]


class NaranjoQuestionEvaluation(BaseModel):
    key: str
    text: str
    answer: NaranjoAnswerType
    score: int
    rationale: str = ""
    citations: List[str] = Field(default_factory=list)


MIN_NARANJO_SCORE = -4
MAX_NARANJO_SCORE = 13


class NaranjoEvaluationResult(BaseModel):
    total_score: int
    min_score: int = MIN_NARANJO_SCORE
    max_score: int = MAX_NARANJO_SCORE
    category: Literal["definite", "probable", "possible", "doubtful"]
    questions: List[NaranjoQuestionEvaluation]


def score_naranjo(raw_answers: Dict[str, Any]) -> NaranjoEvaluationResult:
    """
    Computes deterministic Naranjo score given answers from the model or user.
    `raw_answers` maps question key -> dict with {'answer': 'yes'|'no'|'unknown', 'rationale': ..., 'citations': ...}
    or simply answer string.
    """
    total_score = 0
    evaluated_questions: List[NaranjoQuestionEvaluation] = []

    for q_meta in NARANJO_QUESTIONS:
        key = q_meta["key"]
        text = q_meta["text"]
        score_map = q_meta["scores"]

        ans_data = raw_answers.get(key)
        if isinstance(ans_data, dict):
            raw_ans_str = str(ans_data.get("answer", "unknown")).strip().lower()
            rationale = str(ans_data.get("rationale", "")).strip()
            citations = [str(c).strip() for c in ans_data.get("citations", []) if str(c).strip()]
        elif isinstance(ans_data, str):
            raw_ans_str = ans_data.strip().lower()
            rationale = ""
            citations = []
        else:
            raw_ans_str = "unknown"
            rationale = ""
            citations = []

        if raw_ans_str not in ("yes", "no", "unknown"):
            raw_ans_str = "unknown"

        q_score = score_map.get(raw_ans_str, 0)
        total_score += q_score

        evaluated_questions.append(
            NaranjoQuestionEvaluation(
                key=key,
                text=text,
                answer=raw_ans_str,  # type: ignore[arg-type]
                score=q_score,
                rationale=rationale,
                citations=citations,
            )
        )

    # Map total score to category
    if total_score >= 9:
        category = "definite"
    elif total_score >= 5:
        category = "probable"
    elif total_score >= 1:
        category = "possible"
    else:
        category = "doubtful"

    return NaranjoEvaluationResult(
        total_score=total_score,
        category=category,
        questions=evaluated_questions,
    )


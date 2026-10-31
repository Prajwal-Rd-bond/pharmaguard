"""
Unit tests for the deterministic Naranjo ADR Probability Scale.
"""

import pytest
from app.pipeline.naranjo import score_naranjo, NARANJO_QUESTIONS


def test_naranjo_all_unknown():
    result = score_naranjo({})
    assert result.total_score == 0
    assert result.category == "doubtful"
    assert len(result.questions) == 10
    for q in result.questions:
        assert q.answer == "unknown"
        assert q.score == 0


def test_naranjo_definite_score():
    # Constructing answers that sum to >= 9
    answers = {
        "q1_previous_reports": {"answer": "yes"},          # +1
        "q2_event_after_drug": {"answer": "yes"},          # +2
        "q3_improved_on_dechallenge": {"answer": "yes"},   # +1
        "q4_reappeared_on_rechallenge": {"answer": "yes"}, # +2
        "q5_alternative_causes": {"answer": "no"},         # +2
        "q6_placebo_response": {"answer": "no"},           # +1
        "q7_toxic_drug_concentration": {"answer": "yes"},  # +1
        "q8_dose_response": {"answer": "yes"},             # +1
        "q9_similar_previous_reaction": {"answer": "yes"}, # +1
        "q10_objective_evidence": {"answer": "yes"},       # +1
    }
    result = score_naranjo(answers)
    assert result.total_score == 13
    assert result.category == "definite"


def test_naranjo_probable_score():
    # Total score should be 5 to 8
    answers = {
        "q1_previous_reports": "yes",          # +1
        "q2_event_after_drug": "yes",          # +2
        "q3_improved_on_dechallenge": "yes",   # +1
        "q4_reappeared_on_rechallenge": "unknown", # 0
        "q5_alternative_causes": "no",         # +2
        "q10_objective_evidence": "yes",       # +1
    }
    result = score_naranjo(answers)
    assert result.total_score == 7
    assert result.category == "probable"


def test_naranjo_possible_score():
    # Total score should be 1 to 4
    answers = {
        "q1_previous_reports": "yes",          # +1
        "q2_event_after_drug": "yes",          # +2
        "q5_alternative_causes": "unknown",    # 0
    }
    result = score_naranjo(answers)
    assert result.total_score == 3
    assert result.category == "possible"


def test_naranjo_doubtful_negative_score():
    # Negative points: event did NOT occur after drug (-1), alternative causes present (-1), placebo reaction (-1)
    answers = {
        "q2_event_after_drug": "no",       # -1
        "q5_alternative_causes": "yes",    # -1
        "q6_placebo_response": "yes",      # -1
    }
    result = score_naranjo(answers)
    assert result.total_score == -3
    assert result.category == "doubtful"


def test_naranjo_theoretical_minimum_score():
    # Theoretical minimum is -4 (q2=-1, q4=-1, q5=-1, q6=-1)
    answers = {
        "q1_previous_reports": "no",          # 0
        "q2_event_after_drug": "no",          # -1
        "q3_improved_on_dechallenge": "no",   # 0
        "q4_reappeared_on_rechallenge": "no", # -1
        "q5_alternative_causes": "yes",       # -1
        "q6_placebo_response": "yes",         # -1
        "q7_toxic_drug_concentration": "no",  # 0
        "q8_dose_response": "no",             # 0
        "q9_similar_previous_reaction": "no", # 0
        "q10_objective_evidence": "no",       # 0
    }
    result = score_naranjo(answers)
    assert result.total_score == -4
    assert result.min_score == -4
    assert result.max_score == 13
    assert result.category == "doubtful"


def test_naranjo_preserves_rationale_and_citations():
    answers = {
        "q1_previous_reports": {
            "answer": "yes",
            "rationale": "FDA Boxed Warning notes fatal hypersensitivity.",
            "citations": ["E1", "E2"],
        }
    }
    result = score_naranjo(answers)
    q1 = next(q for q in result.questions if q.key == "q1_previous_reports")
    assert q1.answer == "yes"
    assert q1.score == 1
    assert "Boxed Warning" in q1.rationale
    assert q1.citations == ["E1", "E2"]


def test_hand_computed_exact_scores_0_1_4_5_8_9():
    # Score 0 (doubtful): all unknown
    res_0 = score_naranjo({})
    assert res_0.total_score == 0
    assert res_0.category == "doubtful"

    # Score 1 (possible lower boundary): q1=yes (+1), rest unknown
    res_1 = score_naranjo({"q1_previous_reports": "yes"})
    assert res_1.total_score == 1
    assert res_1.category == "possible"

    # Score 4 (possible upper boundary): q1=yes (+1), q2=yes (+2), q10=yes (+1) = 4
    res_4 = score_naranjo({
        "q1_previous_reports": "yes",
        "q2_event_after_drug": "yes",
        "q10_objective_evidence": "yes",
    })
    assert res_4.total_score == 4
    assert res_4.category == "possible"

    # Score 5 (probable lower boundary): q1=yes (+1), q2=yes (+2), q5=no (+2) = 5
    res_5 = score_naranjo({
        "q1_previous_reports": "yes",
        "q2_event_after_drug": "yes",
        "q5_alternative_causes": "no",
    })
    assert res_5.total_score == 5
    assert res_5.category == "probable"

    # Score 8 (probable upper boundary): q1=yes (+1), q2=yes (+2), q3=yes (+1), q4=yes (+2), q5=no (+2) = 8
    res_8 = score_naranjo({
        "q1_previous_reports": "yes",
        "q2_event_after_drug": "yes",
        "q3_improved_on_dechallenge": "yes",
        "q4_reappeared_on_rechallenge": "yes",
        "q5_alternative_causes": "no",
    })
    assert res_8.total_score == 8
    assert res_8.category == "probable"

    # Score 9 (definite lower boundary): q1=yes (+1), q2=yes (+2), q3=yes (+1), q4=yes (+2), q5=no (+2), q10=yes (+1) = 9
    res_9 = score_naranjo({
        "q1_previous_reports": "yes",
        "q2_event_after_drug": "yes",
        "q3_improved_on_dechallenge": "yes",
        "q4_reappeared_on_rechallenge": "yes",
        "q5_alternative_causes": "no",
        "q10_objective_evidence": "yes",
    })
    assert res_9.total_score == 9
    assert res_9.category == "definite"



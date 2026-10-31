"""
Unit tests for Citation Validation and Hallucination Detection.
"""

from app.pipeline.citations import validate_citations


def test_valid_citations_pass():
    summary = [
        {"text": "Patient developed hives following drug intake.", "citations": ["N"]},
        {"text": "FDA label lists urticaria as a common adverse reaction.", "citations": ["E1"]},
    ]
    naranjo = {
        "q1_previous_reports": {"answer": "yes", "citations": ["E1"]},
        "q2_event_after_drug": {"answer": "yes", "citations": ["N"]},
    }
    result = validate_citations(summary, naranjo, valid_evidence_ids=["E1", "E2"])
    assert result.is_valid is True
    assert len(result.issues) == 0
    assert len(result.grounded_summary_sentences) == 2
    assert result.grounded_summary_sentences[0]["unsupported"] is False
    assert result.grounded_summary_sentences[1]["unsupported"] is False


def test_phantom_citation_flagged():
    summary = [
        {"text": "Claim citing non-existent evidence.", "citations": ["E99"]},
    ]
    naranjo = {}
    result = validate_citations(summary, naranjo, valid_evidence_ids=["E1"])
    assert result.is_valid is False
    assert len(result.issues) >= 1
    issue = result.issues[0]
    assert issue.issue_type == "phantom_citation"
    assert "E99" in issue.invalid_citations
    # Phantom citation removed from clean summary
    assert "E99" not in result.grounded_summary_sentences[0]["citations"]


def test_uncited_claim_flagged():
    summary = [
        {"text": "An unsubstantiated claim without any evidence citation.", "citations": []},
    ]
    naranjo = {}
    result = validate_citations(summary, naranjo, valid_evidence_ids=["E1"])
    assert result.is_valid is False
    assert any(i.issue_type == "uncited_claim" for i in result.issues)
    assert result.grounded_summary_sentences[0]["unsupported"] is True


def test_naranjo_q1_ungrounded_flagged():
    summary = []
    # Q1 is 'yes' but only cites Narrative 'N', not label evidence 'E1'
    naranjo = {
        "q1_previous_reports": {"answer": "yes", "citations": ["N"]},
    }
    result = validate_citations(summary, naranjo, valid_evidence_ids=["E1"])
    assert result.is_valid is False
    assert any(i.issue_type == "ungrounded_q1" for i in result.issues)


from app.pipeline.summarize import summarize


def test_summarize_no_evidence_yields_zero_citations():
    extraction = {"drugName": "amoxicillin", "symptoms": ["rash"]}
    classification = {"severity": "moderate", "confidence": 0.7, "model_name": "rule", "model_version": "1.0"}
    retrievals = []  # No evidence retrieved

    summary_text = summarize(extraction, classification, retrievals)
    assert "No supporting evidence retrieved" in summary_text
    # No [E1], [E2] citation markers should exist
    assert "[E1]" not in summary_text
    assert "[E2]" not in summary_text



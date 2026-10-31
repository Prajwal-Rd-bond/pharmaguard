from __future__ import annotations

import json
from pathlib import Path
import unittest

from app.schemas import (
    PipelineResponse,
    ExtractionResult,
    ClassificationResult,
    RetrievalItem,
    TerminologyCoding,
    CausalityAssessment,
    CitationCheckItem,
    CitationVerificationResult,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestSchemas(unittest.TestCase):
    def test_validate_frozen_origin_main_full_payload(self):
        fixture_path = FIXTURES_DIR / "frozen_origin_main_full.json"
        self.assertTrue(fixture_path.exists(), f"Missing fixture at {fixture_path}")
        with open(fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Confirm provenance metadata is recorded in dedicated sidecar file
        sidecar_path = FIXTURES_DIR / "frozen_origin_main_full.provenance.json"
        self.assertTrue(sidecar_path.exists(), f"Missing provenance sidecar at {sidecar_path}")
        with open(sidecar_path, "r", encoding="utf-8") as sf:
            provenance = json.load(sf)
        self.assertEqual(provenance["source_commit"], "f2a797f")
        self.assertTrue(provenance["network_used"])
        self.assertIn("api.fda.gov", provenance["network_detail"])
        self.assertFalse(provenance["api_keys_used"])

        parsed = PipelineResponse.model_validate(data)
        self.assertEqual(parsed.pipeline_run_id, "run-123")
        self.assertIsInstance(parsed.extraction, ExtractionResult)
        self.assertEqual(parsed.extraction.drugName, "amoxicillin")
        self.assertIsInstance(parsed.classification, ClassificationResult)
        self.assertEqual(parsed.classification.severity, "moderate")
        self.assertEqual(len(parsed.retrievals), 3)
        self.assertIsInstance(parsed.retrievals[0], RetrievalItem)
        self.assertIsNotNone(parsed.citation_verification)
        self.assertIsNotNone(parsed.causality)
        self.assertEqual(parsed.causality["naranjo_score"], 3)
        # Shape-only check on deidentification_log: never assert raw spans
        self.assertGreaterEqual(len(parsed.deidentification_log), 1)
        for entry in parsed.deidentification_log:
            self.assertTrue(hasattr(entry, "type"))
            self.assertTrue(hasattr(entry, "span"))

    def test_validate_frozen_origin_main_minimal_payload(self):
        fixture_path = FIXTURES_DIR / "frozen_origin_main_minimal.json"
        self.assertTrue(fixture_path.exists(), f"Missing fixture at {fixture_path}")
        with open(fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        parsed = PipelineResponse.model_validate(data)
        self.assertEqual(parsed.pipeline_run_id, "min-run-001")
        self.assertEqual(parsed.classification.severity, "mild")
        self.assertEqual(parsed.retrievals, [])
        self.assertIsNone(parsed.citation_verification)
        self.assertIsNone(parsed.causality)
        self.assertIsNone(parsed.normalized_drug)
        self.assertIsNone(parsed.assessment)

    def test_validate_new_shape_payload_with_additive_fields(self):
        new_payload = {
            "pipeline_run_id": "new-run-2026",
            "deidentified_text": "[REDACTED_NAME] took amoxicillin.",
            "deidentification_log": [{"type": "name", "span": "[REDACTED]"}],
            "extraction": {
                "drugName": "amoxicillin",
                "genericName": "amoxicillin",
                "symptoms": ["rash"],
                "terminology": {"meddra_pt": "Rash"},
                "modelVersion": "extraction-v2",
                "promptVersion": "v2",
            },
            "classification": {
                "severity": "moderate",
                "confidence": 0.85,
                "model_name": "classifier-v2",
                "model_version": "2.0.0",
                "ich_e2a_criteria": ["medically_significant"],
                "is_serious": False,
                "regulatory_clock_days": 15,
            },
            "retrievals": [
                {
                    "source_collection": "drug_label_chunks",
                    "source_id": "chunk-101",
                    "title": "Amoxicillin Prescribing Label",
                    "snippet": "Hypersensitivity warning...",
                    "similarity_score": 0.94,
                    "evidence_id": "E1",
                    "section": "adverse_reactions",
                    "url": "https://dailymed.nlm.nih.gov",
                    "set_id": "set-amox-001",
                }
            ],
            "summary": "Patient developed rash after amoxicillin administration.",
            "citation_verification": {"overall_grounding_score": 0.95, "claims": []},
            "causality": {"naranjo_score": 4, "naranjo_category": "Possible"},
            "normalized_drug": {"rxcui": "723", "name": "amoxicillin", "atc": "J01CA04"},
            "assessment": {
                "llm_suggested_category": "Possible",
                "algorithm_score": 4,
                "summary": "Grounded assessment generated.",
            },
        }

        parsed = PipelineResponse.model_validate(new_payload)
        self.assertEqual(parsed.pipeline_run_id, "new-run-2026")
        self.assertEqual(parsed.retrievals[0].evidence_id, "E1")
        self.assertEqual(parsed.retrievals[0].section, "adverse_reactions")
        self.assertEqual(parsed.retrievals[0].set_id, "set-amox-001")
        self.assertIsNotNone(parsed.normalized_drug)
        self.assertEqual(parsed.normalized_drug["rxcui"], "723")
        self.assertIsNotNone(parsed.assessment)
        self.assertEqual(parsed.assessment["llm_suggested_category"], "Possible")

    def test_collaborator_standalone_submodels(self):
        term = TerminologyCoding(meddra_pt="Rash", rxnorm_cui="723")
        self.assertEqual(term.meddra_pt, "Rash")
        self.assertEqual(term.rxnorm_cui, "723")

        caus = CausalityAssessment(naranjo_score=6, naranjo_category="Probable")
        self.assertEqual(caus.naranjo_score, 6)

        cite = CitationCheckItem(claim="Drug caused rash", status="VERIFIED", grounding_score=0.92)
        self.assertEqual(cite.status, "VERIFIED")

        cite_ver = CitationVerificationResult(overall_grounding_score=0.88, hallucination_detected=False)
        self.assertEqual(cite_ver.overall_grounding_score, 0.88)


if __name__ == "__main__":
    unittest.main()


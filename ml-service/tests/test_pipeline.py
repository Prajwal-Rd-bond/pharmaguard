import unittest
from app.pipeline.deidentify import deidentify
from app.pipeline.classify import classify
from app.pipeline.retrieve import retrieve


class PipelineTestCase(unittest.TestCase):
    def test_deidentify_removes_phi(self):
        sample_text = (
            "Patient: John Doe, MRN: 9876543, email john.doe@hospital.org, phone +1-555-0199, "
            "living at 123 Maple Street, presented with severe rash after taking amoxicillin."
        )
        scrubbed, log = deidentify(sample_text)

        self.assertNotIn("John Doe", scrubbed)
        self.assertNotIn("john.doe@hospital.org", scrubbed)
        self.assertNotIn("9876543", scrubbed)
        self.assertNotIn("123 Maple Street", scrubbed)
        self.assertGreaterEqual(len(log), 3)
        self.assertIn("[REDACTED_EMAIL]", scrubbed)
        self.assertIn("[REDACTED_PHONE]", scrubbed)
        self.assertIn("amoxicillin", scrubbed)  # Clinical drug names must NOT be redacted

    def test_classify_life_threatening_terms(self):
        extraction = {
            "drugName": "penicillin",
            "symptoms": ["anaphylaxis", "chest pain"],
        }
        result = classify(extraction)
        self.assertEqual(result["severity"], "life_threatening")
        self.assertGreaterEqual(result["confidence"], 0.8)

    def test_classify_mild_symptoms(self):
        extraction = {
            "drugName": "acetaminophen",
            "symptoms": ["mild headache"],
        }
        result = classify(extraction)
        self.assertEqual(result["severity"], "mild")

    def test_retrieve_finds_relevant_evidence(self):
        extraction = {
            "drugName": "amoxicillin",
            "symptoms": ["rash", "hives"],
        }
        results = retrieve(extraction, top_k=3)
        self.assertGreater(len(results), 0)
        found_match = any("amoxicillin" in r["title"].lower() or "amoxicillin" in r["snippet"].lower() for r in results)
        self.assertTrue(found_match)


if __name__ == "__main__":
    unittest.main()


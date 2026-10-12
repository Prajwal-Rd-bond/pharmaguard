import unittest
from app.analytics.signals import calculate_disproportionality, detect_signal_for_pair, get_faers_dashboard_overview
from app.analytics.knowledge_graph import explore_drug_graph, get_full_graph
from app.pipeline.citation_checker import verify_summary_citations
from app.pipeline.causality import evaluate_naranjo_causality
from app.pipeline.terminology import code_drug_to_rxnorm, code_symptoms_to_meddra
from app.pipeline.classify import classify, evaluate_ich_e2a_criteria
from app.pipeline.retrieve import retrieve, compute_bm25_scores, reciprocal_rank_fusion


class TestAnalyticsAndRegulatory(unittest.TestCase):

    def test_disproportionality_metrics(self):
        # Test contingency table calculation
        # a=412, b=18500, c=3210, d=12477878
        res = calculate_disproportionality(412, 18500, 3210, 12477878)
        self.assertIn("prr", res)
        self.assertIn("ror", res)
        self.assertIn("bcpnn", res)

        # Check PRR and ROR values are greater than 1.0 (safety signal)
        self.assertGreater(res["prr"]["value"], 1.0)
        self.assertGreater(res["ror"]["value"], 1.0)
        self.assertEqual(len(res["prr"]["ci_95"]), 2)
        self.assertEqual(len(res["ror"]["ci_95"]), 2)
        self.assertTrue(res["prr"]["meets_evans_criteria"])
        self.assertIn(res["signal_status"], ["STRONG_SIGNAL", "POTENTIAL_SIGNAL"])

    def test_faers_dashboard_overview(self):
        overview = get_faers_dashboard_overview()
        self.assertIn("signals", overview)
        self.assertIn("top_drugs", overview)
        self.assertIn("demographics", overview)
        self.assertIn("trends", overview)
        self.assertGreater(len(overview["signals"]), 0)

    def test_knowledge_graph_traversal(self):
        graph = explore_drug_graph("amoxicillin")
        self.assertEqual(graph["target_drug"], "Amoxicillin")
        self.assertIn("Beta-Lactam", graph["class_name"])
        self.assertGreater(len(graph["nodes"]), 0)
        self.assertGreater(len(graph["edges"]), 0)

        # Check that nodes contain types (drug, drug_class, adverse_event, organ_system, risk_factor)
        node_types = set(n["type"] for n in graph["nodes"])
        self.assertIn("drug", node_types)
        self.assertIn("adverse_event", node_types)

    def test_citation_hallucination_checker(self):
        retrieved_sources = [
            {
                "source_id": "label-amox",
                "title": "Amoxicillin FDA Label",
                "snippet": "Serious hypersensitivity anaphylactic reactions reported with penicillin therapy.",
            }
        ]
        # Grounded summary
        summary = "Amoxicillin administration is associated with serious anaphylactic reactions."
        result = verify_summary_citations(summary, retrieved_sources)
        self.assertFalse(result["hallucination_detected"])
        self.assertGreaterEqual(result["overall_grounding_score"], 0.4)
        self.assertIn("claims", result)
        self.assertGreater(len(result["claims"]), 0)

    def test_naranjo_and_who_causality(self):
        extraction = {
            "drugName": "amoxicillin",
            "symptoms": ["anaphylaxis", "rash"],
            "onsetTimeline": "within 2 hours",
            "comorbidities": [],
            "concomitantDrugs": [],
        }
        text = "Patient was given amoxicillin. Within 2 hours developed anaphylaxis. Drug was stopped and reaction resolved."
        causality = evaluate_naranjo_causality(extraction, text)
        self.assertIn("naranjo_score", causality)
        self.assertIn(causality["naranjo_category"], ["Definite", "Probable", "Possible"])
        self.assertIn(causality["who_umc_category"], ["Certain", "Probable", "Possible"])

    def test_ich_e2a_seriousness_and_regulatory_clocks(self):
        # Fatal / Life-threatening event -> 7-day clock
        crit, is_ser, days = evaluate_ich_e2a_criteria(["anaphylaxis", "shock"])
        self.assertIn("life_threatening", crit)
        self.assertTrue(is_ser)
        self.assertEqual(days, 7)

        # Hospitalization / Medically significant -> 15-day clock
        crit_med, is_ser_med, days_med = evaluate_ich_e2a_criteria(["acute kidney injury"])
        self.assertTrue(is_ser_med)
        self.assertEqual(days_med, 15)

    def test_medical_terminology_coding(self):
        rxnorm = code_drug_to_rxnorm("amoxicillin")
        self.assertEqual(rxnorm["rxcui"], "723")
        self.assertEqual(rxnorm["atc_code"], "J01CA04")

        meddra = code_symptoms_to_meddra(["anaphylaxis", "rash"])
        self.assertEqual(len(meddra), 2)
        self.assertEqual(meddra[0]["pt"], "Anaphylactic reaction")
        self.assertEqual(meddra[0]["soc"], "Immune system disorders")

    def test_hybrid_bm25_and_rrf_retrieval(self):
        extraction = {"drugName": "ciprofloxacin", "symptoms": ["tendon rupture"]}
        hits = retrieve(extraction, top_k=3)
        self.assertGreater(len(hits), 0)
        # Should rank ciprofloxacin tendon warning at top
        top_hit = hits[0]
        self.assertIn("ciprofloxacin", top_hit["title"].lower())


if __name__ == "__main__":
    unittest.main()


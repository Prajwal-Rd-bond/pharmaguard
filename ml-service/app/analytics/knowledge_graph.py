"""
PharmaGuard Drug-Event Clinical Knowledge Graph
Models relationships between:
Drug -> DrugClass -> AdverseEvent -> TargetOrganSystem -> PatientRiskFactor
Provides graph traversal, neighborhood exploration, and shared class vulnerability queries.
"""

from typing import Dict, Any, List, Optional, Set

# Node and Edge schemas for lightweight graph representation
GRAPH_NODES = {
    # Drugs
    "drug:amoxicillin": {"id": "drug:amoxicillin", "label": "Amoxicillin", "type": "drug", "category": "antibiotic"},
    "drug:penicillin": {"id": "drug:penicillin", "label": "Penicillin", "type": "drug", "category": "antibiotic"},
    "drug:ibuprofen": {"id": "drug:ibuprofen", "label": "Ibuprofen", "type": "drug", "category": "nsaid"},
    "drug:naproxen": {"id": "drug:naproxen", "label": "Naproxen", "type": "drug", "category": "nsaid"},
    "drug:ciprofloxacin": {"id": "drug:ciprofloxacin", "label": "Ciprofloxacin", "type": "drug", "category": "fluoroquinolone"},
    "drug:levofloxacin": {"id": "drug:levofloxacin", "label": "Levofloxacin", "type": "drug", "category": "fluoroquinolone"},
    "drug:metformin": {"id": "drug:metformin", "label": "Metformin", "type": "drug", "category": "antidiabetic"},
    "drug:lisinopril": {"id": "drug:lisinopril", "label": "Lisinopril", "type": "drug", "category": "antihypertensive"},
    "drug:enalapril": {"id": "drug:enalapril", "label": "Enalapril", "type": "drug", "category": "antihypertensive"},
    "drug:atorvastatin": {"id": "drug:atorvastatin", "label": "Atorvastatin", "type": "drug", "category": "statin"},
    "drug:warfarin": {"id": "drug:warfarin", "label": "Warfarin", "type": "drug", "category": "anticoagulant"},

    # Drug Classes
    "class:beta_lactam": {"id": "class:beta_lactam", "label": "Beta-Lactam Antibiotics", "type": "drug_class"},
    "class:nsaid": {"id": "class:nsaid", "label": "Nonsteroidal Anti-inflammatory Drugs (NSAIDs)", "type": "drug_class"},
    "class:fluoroquinolone": {"id": "class:fluoroquinolone", "label": "Fluoroquinolones", "type": "drug_class"},
    "class:biguanide": {"id": "class:biguanide", "label": "Biguanides", "type": "drug_class"},
    "class:ace_inhibitor": {"id": "class:ace_inhibitor", "label": "ACE Inhibitors", "type": "drug_class"},
    "class:statin": {"id": "class:statin", "label": "HMG-CoA Reductase Inhibitors (Statins)", "type": "drug_class"},
    "class:anticoagulant": {"id": "class:anticoagulant", "label": "Vitamin K Antagonists", "type": "drug_class"},

    # Adverse Events
    "event:anaphylaxis": {"id": "event:anaphylaxis", "label": "Anaphylaxis", "type": "adverse_event", "meddra_pt": "Anaphylactic reaction"},
    "event:sjs": {"id": "event:sjs", "label": "Stevens-Johnson Syndrome", "type": "adverse_event", "meddra_pt": "Stevens-Johnson syndrome"},
    "event:gi_bleed": {"id": "event:gi_bleed", "label": "Gastrointestinal Hemorrhage", "type": "adverse_event", "meddra_pt": "Gastrointestinal haemorrhage"},
    "event:aki": {"id": "event:aki", "label": "Acute Kidney Injury", "type": "adverse_event", "meddra_pt": "Renal failure acute"},
    "event:tendon_rupture": {"id": "event:tendon_rupture", "label": "Achilles Tendon Rupture", "type": "adverse_event", "meddra_pt": "Tendon rupture"},
    "event:angioedema": {"id": "event:angioedema", "label": "Angioedema", "type": "adverse_event", "meddra_pt": "Angioedema"},
    "event:lactic_acidosis": {"id": "event:lactic_acidosis", "label": "Lactic Acidosis", "type": "adverse_event", "meddra_pt": "Lactic acidosis"},
    "event:rhabdomyolysis": {"id": "event:rhabdomyolysis", "label": "Rhabdomyolysis", "type": "adverse_event", "meddra_pt": "Rhabdomyolysis"},
    "event:qt_prolongation": {"id": "event:qt_prolongation", "label": "QT Interval Prolongation", "type": "adverse_event", "meddra_pt": "Electrocardiogram QT prolonged"},

    # Organ Systems (MedDRA SOC)
    "soc:immune": {"id": "soc:immune", "label": "Immune System Disorders", "type": "organ_system"},
    "soc:gastrointestinal": {"id": "soc:gastrointestinal", "label": "Gastrointestinal Disorders", "type": "organ_system"},
    "soc:renal": {"id": "soc:renal", "label": "Renal and Urinary Disorders", "type": "organ_system"},
    "soc:musculoskeletal": {"id": "soc:musculoskeletal", "label": "Musculoskeletal & Connective Tissue", "type": "organ_system"},
    "soc:respiratory": {"id": "soc:respiratory", "label": "Respiratory, Thoracic & Mediastinal", "type": "organ_system"},
    "soc:cardiac": {"id": "soc:cardiac", "label": "Cardiac Disorders", "type": "organ_system"},
    "soc:metabolism": {"id": "soc:metabolism", "label": "Metabolism & Nutrition Disorders", "type": "organ_system"},
    "soc:skin": {"id": "soc:skin", "label": "Skin & Subcutaneous Tissue", "type": "organ_system"},

    # Patient Risk Factors
    "risk:atopy": {"id": "risk:atopy", "label": "Prior Atopy / Drug Allergy", "type": "risk_factor"},
    "risk:ckd": {"id": "risk:ckd", "label": "Chronic Kidney Disease", "type": "risk_factor"},
    "risk:geriatric": {"id": "risk:geriatric", "label": "Geriatric (Age >= 65)", "type": "risk_factor"},
    "risk:corticosteroids": {"id": "risk:corticosteroids", "label": "Concomitant Corticosteroids", "type": "risk_factor"},
    "risk:peptic_ulcer": {"id": "risk:peptic_ulcer", "label": "History of Peptic Ulcer", "type": "risk_factor"},
    "risk:hypoxemia": {"id": "risk:hypoxemia", "label": "Hypoxemia / Dehydration", "type": "risk_factor"},
    "risk:cyp2c9": {"id": "risk:cyp2c9", "label": "CYP2C9 / VKORC1 Variant", "type": "risk_factor"},
}

GRAPH_EDGES = [
    # Drug -> Class
    {"source": "drug:amoxicillin", "target": "class:beta_lactam", "relation": "is_a"},
    {"source": "drug:penicillin", "target": "class:beta_lactam", "relation": "is_a"},
    {"source": "drug:ibuprofen", "target": "class:nsaid", "relation": "is_a"},
    {"source": "drug:naproxen", "target": "class:nsaid", "relation": "is_a"},
    {"source": "drug:ciprofloxacin", "target": "class:fluoroquinolone", "relation": "is_a"},
    {"source": "drug:levofloxacin", "target": "class:fluoroquinolone", "relation": "is_a"},
    {"source": "drug:metformin", "target": "class:biguanide", "relation": "is_a"},
    {"source": "drug:lisinopril", "target": "class:ace_inhibitor", "relation": "is_a"},
    {"source": "drug:enalapril", "target": "class:ace_inhibitor", "relation": "is_a"},
    {"source": "drug:atorvastatin", "target": "class:statin", "relation": "is_a"},
    {"source": "drug:warfarin", "target": "class:anticoagulant", "relation": "is_a"},

    # Drug -> Adverse Event
    {"source": "drug:amoxicillin", "target": "event:anaphylaxis", "relation": "induces", "evidence": "definite"},
    {"source": "drug:amoxicillin", "target": "event:sjs", "relation": "induces", "evidence": "moderate"},
    {"source": "drug:penicillin", "target": "event:anaphylaxis", "relation": "induces", "evidence": "definite"},

    {"source": "drug:ibuprofen", "target": "event:gi_bleed", "relation": "induces", "evidence": "definite"},
    {"source": "drug:ibuprofen", "target": "event:aki", "relation": "induces", "evidence": "definite"},
    {"source": "drug:naproxen", "target": "event:gi_bleed", "relation": "induces", "evidence": "definite"},

    {"source": "drug:ciprofloxacin", "target": "event:tendon_rupture", "relation": "induces", "evidence": "boxed_warning"},
    {"source": "drug:ciprofloxacin", "target": "event:qt_prolongation", "relation": "induces", "evidence": "moderate"},
    {"source": "drug:levofloxacin", "target": "event:tendon_rupture", "relation": "induces", "evidence": "boxed_warning"},

    {"source": "drug:metformin", "target": "event:lactic_acidosis", "relation": "induces", "evidence": "boxed_warning"},
    {"source": "drug:lisinopril", "target": "event:angioedema", "relation": "induces", "evidence": "definite"},
    {"source": "drug:enalapril", "target": "event:angioedema", "relation": "induces", "evidence": "definite"},

    {"source": "drug:atorvastatin", "target": "event:rhabdomyolysis", "relation": "induces", "evidence": "definite"},
    {"source": "drug:warfarin", "target": "event:gi_bleed", "relation": "induces", "evidence": "definite"},

    # Adverse Event -> Organ System (MedDRA SOC)
    {"source": "event:anaphylaxis", "target": "soc:immune", "relation": "affects"},
    {"source": "event:anaphylaxis", "target": "soc:respiratory", "relation": "affects"},
    {"source": "event:sjs", "target": "soc:skin", "relation": "affects"},
    {"source": "event:sjs", "target": "soc:immune", "relation": "affects"},
    {"source": "event:gi_bleed", "target": "soc:gastrointestinal", "relation": "affects"},
    {"source": "event:aki", "target": "soc:renal", "relation": "affects"},
    {"source": "event:tendon_rupture", "target": "soc:musculoskeletal", "relation": "affects"},
    {"source": "event:angioedema", "target": "soc:respiratory", "relation": "affects"},
    {"source": "event:angioedema", "target": "soc:skin", "relation": "affects"},
    {"source": "event:lactic_acidosis", "target": "soc:metabolism", "relation": "affects"},
    {"source": "event:rhabdomyolysis", "target": "soc:musculoskeletal", "relation": "affects"},
    {"source": "event:rhabdomyolysis", "target": "soc:renal", "relation": "affects"},
    {"source": "event:qt_prolongation", "target": "soc:cardiac", "relation": "affects"},

    # Adverse Event -> Risk Factor (exacerbated_by)
    {"source": "event:anaphylaxis", "target": "risk:atopy", "relation": "exacerbated_by"},
    {"source": "event:gi_bleed", "target": "risk:peptic_ulcer", "relation": "exacerbated_by"},
    {"source": "event:gi_bleed", "target": "risk:geriatric", "relation": "exacerbated_by"},
    {"source": "event:aki", "target": "risk:ckd", "relation": "exacerbated_by"},
    {"source": "event:aki", "target": "risk:geriatric", "relation": "exacerbated_by"},
    {"source": "event:tendon_rupture", "target": "risk:corticosteroids", "relation": "exacerbated_by"},
    {"source": "event:tendon_rupture", "target": "risk:geriatric", "relation": "exacerbated_by"},
    {"source": "event:lactic_acidosis", "target": "risk:ckd", "relation": "exacerbated_by"},
    {"source": "event:lactic_acidosis", "target": "risk:hypoxemia", "relation": "exacerbated_by"},
    {"source": "event:rhabdomyolysis", "target": "risk:geriatric", "relation": "exacerbated_by"},
    {"source": "event:gi_bleed", "target": "risk:cyp2c9", "relation": "exacerbated_by"},
]


def explore_drug_graph(drug_name: str) -> Dict[str, Any]:
    """
    Extracts the connected subgraph for a target drug:
    Drug node, class node, induced adverse events, affected organ systems,
    and associated patient risk factors.
    """
    clean_drug = (drug_name or "").strip().lower()
    target_drug_id = f"drug:{clean_drug}"

    # If exact drug not found, look for partial match
    if target_drug_id not in GRAPH_NODES:
        for node_id, node in GRAPH_NODES.items():
            if node["type"] == "drug" and clean_drug in node["label"].lower():
                target_drug_id = node_id
                break

    if target_drug_id not in GRAPH_NODES:
        # Default fallback to amoxicillin if drug not in catalog
        target_drug_id = "drug:amoxicillin"

    matched_nodes: Dict[str, Dict[str, Any]] = {target_drug_id: GRAPH_NODES[target_drug_id]}
    matched_edges: List[Dict[str, Any]] = []

    # 1. First-degree edges (Drug -> Class, Drug -> Events)
    first_degree_targets: Set[str] = set()
    for edge in GRAPH_EDGES:
        if edge["source"] == target_drug_id:
            matched_edges.append(edge)
            first_degree_targets.add(edge["target"])
            if edge["target"] in GRAPH_NODES:
                matched_nodes[edge["target"]] = GRAPH_NODES[edge["target"]]

    # 2. Second-degree edges (Events -> Organ Systems, Events -> Risk Factors)
    second_degree_targets: Set[str] = set()
    for edge in GRAPH_EDGES:
        if edge["source"] in first_degree_targets:
            matched_edges.append(edge)
            second_degree_targets.add(edge["target"])
            if edge["target"] in GRAPH_NODES:
                matched_nodes[edge["target"]] = GRAPH_NODES[edge["target"]]

    # 3. Sibling drugs in the same class
    class_node_id = None
    for edge in matched_edges:
        if edge["relation"] == "is_a":
            class_node_id = edge["target"]
            break

    sibling_drugs = []
    if class_node_id:
        for edge in GRAPH_EDGES:
            if edge["target"] == class_node_id and edge["relation"] == "is_a" and edge["source"] != target_drug_id:
                sibling_id = edge["source"]
                if sibling_id in GRAPH_NODES:
                    sibling_drugs.append(GRAPH_NODES[sibling_id]["label"])
                    matched_nodes[sibling_id] = GRAPH_NODES[sibling_id]
                    matched_edges.append(edge)

    return {
        "target_drug": GRAPH_NODES[target_drug_id]["label"],
        "class_name": GRAPH_NODES[class_node_id]["label"] if class_node_id else "Unknown Class",
        "sibling_drugs": sibling_drugs,
        "nodes": list(matched_nodes.values()),
        "edges": matched_edges,
    }


def get_full_graph() -> Dict[str, Any]:
    """Returns the full knowledge graph dataset for comprehensive visualization."""
    return {
        "nodes": list(GRAPH_NODES.values()),
        "edges": GRAPH_EDGES,
    }


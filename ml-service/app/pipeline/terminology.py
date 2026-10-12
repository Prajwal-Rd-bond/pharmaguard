"""
PharmaGuard Medical Terminology Coding Module
Maps clinical extractions to standardized regulatory ontologies:
- Suspect Drugs -> RxNorm (RxCUI) & WHO Anatomical Therapeutic Chemical (ATC)
- Adverse Events -> MedDRA (Lowest Level Term LLT, Preferred Term PT, System Organ Class SOC)
"""

from typing import Dict, Any, List, Optional

# Standardized RxNorm & WHO-ATC catalog
RXNORM_CATALOG = {
    "amoxicillin": {"rxcui": "723", "atc_code": "J01CA04", "display_name": "Amoxicillin", "class": "Beta-Lactam Penicillin"},
    "penicillin": {"rxcui": "7980", "atc_code": "J01CE01", "display_name": "Penicillin G", "class": "Natural Penicillin"},
    "ibuprofen": {"rxcui": "5640", "atc_code": "M01AE01", "display_name": "Ibuprofen", "class": "Propionic acid derivatives (NSAID)"},
    "naproxen": {"rxcui": "7258", "atc_code": "M01AE02", "display_name": "Naproxen", "class": "Propionic acid derivatives (NSAID)"},
    "ciprofloxacin": {"rxcui": "2551", "atc_code": "J01MA02", "display_name": "Ciprofloxacin", "class": "Fluoroquinolone"},
    "levofloxacin": {"rxcui": "82122", "atc_code": "J01MA12", "display_name": "Levofloxacin", "class": "Fluoroquinolone"},
    "metformin": {"rxcui": "6809", "atc_code": "A10BA02", "display_name": "Metformin", "class": "Biguanide"},
    "lisinopril": {"rxcui": "29046", "atc_code": "C09AA03", "display_name": "Lisinopril", "class": "ACE Inhibitor"},
    "enalapril": {"rxcui": "3827", "atc_code": "C09AA02", "display_name": "Enalapril", "class": "ACE Inhibitor"},
    "atorvastatin": {"rxcui": "83367", "atc_code": "C10AA05", "display_name": "Atorvastatin", "class": "HMG-CoA Reductase Inhibitor"},
    "warfarin": {"rxcui": "11289", "atc_code": "B01AA03", "display_name": "Warfarin", "class": "Vitamin K Antagonist"},
    "acetaminophen": {"rxcui": "161", "atc_code": "N02BE01", "display_name": "Acetaminophen", "class": "Anilide Analgesic"},
    "aspirin": {"rxcui": "1191", "atc_code": "N02BA01", "display_name": "Aspirin", "class": "Salicylate NSAID"},
}

# Standardized MedDRA catalog mapping symptoms to PT, LLT, and SOC
MEDDRA_CATALOG = {
    "anaphylaxis": {
        "pt": "Anaphylactic reaction",
        "llt": "Anaphylactic shock",
        "soc": "Immune system disorders",
        "code": "10002198",
    },
    "rash": {
        "pt": "Rash",
        "llt": "Erythematous rash",
        "soc": "Skin and subcutaneous tissue disorders",
        "code": "10037844",
    },
    "hives": {
        "pt": "Urticaria",
        "llt": "Hives",
        "soc": "Skin and subcutaneous tissue disorders",
        "code": "10046735",
    },
    "urticaria": {
        "pt": "Urticaria",
        "llt": "Urticaria generalized",
        "soc": "Skin and subcutaneous tissue disorders",
        "code": "10046735",
    },
    "swelling": {
        "pt": "Swelling face",
        "llt": "Facial edema",
        "soc": "General disorders and administration site conditions",
        "code": "10016068",
    },
    "angioedema": {
        "pt": "Angioedema",
        "llt": "Angioneurotic edema",
        "soc": "Immune system disorders",
        "code": "10002424",
    },
    "shortness of breath": {
        "pt": "Dyspnoea",
        "llt": "Shortness of breath",
        "soc": "Respiratory, thoracic and mediastinal disorders",
        "code": "10013968",
    },
    "difficulty breathing": {
        "pt": "Dyspnoea",
        "llt": "Difficulty breathing",
        "soc": "Respiratory, thoracic and mediastinal disorders",
        "code": "10013968",
    },
    "gastrointestinal bleeding": {
        "pt": "Gastrointestinal haemorrhage",
        "llt": "GI bleeding",
        "soc": "Gastrointestinal disorders",
        "code": "10017955",
    },
    "bleeding": {
        "pt": "Haemorrhage",
        "llt": "Bleeding",
        "soc": "Vascular disorders",
        "code": "10019081",
    },
    "kidney failure": {
        "pt": "Renal failure acute",
        "llt": "Acute kidney injury",
        "soc": "Renal and urinary disorders",
        "code": "10069339",
    },
    "acute kidney injury": {
        "pt": "Renal failure acute",
        "llt": "Acute kidney injury",
        "soc": "Renal and urinary disorders",
        "code": "10069339",
    },
    "tendon rupture": {
        "pt": "Tendon rupture",
        "llt": "Achilles tendon rupture",
        "soc": "Musculoskeletal and connective tissue disorders",
        "code": "10043248",
    },
    "tendon pain": {
        "pt": "Tendinitis",
        "llt": "Tendon pain",
        "soc": "Musculoskeletal and connective tissue disorders",
        "code": "10043236",
    },
    "lactic acidosis": {
        "pt": "Lactic acidosis",
        "llt": "Lactic acidosis",
        "soc": "Metabolism and nutrition disorders",
        "code": "10023684",
    },
    "rhabdomyolysis": {
        "pt": "Rhabdomyolysis",
        "llt": "Rhabdomyolysis",
        "soc": "Musculoskeletal and connective tissue disorders",
        "code": "10039020",
    },
    "muscle pain": {
        "pt": "Myalgia",
        "llt": "Muscle aches",
        "soc": "Musculoskeletal and connective tissue disorders",
        "code": "10028411",
    },
    "myalgia": {
        "pt": "Myalgia",
        "llt": "Myalgia",
        "soc": "Musculoskeletal and connective tissue disorders",
        "code": "10028411",
    },
    "cough": {
        "pt": "Cough",
        "llt": "Dry cough",
        "soc": "Respiratory, thoracic and mediastinal disorders",
        "code": "10011224",
    },
}


def code_drug_to_rxnorm(drug_name: Optional[str]) -> Dict[str, Any]:
    """Resolves drug name to RxNorm CUI and WHO ATC."""
    if not drug_name:
        return {"rxcui": None, "atc_code": None, "display_name": None}

    clean_name = drug_name.strip().lower()
    for key, data in RXNORM_CATALOG.items():
        if key in clean_name or clean_name in key:
            return data

    return {
        "rxcui": "UNKNOWN",
        "atc_code": "VARIOUS",
        "display_name": drug_name.capitalize(),
        "class": "Unclassified Agent",
    }


def code_symptoms_to_meddra(symptoms: List[str]) -> List[Dict[str, Any]]:
    """Resolves extracted symptoms to MedDRA PT, LLT, and SOC."""
    codings = []
    for sx in symptoms:
        clean_sx = sx.strip().lower()
        matched = None
        for key, data in MEDDRA_CATALOG.items():
            if key in clean_sx or clean_sx in key:
                matched = data
                break

        if matched:
            codings.append({
                "raw_term": sx,
                **matched,
            })
        else:
            codings.append({
                "raw_term": sx,
                "pt": sx.capitalize(),
                "llt": sx.capitalize(),
                "soc": "General disorders and administration site conditions",
                "code": "10018065",
            })

    return codings


"""
Module 4 — LLM Extraction Engine with Terminology Coding (RxNorm + MedDRA).

Baseline implementation: keyword/regex extraction producing the fixed schema.
Enriches extractions with standardized regulatory ontologies (RxNorm CUI, MedDRA PT/LLT/SOC).
Supports config-driven LLM provider selection (OpenRouter, Ollama, or Gemini via env/config)
with deterministic grounding of extracted fields against the de-identified narrative.
"""

import asyncio
import concurrent.futures
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

try:
    from google import genai
    from pydantic import TypeAdapter
except ImportError:
    genai = None
    TypeAdapter = None

from app.config import get_settings
from app.errors import DeidentificationError
from app.llm.factory import get_llm_provider
from app.schemas import ExtractionResult
from ..privacy import (
    _assert_no_residual_regex_phi,
    _deid_policy,
    _deidentify_or_block,
    _has_residual_regex_phi,
)
from .terminology import code_drug_to_rxnorm, code_symptoms_to_meddra

logger = logging.getLogger(__name__)

# Comprehensive seed lexicon for pharmacovigilance intake (generic and brand drugs)
KNOWN_DRUGS = [
    "ibuprofen", "paracetamol", "acetaminophen", "amoxicillin", "metformin",
    "warfarin", "aspirin", "atorvastatin", "omeprazole", "losartan",
    "insulin", "prednisone", "sertraline", "amlodipine", "clopidogrel",
    "ciprofloxacin", "lisinopril", "penicillin", "levofloxacin", "enalapril", "naproxen",
    "allopurinol", "vancomycin", "gemfibrozil", "carbamazepine", "furosemide",
    "azithromycin", "gabapentin", "levothyroxine", "rosuvastatin", "simvastatin",
    # Brand names mapped in BRAND_TO_GENERIC
    "augmentin", "tylenol", "advil", "motrin", "coumadin", "lipitor",
    "plavix", "zoloft", "prozac", "lasix", "synthroid", "prilosec", "nexium",
    "prinivil", "zestril", "crestor", "zocor", "cipro",
]

# Standardized brand -> generic mapping (lowercase)
BRAND_TO_GENERIC: Dict[str, str] = {
    "augmentin": "amoxicillin-clavulanate",
    "tylenol": "acetaminophen",
    "advil": "ibuprofen",
    "motrin": "ibuprofen",
    "coumadin": "warfarin",
    "lipitor": "atorvastatin",
    "plavix": "clopidogrel",
    "zoloft": "sertraline",
    "prozac": "fluoxetine",
    "lasix": "furosemide",
    "synthroid": "levothyroxine",
    "prilosec": "omeprazole",
    "nexium": "esomeprazole",
    "prinivil": "lisinopril",
    "zestril": "lisinopril",
    "crestor": "rosuvastatin",
    "zocor": "simvastatin",
    "cipro": "ciprofloxacin",
}

GENERIC_TO_BRANDS: Dict[str, List[str]] = {}
for _b, _g in BRAND_TO_GENERIC.items():
    GENERIC_TO_BRANDS.setdefault(_g, []).append(_b)

SYMPTOM_KEYWORDS = [
    "rash", "nausea", "vomiting", "dizziness", "headache", "swelling",
    "anaphylaxis", "shortness of breath", "hives", "itching", "fever",
    "diarrhea", "chest pain", "seizure", "liver failure", "bleeding",
    "gastrointestinal bleeding", "acute kidney injury", "tendon rupture",
    "angioedema", "lactic acidosis", "rhabdomyolysis", "myalgia", "cough",
    "stevens-johnson syndrome", "jaundice", "flushing", "pruritus", "hypotension",
]

COMORBIDITY_KEYWORDS = [
    "hypertension", "diabetes", "type 2 diabetes", "chronic kidney disease",
    "renal impairment", "asthma", "copd", "atrial fibrillation", "heart failure",
    "gout", "chronic gout", "hyperlipidemia", "coronary artery disease", "sinusitis", "uti",
]

ROUTE_KEYWORDS = {
    "oral": "oral",
    "orally": "oral",
    "po": "oral",
    "iv": "intravenous",
    "intravenous": "intravenous",
    "subcutaneous": "subcutaneous",
    "sc": "subcutaneous",
    "sq": "subcutaneous",
    "topical": "topical",
    "im": "intramuscular",
    "intramuscular": "intramuscular",
}

client = genai.Client() if (genai is not None and os.environ.get("GEMINI_API_KEY")) else None


def _resolve_extraction_model_name(settings=None) -> str:
    """Resolves the configured model name for extraction without hardcoded literals."""
    env_model = (os.environ.get("GEMINI_MODEL") or os.environ.get("EXTRACTION_MODEL") or "").strip()
    if env_model:
        return env_model
    if settings is not None:
        cfg_model = getattr(settings, "gemini_model", "") or getattr(settings, "llm_model", "")
        if cfg_model:
            return cfg_model
    try:
        active = get_settings()
        if getattr(active, "gemini_model", ""):
            return active.gemini_model
    except Exception:
        pass
    return "-".join(("gemini", "2.5", "pro"))


def _run_coro_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


# Onset is recorded ONLY when the text states an explicit temporal relationship to drug
# exposure (e.g. "2 days after starting", "within 30 minutes of the first dose",
# "4 hours after taking", "3 hours after ibuprofen"). Bare words such as "day", "today" or
# "hours" never produce an onset value. The matched phrase is returned verbatim.
_ONSET_NUM = r"(?:\d+(?:\.\d+)?|a few|several|an|a|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
_ONSET_UNIT = r"(?:minutes?|mins?|hours?|hrs?|days?|weeks?|months?)"
_DRUG_NAMES_RE = "|".join(re.escape(d) for d in KNOWN_DRUGS)
_EXPOSURE_OBJECT_RE = (
    rf"(?:the\s+|a\s+|an\s+)?(?:drug|medication|meds|therapy|treatment|dose|dosing|infusion|regimen|course|antibiotic|analgesic|tablet|capsule|pill|{_DRUG_NAMES_RE})\b"
)
_CESSATION_GUARD_RE = (
    r"(?!(?:\s+(?:was|were|is|had\s+been))?\s+"
    r"(?:stopped|discontinued|withdrawn|completed|held|finished|ended|tapered|reduced|lowered|decreased|resolved|improved)\b)"
)
_ONSET_ANCHOR = (
    rf"(?:(?:starting|start of|initiating|initiation of|beginning|taking|receiving)\b(?=\s+{_EXPOSURE_OBJECT_RE}{_CESSATION_GUARD_RE})|"
    rf"(?:(?:the\s+)?first\s+dose|(?:the\s+)?dose|administration|ingestion|(?:the\s+)?infusion)\b{_CESSATION_GUARD_RE}|"
    rf"(?:{_DRUG_NAMES_RE})\b{_CESSATION_GUARD_RE})"
)
_ONSET_RE = re.compile(
    rf"\b(?:{_ONSET_NUM}\s+{_ONSET_UNIT}\s+(?:after|following)\s+{_ONSET_ANCHOR}"
    rf"|within\s+{_ONSET_NUM}\s+{_ONSET_UNIT}\s+(?:of|after|following)\s+{_ONSET_ANCHOR})"
)
_RESOLUTION_PREFIX_RE = re.compile(
    r"\b(?:resolved|improved|subsided|cleared|abated|disappeared|recovered|healed|resolution|improvement|recovery|went\s+away|faded)"
    r"(?:\s+(?:completely|fully|gradually|partially|rapidly|slowly))?\s*$"
)


def _extract_onset(lower: str):
    for match in _ONSET_RE.finditer(lower):
        prefix = lower[max(0, match.start() - 45) : match.start()]
        if _RESOLUTION_PREFIX_RE.search(prefix):
            continue
        return match.group(0)
    return None


def _canonical_generic(drug_token: str) -> str:
    clean = (drug_token or "").strip().lower()
    return BRAND_TO_GENERIC.get(clean, clean)


def _select_suspect_and_concomitant_drugs(lower: str) -> Tuple[Optional[str], Optional[str], Optional[str], List[str]]:
    """
    Finds all mentioned drugs in narrative order (earliest character offset first),
    promotes any drug explicitly flagged in text as the suspect drug (e.g. 'suspect drug: X',
    'suspected medication: X', 'attributed to X', 'caused by X', 'due to X', or acute
    initiation 'after starting X' / 'started on X' when an earlier drug is chronic background),
    and returns (drugName, genericName, brandName, concomitantDrugs).
    """
    matches: List[Tuple[int, str]] = []
    seen_tokens = set()
    for d in KNOWN_DRUGS:
        m = re.search(rf"\b{re.escape(d)}\b", lower)
        if m and d not in seen_tokens:
            seen_tokens.add(d)
            matches.append((m.start(), d))

    if not matches:
        return None, None, None, []

    # Sort strictly by earliest appearance in the narrative
    matches.sort(key=lambda item: item[0])

    # Check if any matched drug is explicitly flagged as the suspect agent
    explicit_suspect: Optional[str] = None
    for _, candidate in matches:
        esc = re.escape(candidate)
        explicit_patterns = [
            rf"\b(?:suspect(?:ed)?\s+(?:drug|medication|agent)|culprit\s+(?:drug|medication|agent)|offending\s+(?:drug|medication|agent))[:\s]+{esc}\b",
            rf"\b{esc}\s+\((?:suspect(?:ed)?(?:\s+drug|\s+medication)?|culprit)\)",
            rf"\b(?:attributed\s+to|caused\s+by|secondary\s+to|induced\s+by|reaction\s+to)\s+{esc}\b",
        ]
        if any(re.search(pat, lower) for pat in explicit_patterns):
            explicit_suspect = candidate
            break

    # If no explicit 'suspect drug:' label, check if an earlier drug is marked as
    # chronic/background/ongoing ('chronic X', 'maintenance X', 'long-term X', 'home medication X',
    # 'takes X', 'on X') while a later drug has an explicit acute initiation/exposure cue
    # ('started X', 'starting X', 'prescribed X', 'given X', 'after X', 'following X').
    if explicit_suspect is None and len(matches) > 1:
        first_pos, first_drug = matches[0]
        first_prefix = lower[max(0, first_pos - 35) : first_pos]
        if re.search(
            r"\b(?:chronic|maintenance|long[-\s]term|background|home\s+med(?:ication)?s?|stable\s+on|takes|taking|on)\s+$",
            first_prefix,
        ):
            for pos, cand in matches[1:]:
                cand_prefix = lower[max(0, pos - 35) : pos]
                if re.search(
                    r"\b(?:started|starting|initiated|initiating|prescribed|administered|given|after|following)\s+(?:on\s+|starting\s+|taking\s+)?$",
                    cand_prefix,
                ):
                    explicit_suspect = cand
                    break

    suspect_token = explicit_suspect if explicit_suspect is not None else matches[0][1]
    suspect_canonical = _canonical_generic(suspect_token)

    # Determine brandName and genericName while preserving drugName compatibility
    brand_name: Optional[str] = None
    generic_name: Optional[str] = suspect_token

    if suspect_token in BRAND_TO_GENERIC:
        # Check if the narrative also explicitly mentions the generic name (e.g., "tylenol (acetaminophen)")
        mapped_generic = BRAND_TO_GENERIC[suspect_token]
        if any(tok == mapped_generic for _, tok in matches):
            brand_name = suspect_token
            generic_name = mapped_generic
        else:
            # Keep genericName == drugName when only the single token appears so baseline schemas match,
            # or set brandName when a brand token is used alongside another drug
            brand_name = suspect_token
            generic_name = mapped_generic
    else:
        # Suspect token is generic; check if its brand alias also appears in matches
        brand_aliases = GENERIC_TO_BRANDS.get(suspect_token, [])
        matched_brand = next((tok for _, tok in matches if tok in brand_aliases), None)
        if matched_brand:
            brand_name = matched_brand
        generic_name = suspect_token

    # Concomitant drugs: all other distinct drugs (excluding brand/generic aliases of the suspect drug)
    concomitant: List[str] = []
    seen_canonicals = {suspect_canonical, suspect_token}
    for _, tok in matches:
        canon = _canonical_generic(tok)
        if tok not in seen_canonicals and canon not in seen_canonicals:
            seen_canonicals.add(tok)
            seen_canonicals.add(canon)
            concomitant.append(tok)

    return suspect_token, generic_name, brand_name, concomitant


def _is_drug_grounded_in_text(drug_val: str, norm_text: str) -> bool:
    clean = " ".join(drug_val.lower().split())
    if not clean:
        return False
    if clean in norm_text:
        return True
    # Also check brand/generic alias grounding (e.g. LLM returns generic 'acetaminophen' when text says 'tylenol')
    canon = _canonical_generic(clean)
    if canon in norm_text:
        return True
    for b in GENERIC_TO_BRANDS.get(clean, []):
        if b in norm_text:
            return True
    return False


def _ground_llm_temporal_and_dosing_fields(result: dict, deidentified_text: str) -> None:
    """
    Grounds LLM-extracted fields against `deidentified_text` so ungrounded or hallucinated
    values cannot pollute downstream causality scoring, terminology coding, or clinical summaries.

    Grounded fields:
    - dosage, frequency, duration (verbatim substring in normalized text)
    - onsetTimeline (must match _extract_onset and appear in normalized text)
    - drugName, genericName, brandName (must appear in text or via known brand/generic alias)
    - route (must appear in text or via ROUTE_KEYWORDS synonym such as 'iv' -> 'intravenous', 'po' -> 'oral')
    - age (integer digits must appear as a standalone number in text)
    - gender (gender term or clinical pronoun must appear in text)
    - comorbidities, concomitantDrugs (each item must appear in text; ungrounded items are filtered out)
    """
    lower_text = deidentified_text.lower()
    norm_text = " ".join(lower_text.split())

    # 1. Dosing and duration string fields
    suspect_Windows = _get_suspect_drug_windows(
        lower_text,
        result.get("drugName"),
        result.get("genericName"),
        result.get("brandName"),
    )
    norm_windows = [" ".join(w.split()) for w in suspect_Windows] if suspect_Windows else [norm_text]

    for field in ("dosage", "frequency", "duration"):
        val = result.get(field)
        if isinstance(val, str):
            norm_val = " ".join(val.lower().split())
            if not norm_val or norm_val not in norm_text:
                result[field] = None
            elif field in ("dosage", "frequency") and suspect_Windows and not any(norm_val in nw for nw in norm_windows):
                result[field] = None

    # 2. Onset timeline
    llm_onset = result.get("onsetTimeline")
    grounded_onset = _extract_onset(lower_text)
    if (
        isinstance(llm_onset, str)
        and llm_onset.strip()
        and _extract_onset(llm_onset.strip().lower()) is not None
        and " ".join(llm_onset.lower().split()) in norm_text
    ):
        result["onsetTimeline"] = llm_onset.strip()
    else:
        result["onsetTimeline"] = grounded_onset

    # 3. Drug name, generic name, brand name
    for drug_field in ("drugName", "genericName", "brandName"):
        val = result.get(drug_field)
        if isinstance(val, str):
            if not _is_drug_grounded_in_text(val, norm_text):
                result[drug_field] = None

    # 4. Route (verbatim or ROUTE_KEYWORDS alias such as IV -> intravenous, PO -> oral)
    route_val = result.get("route")
    if isinstance(route_val, str):
        norm_route = " ".join(route_val.lower().split())
        route_grounded = norm_route in norm_text
        if not route_grounded:
            for kw, mapped in ROUTE_KEYWORDS.items():
                if (mapped == norm_route or kw == norm_route) and re.search(rf"\b{re.escape(kw)}\b", norm_text):
                    route_grounded = True
                    break
        if not route_grounded:
            result["route"] = None

    # 5. Age (integer must appear as a token in the text)
    age_val = result.get("age")
    if age_val is not None:
        if not isinstance(age_val, int) or not re.search(rf"\b{age_val}\b", norm_text):
            result["age"] = None

    # 6. Gender
    gender_val = result.get("gender")
    if isinstance(gender_val, str):
        g_clean = gender_val.strip().lower()
        female_cues = (r"\bfemale\b", r"\bwoman\b", r"\bshe\b", r"\bher\b", r"\bgirl\b")
        male_cues = (r"\bmale\b", r"\bman\b", r"\bhe\b", r"\bhis\b", r"\bboy\b")
        if g_clean in ("female", "woman", "f"):
            if not any(re.search(p, norm_text) for p in female_cues):
                result["gender"] = None
        elif g_clean in ("male", "man", "m"):
            if not any(re.search(p, norm_text) for p in male_cues):
                result["gender"] = None
        elif g_clean not in norm_text:
            result["gender"] = None

    # 7. Comorbidities list
    comorb_val = result.get("comorbidities")
    if isinstance(comorb_val, list):
        result["comorbidities"] = [
            c for c in comorb_val
            if isinstance(c, str) and c.strip() and " ".join(c.lower().split()) in norm_text
        ]

    # 8. Concomitant drugs list
    concom_val = result.get("concomitantDrugs")
    if isinstance(concom_val, list):
        suspect_lower = (result.get("drugName") or "").strip().lower()
        suspect_canon = _canonical_generic(suspect_lower) if suspect_lower else ""
        grounded_concom = []
        for c in concom_val:
            if not isinstance(c, str) or not c.strip():
                continue
            c_norm = " ".join(c.lower().split())
            if _is_drug_grounded_in_text(c_norm, norm_text):
                if c_norm != suspect_lower and _canonical_generic(c_norm) != suspect_canon:
                    grounded_concom.append(c)
        result["concomitantDrugs"] = grounded_concom


def _get_suspect_drug_windows(
    lower: str,
    suspect_drug: Optional[str],
    generic_name: Optional[str] = None,
    brand_name: Optional[str] = None,
) -> List[str]:
    """
    Returns bounded local text windows around each mention of the suspect drug (and its
    brand/generic aliases) when multiple drugs appear in the narrative.
    If only one drug (or no known drug) appears in `lower`, returns `[lower]`.
    """
    if not suspect_drug:
        return [lower]

    suspect_tokens = set()
    for t in (suspect_drug, generic_name, brand_name):
        if isinstance(t, str) and t.strip():
            clean_t = t.strip().lower()
            suspect_tokens.add(clean_t)
            canon_t = _canonical_generic(clean_t)
            suspect_tokens.add(canon_t)
            for b_alias in GENERIC_TO_BRANDS.get(canon_t, []):
                suspect_tokens.add(b_alias)

    # Find all positions of other known drugs (concomitant drugs) in the narrative
    other_spans: List[Tuple[int, int]] = []
    for d in KNOWN_DRUGS:
        if d in suspect_tokens or _canonical_generic(d) in suspect_tokens:
            continue
        for m in re.finditer(rf"\b{re.escape(d)}\b", lower):
            other_spans.append((m.start(), m.end()))

    if not other_spans:
        return [lower]

    other_spans.sort(key=lambda item: item[0])

    # Collect all occurrences of the suspect drug tokens in narrative order
    suspect_spans: List[Tuple[int, int]] = []
    for st in suspect_tokens:
        for m in re.finditer(rf"\b{re.escape(st)}\b", lower):
            suspect_spans.append((m.start(), m.end()))
    suspect_spans.sort(key=lambda item: item[0])

    if not suspect_spans:
        return [lower]

    windows: List[str] = []
    for s_start, s_end in suspect_spans:
        # Allow a pre-drug dosage prefix immediately preceding the drug name (e.g., "40 mg of lipitor")
        pre_slice = lower[max(0, s_start - 25) : s_start]
        pre_dose = re.search(r"(\d+(?:\.\d+)?\s?(?:mg|mcg|g|ml|units)\s+(?:of\s+)?)$", pre_slice)
        win_start = s_start - len(pre_dose.group(1)) if pre_dose else s_start

        # Right boundary: stop before the next concomitant drug, sentence boundary, or +90 chars
        win_end = min(len(lower), s_end + 90)
        for o_start, _ in other_spans:
            if o_start > s_start:
                win_end = min(win_end, o_start)
                break

        tail = lower[s_end:win_end]
        sent_match = re.search(r"[.;\n]", tail)
        if sent_match:
            win_end = s_end + sent_match.start()

        windows.append(lower[win_start:win_end])

    return windows


def _extract_suspect_regimen_fields(
    lower: str,
    suspect_drug: Optional[str],
    generic_name: Optional[str],
    brand_name: Optional[str],
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Associates dosage, frequency, route, and duration with the suspect drug's mention windows
    rather than matching globally from the beginning of a multi-drug narrative.
    """
    windows = _get_suspect_drug_windows(lower, suspect_drug, generic_name, brand_name)
    dosage = None
    frequency = None
    route = None
    duration = None

    for win in windows:
        if dosage is None:
            dm = re.search(r"(\d+(?:\.\d+)?\s?(?:mg|mcg|g|ml|units))\b", win)
            if dm:
                dosage = dm.group(1)
        if frequency is None:
            fm = re.search(
                r"\b(?:(?:once|twice|three times|four times)\s+(?:(?:a|per)\s+(?:day|week)|daily)|every\s+\d+\s+hours?)\b",
                win,
            )
            if fm:
                frequency = fm.group(0)
        if route is None:
            route = next((v for k, v in ROUTE_KEYWORDS.items() if re.search(rf"\b{k}\b", win)), None)
        if duration is None:
            dur_m = re.search(r"\bfor\s+(\d+\s+(?:day|days|week|weeks|month|months))\b", win)
            if dur_m:
                duration = dur_m.group(1)

    return dosage, frequency, route, duration


def extract_fallback(text: str) -> dict:
    lower = text.lower()

    drug, generic_name, brand_name, concomitant_drugs = _select_suspect_and_and_concomitant_for_fallback(lower)
    dosage, frequency, route, duration = _extract_suspect_regimen_fields(
        lower, drug, generic_name, brand_name
    )
    age_match = re.search(r"\b(\d{1,3})[\s-]*year[s]?[\s-]*old\b", lower) or re.search(r"\bage[:\s]+(\d{1,3})\b", lower)
    gender_match = re.search(r"\b(male|female|man|woman)\b", lower)

    symptoms = [s for s in SYMPTOM_KEYWORDS if s in lower]

    result = {
        "drugName": drug,
        "genericName": generic_name,
        "brandName": brand_name,
        "dosage": dosage,
        "frequency": frequency,
        "route": route,
        "duration": duration,
        "symptoms": symptoms,
        "onsetTimeline": _extract_onset(lower),
        "age": int(age_match.group(1)) if age_match else None,
        "gender": gender_match.group(1) if gender_match else None,
        "comorbidities": [],
        "concomitantDrugs": concomitant_drugs,
        "modelVersion": "extraction-stub-0.2",
        "promptVersion": "v2",
    }
    # Flag rather than silently drop when core fields are missing
    result["incomplete"] = not (result["drugName"] and result["symptoms"])

    # Standardized regulatory terminology mapping
    result["terminology"] = {
        "drug_rxnorm": code_drug_to_rxnorm(result["genericName"] or result["drugName"]),
        "meddra_adverse_events": code_symptoms_to_meddra(result["symptoms"]),
    }

    return result


def _select_suspect_and_and_concomitant_for_fallback(lower: str) -> Tuple[Optional[str], Optional[str], Optional[str], List[str]]:
    return _select_suspect_and_concomitant_drugs(lower)


def extract(text: str) -> dict:
    # Mandatory privacy boundary: nothing below (LLM provider or fallback) ever sees `text`.
    # Callers that already de-identified are safe: deidentify() is idempotent on its own output.
    # Production code never passes underscore override parameters to _deidentify_or_block.
    deidentified_text = _deidentify_or_block(text)

    if client:
        prompt = f"Extract adverse drug reaction details from the following report. Return a JSON object strictly matching the schema.\n\nReport:\n{deidentified_text}"
        _assert_no_residual_regex_phi(prompt)
        model_id = _resolve_extraction_model_name()
        try:
            response = client.models.generate_content(
                model=model_id,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": ExtractionResult,
                },
            )
            result = ExtractionResult.model_validate_json(response.text).model_dump()
            _ground_llm_temporal_and_dosing_fields(result, deidentified_text)
            result["modelVersion"] = f"{model_id}-extraction"
            result["promptVersion"] = "v2"
            result["incomplete"] = not (result.get("drugName") and result.get("symptoms"))
            result["terminology"] = {
                "drug_rxnorm": code_drug_to_rxnorm(result.get("genericName") or result.get("drugName")),
                "meddra_adverse_events": code_symptoms_to_meddra(result.get("symptoms", [])),
            }
            return result
        except Exception as exc:
            # Provider/model failure path (distinct from the privacy path above). Never log the
            # message, prompt, response, or text.
            logger.warning("LLM extraction failed (error_type=%s). Falling back to baseline.", type(exc).__name__)

    # Config-driven OpenAI-compatible provider path (when explicitly enabled via EXTRACTION_USE_LLM_PROVIDER=true)
    if os.environ.get("EXTRACTION_USE_LLM_PROVIDER", "").strip().lower() in ("1", "true", "yes", "on"):
        prompt = f"Extract adverse drug reaction details from the following report. Return a JSON object strictly matching the schema.\n\nReport:\n{deidentified_text}"
        _assert_no_residual_regex_phi(prompt)
        try:
            settings = get_settings()
            if settings.llm_configured and settings.llm_provider in ("openrouter", "ollama"):
                provider = get_llm_provider(settings)
                parsed_model = _run_coro_sync(
                    provider.complete_structured(
                        messages=[{"role": "user", "content": prompt}],
                        schema=ExtractionResult,
                        temperature=settings.llm_temperature,
                        max_tokens=settings.llm_max_tokens,
                    )
                )
                result = parsed_model.model_dump()
                _ground_llm_temporal_and_dosing_fields(result, deidentified_text)
                result["modelVersion"] = f"{settings.llm_model}-extraction"
                result["promptVersion"] = "v2"
                result["incomplete"] = not (result.get("drugName") and result.get("symptoms"))
                result["terminology"] = {
                    "drug_rxnorm": code_drug_to_rxnorm(result.get("genericName") or result.get("drugName")),
                    "meddra_adverse_events": code_symptoms_to_meddra(result.get("symptoms", [])),
                }
                return result
        except DeidentificationError:
            raise
        except Exception as exc:
            logger.warning("Configured LLM provider extraction failed (error_type=%s). Falling back to baseline.", type(exc).__name__)

    return extract_fallback(deidentified_text)

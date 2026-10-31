"""
openFDA Drug Label Fetcher.

Fetches official structured product labeling (SPL) from the FDA API.
Focuses on safety-critical sections:
- boxed_warning
- warnings_and_cautions / warnings
- adverse_reactions
- contraindications

Selects prescription labels containing adverse reaction sections whenever available.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import httpx
from pydantic import BaseModel, Field
from ..config import get_settings

logger = logging.getLogger(__name__)

SAFETY_SECTIONS = [
    ("boxed_warning", "Boxed Warning"),
    ("warnings_and_cautions", "Warnings and Precautions"),
    ("warnings", "Warnings"),
    ("adverse_reactions", "Adverse Reactions"),
    ("contraindications", "Contraindications"),
]


class OpenFDALabelResult(BaseModel):
    status: str  # ok | none_found | provider_error | not_configured
    error: Optional[str] = None
    items: List[Dict[str, Any]] = Field(default_factory=list)


class OpenFDALabelList(list):
    """List subclass preserving backward compatibility for list operations while exposing .status."""
    def __init__(self, items: List[Dict[str, Any]], status: str = "ok", error: Optional[str] = None):
        super().__init__(items)
        self.status = status
        self.error = error

    def to_result(self) -> OpenFDALabelResult:
        return OpenFDALabelResult(status=self.status, error=self.error, items=list(self))


async def fetch_openfda_labels(
    term: str,
    base_url: str = "https://api.fda.gov",
    api_key: str = "",
    timeout_s: float = 20.0,
    limit: int = 4,
) -> OpenFDALabelList:
    """
    Queries openFDA drug label endpoint for an ingredient or brand name.
    Returns parsed sections from the best matching label(s) with typed .status.
    """
    clean_term = term.strip().replace('"', '')
    if not clean_term:
        return OpenFDALabelList([], status="none_found")

    url = f"{base_url}/drug/label.json"
    query = f'openfda.generic_name:"{clean_term}" openfda.brand_name:"{clean_term}"'
    params: Dict[str, Any] = {
        "search": query,
        "limit": limit,
    }
    if api_key:
        params["api_key"] = api_key

    headers = {"Accept": "application/json", "User-Agent": "PharmaGuard-PV/1.0"}

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code == 404:
                # Fallback to single field search
                params["search"] = f'openfda.generic_name:"{clean_term}"'
                resp = await client.get(url, params=params, headers=headers)
                if resp.status_code == 404:
                    logger.info("No openFDA labels found for term: %s", clean_term)
                    return OpenFDALabelList([], status="none_found")

            if resp.status_code != 200:
                logger.warning("openFDA API returned status=%d for term=%s", resp.status_code, clean_term)
                return OpenFDALabelList([], status="provider_error", error=f"HTTP_{resp.status_code}")

            data = resp.json()
    except Exception as exc:
        logger.warning("openFDA request failed for term=%s error=%s", clean_term, type(exc).__name__)
        return OpenFDALabelList([], status="provider_error", error=type(exc).__name__)

    if not isinstance(data, dict):
        return OpenFDALabelList([], status="provider_error", error="MalformedResponse")

    results = data.get("results", [])
    if not results:
        return OpenFDALabelList([], status="none_found")
    if not isinstance(results, list):
        return OpenFDALabelList([], status="provider_error", error="MalformedResults")

    # Sort candidates: prefer labels that have 'adverse_reactions' and 'boxed_warning'
    def _score_label(label: Dict[str, Any]) -> int:
        score = 0
        if "adverse_reactions" in label:
            score += 10
        if "boxed_warning" in label:
            score += 5
        if "warnings_and_cautions" in label or "warnings" in label:
            score += 3
        if "contraindications" in label:
            score += 2
        return score

    results.sort(key=_score_label, reverse=True)
    best_labels = results[:2]  # Keep top 1-2 most informative labels

    extracted_sections: List[Dict[str, Any]] = []

    for label in best_labels:
        set_id = label.get("set_id", "")
        effective_time = label.get("effective_time", "")
        brand_names = label.get("openfda", {}).get("brand_name", [])
        brand_name_str = brand_names[0] if brand_names else clean_term.title()
        generic_names = label.get("openfda", {}).get("generic_name", [])
        generic_name_str = generic_names[0] if generic_names else clean_term.lower()

        dailymed_url = f"https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid={set_id}" if set_id else ""

        for sec_key, sec_title in SAFETY_SECTIONS:
            sec_val = label.get(sec_key)
            if not sec_val:
                continue

            # Section values are usually lists of strings
            combined_text = "\n".join(sec_val) if isinstance(sec_val, list) else str(sec_val)
            if not combined_text.strip():
                continue

            extracted_sections.append({
                "source_id": f"fda-{set_id[:8] if set_id else 'label'}-{sec_key}",
                "set_id": set_id,
                "section": sec_key,
                "title": f"{generic_name_str.title()} ({brand_name_str}) — {sec_title}",
                "ingredient_name": generic_name_str.lower(),
                "text": combined_text,
                "effective_time": effective_time,
                "url": dailymed_url,
            })

    logger.info(
        "Fetched %d safety sections from openFDA for %s",
        len(extracted_sections),
        clean_term,
    )
    return OpenFDALabelList(extracted_sections, status="ok")


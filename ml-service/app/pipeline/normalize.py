"""
Module 4 — RxNorm Drug Normalization Engine.

Connects to the NLM RxNav REST API (free, public, no key required):
1. approximateTerm: matches noisy/brand drug names to candidate RxCUIs.
2. related?tty=IN: resolves brand names / clinical drugs to active ingredients.
3. Provides an in-memory cache and backoff retry logic.
4. Gracefully degrades if external service is unreachable, retaining original text.
"""

from __future__ import annotations

from collections import OrderedDict
import copy
import logging
from typing import Any, Dict, List, Optional
import httpx
from ..config import get_settings
from ..errors import ExternalServiceError
from .terminology import RXNORM_CATALOG

logger = logging.getLogger(__name__)

# Bounded in-memory LRU cache for normalized drug lookups: term -> dict
MAX_NORMALIZATION_CACHE_SIZE = 256
_NORMALIZATION_CACHE: OrderedDict[str, Dict[str, Any]] = OrderedDict()


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    if key in _NORMALIZATION_CACHE:
        _NORMALIZATION_CACHE.move_to_end(key)
        return copy.deepcopy(_NORMALIZATION_CACHE[key])
    return None


def _cache_put(key: str, value: Dict[str, Any]) -> None:
    if key in _NORMALIZATION_CACHE:
        _NORMALIZATION_CACHE.move_to_end(key)
    _NORMALIZATION_CACHE[key] = copy.deepcopy(value)
    while len(_NORMALIZATION_CACHE) > MAX_NORMALIZATION_CACHE_SIZE:
        _NORMALIZATION_CACHE.popitem(last=False)


async def query_rxnav_approximate_term(
    term: str,
    base_url: str = "https://rxnav.nlm.nih.gov/REST",
    timeout_s: float = 15.0,
) -> Optional[Dict[str, Any]]:
    """Queries RxNav approximateTerm API."""
    url = f"{base_url}/approximateTerm.json"
    params = {"term": term, "maxEntries": 4}
    headers = {"Accept": "application/json", "User-Agent": "PharmaGuard-PV/1.0"}

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code != 200:
                logger.warning("RxNav approximateTerm error status=%d for term=%s", resp.status_code, term)
                return None
            data = resp.json()
    except Exception as exc:
        logger.warning("RxNav approximateTerm request failed: %s", type(exc).__name__)
        return None

    candidates = data.get("approximateGroup", {}).get("candidate", [])
    if not candidates:
        return None

    # Sort or pick top candidate
    # Candidates often have 'rank' (1 is best) or highest 'score'
    best = candidates[0]
    return {
        "rxcui": best.get("rxcui"),
        "score": float(best.get("score", 0.0)),
        "rank": int(best.get("rank", 99)),
        "rxnorm_name": best.get("name"),
    }


async def query_rxnav_ingredients(
    rxcui: str,
    base_url: str = "https://rxnav.nlm.nih.gov/REST",
    timeout_s: float = 15.0,
) -> List[Dict[str, str]]:
    """Queries RxNav related API for active ingredient(s) (tty=IN)."""
    url = f"{base_url}/rxcui/{rxcui}/related.json"
    params = {"tty": "IN"}
    headers = {"Accept": "application/json", "User-Agent": "PharmaGuard-PV/1.0"}

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code != 200:
                return []
            data = resp.json()
    except Exception as exc:
        logger.warning("RxNav related ingredient lookup failed: %s", type(exc).__name__)
        return []

    groups = data.get("relatedGroup", {}).get("conceptGroup", [])
    ingredients = []
    for g in groups:
        if g.get("tty") == "IN":
            for prop in g.get("conceptProperties", []):
                ingredients.append({
                    "rxcui": prop.get("rxcui", ""),
                    "name": prop.get("name", "").lower(),
                })
    return ingredients


async def normalize_drug(
    drug_name: str,
    settings=None,
    *,
    allow_network: bool = False,
) -> Dict[str, Any]:
    """
    Normalizes a drug name to its RxCUI and active ingredient(s).
    By default (`allow_network=False`), resolves offline against RXNORM_CATALOG without
    making outbound network requests and never fabricates RxNorm IDs (unmatched drugs
    return matched=False, rxcui=None, ingredients=[]).
    Note: RXNORM_CATALOG CUI values are static catalog entries ([UNVERIFIED] against live
    NLM RxNav in offline environments).
    Always returns a safe dictionary; never raises exceptions to break pipeline flow.
    """
    clean_name = (drug_name or "").strip()
    if not clean_name:
        return {
            "input_term": "",
            "matched": False,
            "rxcui": None,
            "name": "",
            "ingredients": [],
            "score": 0.0,
            "source": "not_found",
            "lookup_status": "not_found",
        }

    cache_key = clean_name.lower()
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    if cache_key in RXNORM_CATALOG:
        cat = RXNORM_CATALOG[cache_key]
        rxcui = cat["rxcui"]
        catalog_res = {
            "input_term": clean_name,
            "matched": True,
            "rxcui": rxcui,
            "name": cat.get("display_name") or clean_name,
            "ingredients": [{"rxcui": rxcui, "name": cache_key}],
            "score": 100.0,
            "source": "offline_catalog",
            "lookup_status": "offline_catalog",
        }
        _cache_put(cache_key, catalog_res)
        return copy.deepcopy(catalog_res)

    if not allow_network:
        return {
            "input_term": clean_name,
            "matched": False,
            "rxcui": None,
            "name": clean_name,
            "ingredients": [],
            "score": 0.0,
            "source": "network_disabled",
            "lookup_status": "network_disabled",
        }

    if settings is None:
        settings = get_settings()

    base_url = settings.rxnav_base_url
    timeout_s = settings.http_timeout_s

    candidate = await query_rxnav_approximate_term(clean_name, base_url=base_url, timeout_s=timeout_s)

    if not candidate or not candidate.get("rxcui"):
        fallback_res = {
            "input_term": clean_name,
            "matched": False,
            "rxcui": None,
            "name": clean_name,
            "ingredients": [],
            "score": 0.0,
            "source": "not_found",
            "lookup_status": "not_found",
        }
        _cache_put(cache_key, fallback_res)
        return fallback_res

    rxcui = candidate["rxcui"]
    ingredients = await query_rxnav_ingredients(rxcui, base_url=base_url, timeout_s=timeout_s)

    # If the candidate was already an ingredient, ensure it's in the ingredients list
    if not ingredients:
        ingredients = [{
            "rxcui": rxcui,
            "name": (candidate.get("rxnorm_name") or clean_name).lower(),
        }]

    result = {
        "input_term": clean_name,
        "matched": True,
        "rxcui": rxcui,
        "name": candidate.get("rxnorm_name") or clean_name,
        "ingredients": ingredients,
        "score": candidate.get("score", 0.0),
        "source": "rxnav",
        "lookup_status": "rxnav",
    }

    _cache_put(cache_key, result)
    logger.info(
        "Normalized drug input=%s rxcui=%s ingredient_count=%d",
        clean_name,
        rxcui,
        len(ingredients),
    )
    return copy.deepcopy(result)



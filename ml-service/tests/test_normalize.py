"""
Unit tests for RxNorm drug normalization with mocked RxNav API calls.
"""

import pytest
from unittest.mock import AsyncMock, patch
from app.pipeline.normalize import (
    MAX_NORMALIZATION_CACHE_SIZE,
    _NORMALIZATION_CACHE,
    normalize_drug,
)


@pytest.mark.asyncio
async def test_normalize_empty_drug():
    res = await normalize_drug("")
    assert res["matched"] is False
    assert res["rxcui"] is None
    assert res["ingredients"] == []
    assert res["source"] == "not_found"
    assert res["lookup_status"] == "not_found"


@pytest.mark.asyncio
async def test_normalize_offline_catalog_lookup():
    res = await normalize_drug("ibuprofen", allow_network=False)
    assert res["matched"] is True
    assert res["rxcui"] == "5640"
    assert res["name"] == "Ibuprofen"
    assert res["source"] == "offline_catalog"
    assert res["lookup_status"] == "offline_catalog"
    assert res["ingredients"] == [{"rxcui": "5640", "name": "ibuprofen"}]


@pytest.mark.asyncio
async def test_normalize_network_disabled_unmatched():
    with patch("app.pipeline.normalize.query_rxnav_approximate_term", new_callable=AsyncMock) as mock_term:
        res = await normalize_drug("unrecognized_offline_compound_abc", allow_network=False)
        assert mock_term.call_count == 0
        assert res["matched"] is False
        assert res["rxcui"] is None
        assert res["ingredients"] == []
        assert res["source"] == "network_disabled"
        assert res["lookup_status"] == "network_disabled"


@pytest.mark.asyncio
async def test_normalize_successful_brand_lookup():
    mock_candidate = {
        "rxcui": "153010",
        "score": 13.1,
        "rank": 1,
        "rxnorm_name": "Advil",
    }
    mock_ingredients = [
        {"rxcui": "5640", "name": "ibuprofen"}
    ]

    with patch("app.pipeline.normalize.query_rxnav_approximate_term", new_callable=AsyncMock) as mock_term:
        with patch("app.pipeline.normalize.query_rxnav_ingredients", new_callable=AsyncMock) as mock_ingr:
            mock_term.return_value = mock_candidate
            mock_ingr.return_value = mock_ingredients

            res = await normalize_drug("advil_test_brand", allow_network=True)
            assert res["matched"] is True
            assert res["rxcui"] == "153010"
            assert res["name"] == "Advil"
            assert res["source"] == "rxnav"
            assert res["lookup_status"] == "rxnav"
            assert len(res["ingredients"]) == 1
            assert res["ingredients"][0]["name"] == "ibuprofen"


@pytest.mark.asyncio
async def test_normalize_unmatched_fallback():
    with patch("app.pipeline.normalize.query_rxnav_approximate_term", new_callable=AsyncMock) as mock_term:
        mock_term.return_value = None

        res = await normalize_drug("unrecognized_experimental_compound_xyz", allow_network=True)
        assert res["matched"] is False
        assert res["rxcui"] is None
        assert res["name"] == "unrecognized_experimental_compound_xyz"
        assert res["ingredients"] == []
        assert res["source"] == "not_found"
        assert res["lookup_status"] == "not_found"


@pytest.mark.asyncio
async def test_normalization_cache_is_bounded():
    _NORMALIZATION_CACHE.clear()
    with patch("app.pipeline.normalize.query_rxnav_approximate_term", new_callable=AsyncMock) as mock_term:
        mock_term.return_value = None
        for idx in range(MAX_NORMALIZATION_CACHE_SIZE + 25):
            await normalize_drug(f"synthetic_drug_{idx}", allow_network=True)
        assert len(_NORMALIZATION_CACHE) == MAX_NORMALIZATION_CACHE_SIZE
        assert "synthetic_drug_0" not in _NORMALIZATION_CACHE
        last_key = f"synthetic_drug_{MAX_NORMALIZATION_CACHE_SIZE + 24}"
        assert last_key in _NORMALIZATION_CACHE

        # Verify _cache_get returns a deep copy so caller mutation cannot corrupt cached entries
        cached_1 = await normalize_drug(last_key, allow_network=True)
        cached_1["name"] = "CORRUPTED_BY_CALLER"
        cached_1["ingredients"].append({"rxcui": "999", "name": "injected"})
        cached_2 = await normalize_drug(last_key, allow_network=True)
        assert cached_2["name"] == last_key
        assert cached_2["ingredients"] == []




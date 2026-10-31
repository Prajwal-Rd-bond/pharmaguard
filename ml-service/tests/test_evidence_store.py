"""
Unit tests for EvidenceStore (in-memory backend without live Qdrant or model download)
and openFDA drug label fetcher.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import numpy as np

from app.evidence.store import EvidenceStore, _IN_MEMORY_FALLBACK_STORE
from app.evidence.openfda import fetch_openfda_labels
import httpx


def test_in_memory_store_indexing_and_search_without_qdrant():
    store = EvidenceStore(
        qdrant_url="http://127.0.0.1:65534",
        collection_name="test_collection",
    )

    sample_chunks = [
        {
            "source_id": "fda-chunk-1",
            "title": "Amoxicillin — Adverse Reactions",
            "section": "adverse_reactions",
            "ingredient_name": "amoxicillin",
            "text": "Serious hypersensitivity reactions have been reported in patients on penicillin therapy.",
            "url": "https://example.com/amox",
            "set_id": "set-1",
        },
        {
            "source_id": "fda-chunk-2",
            "title": "Metformin — Warnings",
            "section": "warnings",
            "ingredient_name": "metformin",
            "text": "Lactic acidosis is a rare but serious metabolic complication.",
            "url": "https://example.com/met",
            "set_id": "set-2",
        },
    ]

    mock_embed = MagicMock()
    mock_embed.embed.side_effect = lambda texts: [np.array([0.1] * 384) for _ in texts]

    with patch("app.evidence.store.get_embed_model", return_value=mock_embed):
        store.upsert_chunks(sample_chunks)
        assert store.is_ingredient_indexed("amoxicillin") is True
        assert store.is_ingredient_indexed("metformin") is True
        assert store.is_ingredient_indexed("nonexistent") is False

        results = store.search(query="rash on penicillin", ingredient_name="amoxicillin", top_k=2)
        assert len(results) >= 1
        assert results[0]["title"] == "Amoxicillin — Adverse Reactions"
        assert "similarity_score" in results[0]


@pytest.mark.asyncio
async def test_openfda_fetch_success_empty_error():
    # 1. Success response
    success_resp = httpx.Response(
        200,
        json={
            "results": [
                {
                    "set_id": "test-set-123",
                    "effective_time": "20240101",
                    "openfda": {"generic_name": ["amoxicillin"], "brand_name": ["Amoxil"]},
                    "adverse_reactions": ["Skin rashes and urticaria have been reported."],
                    "boxed_warning": ["Fatal anaphylaxis warning."],
                }
            ]
        },
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = success_resp
        sections = await fetch_openfda_labels("amoxicillin")
        assert len(sections) >= 1
        assert any(s["section"] == "adverse_reactions" for s in sections)

    # 2. Empty response (404)
    empty_resp = httpx.Response(404, json={"error": {"code": "NOT_FOUND", "message": "No matches found"}})

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = empty_resp
        sections = await fetch_openfda_labels("nonexistent_drug")
        assert sections == []

    # 3. Error response (500)
    error_resp = httpx.Response(500, text="Server Error")

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = error_resp
        sections = await fetch_openfda_labels("error_drug")
        assert sections == []



@pytest.mark.asyncio
async def test_openfda_typed_status_http_500():
    error_resp = httpx.Response(500, text="Internal Server Error")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = error_resp
        res = await fetch_openfda_labels("amoxicillin")
        assert res.status == "provider_error"
        assert res.error == "HTTP_500"
        assert len(res) == 0
        typed = res.to_result()
        assert typed.status == "provider_error"
        assert typed.error == "HTTP_500"
        assert typed.items == []


@pytest.mark.asyncio
async def test_openfda_typed_status_timeout():
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.ConnectTimeout("Connection timed out")
        res = await fetch_openfda_labels("amoxicillin")
        assert res.status == "provider_error"
        assert res.error == "ConnectTimeout"
        assert len(res) == 0
        typed = res.to_result()
        assert typed.status == "provider_error"
        assert typed.error == "ConnectTimeout"
        assert typed.items == []


@pytest.mark.asyncio
async def test_openfda_typed_status_malformed_200():
    # Case A: Invalid JSON string
    bad_json_resp = httpx.Response(200, text="NOT_VALID_JSON{")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = bad_json_resp
        res = await fetch_openfda_labels("amoxicillin")
        assert res.status == "provider_error"
        assert res.error == "JSONDecodeError"
        assert len(res) == 0

    # Case B: JSON where results is not a list
    bad_shape_resp = httpx.Response(200, json={"results": "unexpected_string_not_list"})
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = bad_shape_resp
        res2 = await fetch_openfda_labels("amoxicillin")
        assert res2.status == "provider_error"
        assert res2.error == "MalformedResults"
        assert len(res2) == 0


@pytest.mark.asyncio
async def test_openfda_typed_status_empty_results():
    empty_results_resp = httpx.Response(200, json={"results": []})
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = empty_results_resp
        res = await fetch_openfda_labels("amoxicillin")
        assert res.status == "none_found"
        assert res.error is None
        assert len(res) == 0


def test_socket_guard_blocks_unrecorded_drug_live_network(monkeypatch):
    """
    Verifies that when an unrecorded valid drug name is fetched without conftest replay and
    ENABLE_LIVE_OPENFDA=true, it attempts a real outbound connection to api.fda.gov
    and is intercepted by the session-wide socket guard.
    """
    import app.pipeline.retrieve as ret_mod
    from app.config import get_settings

    monkeypatch.setenv("ENABLE_LIVE_OPENFDA", "true")
    get_settings.cache_clear()
    ret_mod._LIVE_EVIDENCE_CACHE.clear()
    real_fn = getattr(ret_mod, "_ORIGINAL_RETRIEVE_LIVE_EVIDENCE_FOR_DRUG", ret_mod.retrieve_live_evidence_for_drug)
    with pytest.raises(RuntimeError) as exc_info:
        real_fn("investigational-compound-xyz99")

    assert "NETWORK ISOLATION VIOLATION" in str(exc_info.value)
    get_settings.cache_clear()


def test_disabled_live_openfda_causes_no_socket_attempt(monkeypatch):
    """
    Verifies that when ENABLE_LIVE_OPENFDA is disabled (default),
    retrieve_live_evidence_for_drug causes zero socket calls and returns 'live_disabled'.
    """
    import app.pipeline.retrieve as ret_mod
    from app.config import get_settings

    monkeypatch.setenv("ENABLE_LIVE_OPENFDA", "false")
    get_settings.cache_clear()
    ret_mod._LIVE_EVIDENCE_CACHE.clear()
    real_fn = getattr(ret_mod, "_ORIGINAL_RETRIEVE_LIVE_EVIDENCE_FOR_DRUG", ret_mod.retrieve_live_evidence_for_drug)
    res = real_fn("investigational-compound-xyz99")
    assert getattr(res, "evidence_status", None) == "live_disabled"
    assert len(res) == 0
    get_settings.cache_clear()

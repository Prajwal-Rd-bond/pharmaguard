"""
Pytest configuration and network isolation guard for ml-service test suite.
Intercepts socket connection attempts and asserts that tests make zero live network calls.
Allowed local loopback addresses (127.0.0.1, localhost) for in-process TestClient requests.
"""

from __future__ import annotations

import os
import socket
import pytest

_ORIGINAL_CONNECT = socket.socket.connect
_ORIGINAL_CREATE_CONNECTION = socket.create_connection
_ORIGINAL_GETADDRINFO = socket.getaddrinfo

# Pre-load spaCy NER model at session import before Windows DLL load-order conflicts
# with onnxruntime/fastembed can occur during test collection.
try:
    from app.pipeline.deidentify import get_spacy_model
    get_spacy_model("en_core_web_sm")
except Exception:
    pass


@pytest.fixture(autouse=True, scope="session")
def guard_network_sockets():
    """
    Session-wide guard that intercepts real outbound socket connection attempts.
    Permits only in-process localhost/127.0.0.1 loopbacks for TestClient.
    Fails immediately if any external host connection is attempted.
    """
    def _guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) and len(address) > 0 else str(address)
        # Allow local loopback / in-process IPC (e.g. Starlette TestClient / asyncio self-pipe)
        if host in ("127.0.0.1", "localhost", "::1"):
            return _ORIGINAL_CONNECT(self, address)
        # Any non-local connection attempt fails the test run immediately
        raise RuntimeError(
            f"NETWORK ISOLATION VIOLATION: Test suite attempted real external network connection to {address}! "
            "All test components must use offline mock transports or synthetic catalogs."
        )

    def _guarded_getaddrinfo(host, port, *args, **kwargs):
        if str(host) in ("127.0.0.1", "localhost", "::1"):
            return _ORIGINAL_GETADDRINFO(host, port, *args, **kwargs)
        raise RuntimeError(
            f"NETWORK ISOLATION VIOLATION: Test suite attempted real external network connection to {(host, port)}! "
            "All test components must use offline mock transports or synthetic catalogs."
        )

    def _guarded_create_connection(address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) and len(address) > 0 else str(address)
        if host in ("127.0.0.1", "localhost", "::1"):
            return _ORIGINAL_CREATE_CONNECTION(address, *args, **kwargs)
        raise RuntimeError(
            f"NETWORK ISOLATION VIOLATION: Test suite attempted real external network connection to {address}! "
            "All test components must use offline mock transports or synthetic catalogs."
        )

    socket.socket.connect = _guarded_connect
    socket.create_connection = _guarded_create_connection
    socket.getaddrinfo = _guarded_getaddrinfo
    yield
    socket.socket.connect = _ORIGINAL_CONNECT
    socket.create_connection = _ORIGINAL_CREATE_CONNECTION
    socket.getaddrinfo = _ORIGINAL_GETADDRINFO


@pytest.fixture(autouse=True)
def scope_builtin_reference_corpus_for_legacy_unit_tests(request, monkeypatch):
    """
    By default, ALLOW_BUILTIN_REFERENCE_CORPUS is false so disabled live retrieval
    returns retrievals: [] with no fabricated demo reference material.
    For the two untouched origin/main unit tests that specifically test the static
    BM25/RRF ranker over KNOWLEDGE_CORPUS, enable ALLOW_BUILTIN_REFERENCE_CORPUS=true.
    """
    from app.config import get_settings
    if request.node.name in ("test_retrieve_finds_relevant_evidence", "test_hybrid_bm25_and_rrf_retrieval"):
        monkeypatch.setenv("NODE_ENV", "test")
        monkeypatch.setenv("ALLOW_BUILTIN_REFERENCE_CORPUS", "true")
    else:
        monkeypatch.delenv("NODE_ENV", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def replay_recorded_live_openfda(monkeypatch):
    """
    The legacy retrieve_live_evidence_for_drug() performs a REAL https://api.fda.gov call.
    The frozen origin-main capture was recorded with that call live (its 3rd retrieval,
    source_id 'fda-amoxicillin'). Replay exactly that recorded item offline; return [] for
    every other drug. Production code is untouched.
    """
    import json
    from pathlib import Path

    import app.pipeline.retrieve as retrieve_mod

    frozen = json.loads(
        (Path(__file__).parent / "fixtures" / "frozen_origin_main_full.json").read_text(encoding="utf-8")
    )
    recorded = [r for r in frozen["retrievals"] if r["source_collection"] == "openfda_labels"]

    def _replay(drug_name, *args, **kwargs):
        if (drug_name or "").strip().lower() == "amoxicillin":
            return [dict(r) for r in recorded]
        return []

    monkeypatch.setattr(retrieve_mod, "retrieve_live_evidence_for_drug", _replay)

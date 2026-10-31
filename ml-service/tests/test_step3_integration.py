"""
Step 3 Integration Completeness tests:
- 3.2: FastAPI route mounting and response verification for all collaborator endpoints
- 3.4: Benchmark suite docstring & regression benchmark framing verification
- 3.5: Built-in reference corpus tagging (corpus_origin) and ALLOW_BUILTIN_REFERENCE_CORPUS guard
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from app.main import app
from app.config import load_settings
from app.pipeline.retrieve import retrieve


def test_collaborator_fastapi_endpoints_mount_and_respond(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "disabled")
    monkeypatch.setenv("ENABLE_LIVE_OPENFDA", "false")
    client = TestClient(app)

    route_paths = {getattr(r, "path", None) for r in app.routes}
    expected_paths = {
        "/health",
        "/pipeline/run",
        "/pipeline/deidentify",
        "/pipeline/extract",
        "/pipeline/classify",
        "/pipeline/causality",
        "/analytics/signals/overview",
        "/analytics/signals/detect",
        "/analytics/graph/explore",
        "/analytics/graph/full",
    }
    assert expected_paths.issubset(route_paths)

    assert client.get("/health").status_code == 200
    assert client.get("/analytics/signals/overview").status_code == 200
    assert client.get("/analytics/signals/detect?drug=amoxicillin&reaction=rash").status_code == 200
    assert client.get("/analytics/graph/explore?drug=amoxicillin").status_code == 200
    assert client.get("/analytics/graph/full").status_code == 200

    sample_req = {
        "pipeline_run_id": "test-collab-001",
        "raw_text": "Patient took amoxicillin 500 mg and developed rash 2 days later.",
    }
    assert client.post("/pipeline/deidentify", json=sample_req).status_code == 200
    assert client.post("/pipeline/extract", json=sample_req).status_code == 200
    assert client.post("/pipeline/classify", json=sample_req).status_code == 200
    assert client.post("/pipeline/causality", json=sample_req).status_code == 200


def test_builtin_reference_corpus_tagging_and_opt_out_guard(monkeypatch):
    import app.pipeline.retrieve as retrieve_mod

    monkeypatch.setattr(retrieve_mod, "get_qdrant_client", lambda: None)

    # 1. Default (ALLOW_BUILTIN_REFERENCE_CORPUS=true): static reference corpus items are returned and tagged
    settings_default = load_settings(
        {"LLM_PROVIDER": "disabled", "ENABLE_LIVE_OPENFDA": "false", "ALLOW_BUILTIN_REFERENCE_CORPUS": "true"}
    )
    res_default = retrieve({"drugName": "amoxicillin", "symptoms": ["rash"]}, settings=settings_default)
    assert len(res_default) > 0
    assert all(getattr(item, "corpus_origin", None) == "builtin_demo_corpus" for item in res_default)

    # 2. Strict production mode (ALLOW_BUILTIN_REFERENCE_CORPUS=false): static demo corpus is excluded
    settings_strict = load_settings(
        {"LLM_PROVIDER": "disabled", "ENABLE_LIVE_OPENFDA": "false", "ALLOW_BUILTIN_REFERENCE_CORPUS": "false"}
    )
    res_strict = retrieve({"drugName": "amoxicillin", "symptoms": ["rash"]}, settings=settings_strict)
    assert len(res_strict) == 0
    assert res_strict.evidence_status == "live_disabled"


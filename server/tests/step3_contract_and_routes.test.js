import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import mongoose from "mongoose";
import app from "../src/app.js";
import Report from "../src/models/Report.js";
import Extraction from "../src/models/Extraction.js";
import Classification from "../src/models/Classification.js";
import { normalizePipelineResultForServer } from "../src/queue/pipelineQueue.js";

function extractExpressRoutes(expressApp) {
  const routes = [];
  function walk(stack, prefix = "") {
    for (const layer of stack || []) {
      if (layer.route && layer.route.path) {
        const methods = Object.keys(layer.route.methods)
          .filter((m) => layer.route.methods[m])
          .map((m) => m.toUpperCase())
          .sort();
        const routePath = layer.route.path === "/" && prefix ? prefix : `${prefix}${layer.route.path}`;
        routes.push(`${methods.join(",")} ${routePath}`);
      } else if (layer.name === "router" && layer.handle?.stack) {
        let subPrefix = prefix;
        const src = layer.regexp?.source || "";
        const m = src.match(/^\^\\\/(.+?)\\\/\?\(\?=\\\/\|\$\)/);
        if (m) {
          subPrefix = prefix + "/" + m[1].replace(/\\\//g, "/");
        }
        walk(layer.handle.stack, subPrefix);
      }
    }
  }
  walk(expressApp._router?.stack || []);
  return routes;
}

test("Step 3.1: Real /pipeline/run output -> Express queue transformation -> ReportDetail.jsx & Mongoose contract", () => {
  const pyScript = `
import json, os
os.environ["LLM_PROVIDER"] = "disabled"
os.environ["ENABLE_LIVE_OPENFDA"] = "false"
os.environ["NODE_ENV"] = "test"
from app.pipeline.deidentify import get_spacy_model
get_spacy_model("en_core_web_sm")
from fastapi.testclient import TestClient
from app.main import app
client = TestClient(app)
resp = client.post("/pipeline/run", json={
    "pipeline_run_id": "contract-run-001",
    "raw_text": "Patient Jane Doe, MRN 99120, developed severe anaphylaxis and hospitalization 2 hours after starting amoxicillin 500 mg orally twice daily.",
    "unexpected": True,
    "reasonably_related": True
})
assert resp.status_code == 200, resp.text
print("__JSON_START__" + json.dumps(resp.json()) + "__JSON_END__")
`;

  const proc = spawnSync(
    "D:\\pharmaguard\\ml-service\\.venv\\Scripts\\python.exe",
    ["-c", pyScript],
    {
      cwd: new URL("../../ml-service", import.meta.url),
      encoding: "utf-8",
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PYTHONPATH: "" },
    }
  );
  assert.equal(proc.status, 0, `Python /pipeline/run failed: ${proc.stderr}`);
  const match = proc.stdout.match(/__JSON_START__(.+?)__JSON_END__/s);
  assert.ok(match, `Missing JSON marker in stdout: ${proc.stdout}`);
  const mlResult = JSON.parse(match[1]);

  // 2. Pass real ML output through normalizePipelineResultForServer (used by executePipelineTask)
  const receiptDate = new Date("2026-10-01T00:00:00.000Z");
  const normalized = normalizePipelineResultForServer(mlResult, receiptDate);

  // 3. Instantiate actual Mongoose documents (Report, Extraction, Classification) to prove Mongoose schema does not strip fields
  const reportDoc = new Report({
    submittedBy: new mongoose.Types.ObjectId(),
    source: "pasted_text",
    rawText: "Encrypted raw text placeholder",
    deidentifiedText: mlResult.deidentified_text,
    deidentificationLog: mlResult.deidentification_log,
    summary: mlResult.summary,
    ichE2ACriteria: normalized.ichE2ACriteria,
    isSerious: normalized.isSerious,
    regulatoryClockDays: normalized.regulatoryClockDays,
    regulatory_clock_days: normalized.regulatory_clock_days,
    expeditedClockLabel: normalized.expeditedClockLabel,
    expedited_clock_label: normalized.expedited_clock_label,
    regulatoryDueDate: normalized.regulatoryDueDate,
    causality: normalized.causality,
    terminology: normalized.terminology,
    citationVerification: normalized.citationVerification,
    citation_verification: normalized.citation_verification,
    evidenceStatus: normalized.evidenceStatus,
    evidence_status: normalized.evidence_status,
    assessmentStatus: normalized.assessmentStatus,
    assessment_status: normalized.assessment_status,
    assessment: normalized.assessment,
    normalizedDrug: normalized.normalizedDrug,
    normalized_drug: normalized.normalized_drug,
    status: "pending_review",
  });

  const extractionDoc = new Extraction({
    report: reportDoc._id,
    pipelineRunId: "contract-run-001",
    ...normalized.extraction,
  });

  const classificationDoc = new Classification({
    report: reportDoc._id,
    pipelineRunId: "contract-run-001",
    ...normalized.classification,
  });

  const reportJson = reportDoc.toObject();
  const extractionJson = extractionDoc.toObject();
  const classificationJson = classificationDoc.toObject();

  // 4. Assert every field requested in Step 3.1 + read by ReportDetail.jsx and pipelineQueue.js is present & non-undefined
  assert.equal(typeof reportJson.causality.naranjoScore, "number");
  assert.equal(reportJson.causality.naranjoScore, mlResult.causality.naranjo_score);
  assert.equal(typeof reportJson.causality.naranjoCategory, "string");
  assert.equal(reportJson.causality.naranjoCategory, mlResult.causality.naranjo_category);
  assert.equal(typeof reportJson.causality.whoUmcCategory, "string");
  assert.equal(reportJson.causality.whoUmcCategory, mlResult.causality.who_umc_category);
  assert.equal(typeof reportJson.causality.rationale, "string");
  assert.equal(reportJson.causality.naranjo_score, mlResult.causality.naranjo_score);
  assert.equal(reportJson.causality.who_umc_category, mlResult.causality.who_umc_category);

  // Classification & Regulatory Clock fields
  assert.ok(Array.isArray(classificationJson.ich_e2a_criteria));
  assert.ok(classificationJson.ich_e2a_criteria.includes("life_threatening"));
  assert.deepEqual(reportJson.ichE2ACriteria, mlResult.classification.ich_e2a_criteria);
  assert.equal(classificationJson.regulatory_clock_days, mlResult.classification.regulatory_clock_days);
  assert.equal(reportJson.regulatoryClockDays, mlResult.classification.regulatory_clock_days);
  assert.equal(reportJson.regulatory_clock_days, mlResult.classification.regulatory_clock_days);
  assert.equal(mlResult.classification.regulatory_clock_days, 7);
  assert.equal(mlResult.classification.expedited_clock_label, "expedited_7_day");
  assert.equal(classificationJson.expeditedClockLabel, "expedited_7_day");
  assert.equal(classificationJson.expedited_clock_label, "expedited_7_day");
  assert.equal(reportJson.expeditedClockLabel, "expedited_7_day");
  assert.equal(reportJson.expedited_clock_label, "expedited_7_day");
  assert.equal(mlResult.classification.periodic_clock_days, null);
  assert.ok(Array.isArray(mlResult.retrievals) && mlResult.retrievals.length > 0);
  assert.equal(mlResult.retrievals[0].corpus_origin, "builtin_demo_corpus");

  // Citation verification & evidence_status
  assert.ok(reportJson.citationVerification && typeof reportJson.citationVerification === "object");
  assert.ok(reportJson.citation_verification && typeof reportJson.citation_verification === "object");
  assert.equal(
    reportJson.citationVerification.overall_grounding_score,
    mlResult.citation_verification.overall_grounding_score
  );
  assert.equal(reportJson.evidenceStatus, mlResult.evidence_status);
  assert.equal(reportJson.evidence_status, mlResult.evidence_status);

  // Terminology (camelCase for ReportDetail.jsx + E2B/FHIR exporters + snake_case)
  assert.ok(reportJson.terminology.drugRxNorm && typeof reportJson.terminology.drugRxNorm === "object");
  assert.equal(reportJson.terminology.drugRxNorm.rxcui, mlResult.extraction.terminology.drug_rxnorm.rxcui);
  assert.ok(Array.isArray(reportJson.terminology.meddraAdverseEvents));
  assert.ok(reportJson.terminology.meddraAdverseEvents.length > 0);
  assert.equal(
    reportJson.terminology.meddraAdverseEvents[0].pt,
    mlResult.extraction.terminology.meddra_adverse_events[0].pt
  );
  assert.ok(extractionJson.terminology.drugRxNorm);
});

test("Step 3.2: All collaborator endpoints mount on Express app", () => {
  const routes = extractExpressRoutes(app);
  const expectedRoutes = [
    "GET /.well-known/smart-configuration",
    "GET /api/health",
    "GET /api/metrics",
    "POST /api/auth/login",
    "POST /api/auth/mfa/verify-login",
    "POST /api/auth/mfa/setup",
    "POST /api/auth/mfa/verify",
    "GET /api/reports/sla/stream",
    "GET /api/reports/sla/summary",
    "GET /api/reports/eval/feedback-dataset",
    "GET /api/reports/eval/training-export",
    "GET /api/reports/:id/export/e2b",
    "GET /api/reports/:id/export/fhir",
    "POST /api/reports/:id/transmit-gateway",
    "GET /api/reports/:id/duplicate-check",
    "POST /api/reports/:id/causality",
    "GET /api/signals/dashboard",
    "GET /api/signals/detect",
    "GET /api/signals/knowledge-graph",
    "GET /api/fhir/metadata",
    "POST /api/fhir/AdverseEvent",
    "POST /api/fhir/Bundle",
  ];
  for (const exp of expectedRoutes) {
    assert.ok(routes.includes(exp), `Expected Express route '${exp}' not found in: ${routes.join("; ")}`);
  }
});

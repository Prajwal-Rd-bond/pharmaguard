import test from "node:test";
import assert from "node:assert/strict";

import { parseFhirAdverseEvent, exportReportToFhir, getFhirCapabilityStatement } from "../src/utils/fhirAdapter.js";
import {
  computeAs2Mic,
  packageAs2Envelope,
  validateE2BXmlPrerequisites,
  transmitToRegulatoryGateway,
} from "../src/utils/regulatoryGateway.js";
import { exportToBioNerFormat, exportToInstructionJsonl } from "../src/utils/datasetExporter.js";
import { calculateReportSla, aggregateQueueSlaMetrics } from "../src/utils/slaAlertEngine.js";

test("HL7 FHIR R4 Interoperability Adapter", async (t) => {
  await t.test("parses standalone FHIR R4 AdverseEvent resource correctly", () => {
    const fhirAe = {
      resourceType: "AdverseEvent",
      id: "ae-test-101",
      actuality: "actual",
      subject: { reference: "Patient/PAT-882", display: "John Doe" },
      date: "2026-10-10T14:30:00Z",
      event: {
        coding: [{ system: "http://hl7.org/fhir/sid/meddra", code: "10002272", display: "Anaphylactic shock" }],
        text: "Severe anaphylactic shock",
      },
      seriousness: {
        coding: [{ code: "life-threatening", display: "Life-Threatening" }],
      },
      suspectEntity: [
        {
          instance: {
            concept: { text: "Amoxicillin 500mg" },
            display: "Amoxicillin",
          },
        },
      ],
    };

    const parsed = parseFhirAdverseEvent(fhirAe);
    assert.equal(parsed.source, "fhir_r4");
    assert.equal(parsed.suspectDrug, "Amoxicillin");
    assert.equal(parsed.isSerious, true);
    assert.ok(parsed.seriousnessCriteria.includes("life_threatening"));
    assert.ok(parsed.symptoms.includes("Severe anaphylactic shock") || parsed.symptoms.includes("Anaphylactic shock"));
    assert.ok(parsed.rawText.includes("PAT-882"));
    assert.ok(parsed.rawText.includes("Amoxicillin"));
  });

  await t.test("parses FHIR R4 Bundle containing AdverseEvent and Patient", () => {
    const bundle = {
      resourceType: "Bundle",
      entry: [
        {
          resource: {
            resourceType: "Patient",
            id: "PAT-991",
            gender: "female",
          },
        },
        {
          resource: {
            resourceType: "AdverseEvent",
            id: "ae-bundle-01",
            subject: { reference: "Patient/PAT-991" },
            event: { text: "Stevens-Johnson syndrome" },
            seriousness: {
              coding: [{ code: "hospitalization", display: "Requires hospitalization" }],
            },
            suspectEntity: [
              {
                instance: { display: "Lamotrigine" },
              },
            ],
          },
        },
      ],
    };

    const parsed = parseFhirAdverseEvent(bundle);
    assert.equal(parsed.suspectDrug, "Lamotrigine");
    assert.equal(parsed.patientGender, "female");
    assert.equal(parsed.isSerious, true);
    assert.ok(parsed.seriousnessCriteria.includes("hospitalization"));
    assert.ok(parsed.symptoms.includes("Stevens-Johnson syndrome"));
  });

  await t.test("exports PharmaGuard Report to compliant FHIR R4 AdverseEvent", () => {
    const mockReport = {
      _id: "670aa1122334455667788990",
      createdAt: new Date("2026-10-11T10:00:00Z"),
      isSerious: true,
      ichE2ACriteria: ["hospitalization"],
      summary: "Patient suffered severe hepatotoxicity after starting Atorvastatin.",
      causality: {
        naranjoScore: 7,
        naranjoCategory: "Probable",
      },
      terminology: {
        drugRxNorm: { rxcui: "83367" },
        meddraAdverseEvents: [{ pt: "Hepatotoxicity", soc: "Hepatobiliary disorders" }],
      },
      submittedBy: { name: "Dr. Sarah Adams" },
    };

    const mockExt = {
      drugName: "Atorvastatin",
      symptoms: ["Hepatotoxicity", "Jaundice"],
    };

    const mockClass = {
      severity: "serious",
    };

    const fhirRes = exportReportToFhir(mockReport, mockExt, mockClass);
    assert.equal(fhirRes.resourceType, "AdverseEvent");
    assert.equal(fhirRes.id, "pharmaguard-670aa1122334455667788990");
    assert.equal(fhirRes.actuality, "actual");
    assert.equal(fhirRes.suspectEntity[0].instance.display, "Atorvastatin");
    assert.equal(fhirRes.event.coding[0].display, "Hepatotoxicity");
    assert.equal(fhirRes.suspectEntity[0].causality[0].assessment.coding[0].code, "Probable");
  });

  await t.test("generates valid FHIR CapabilityStatement", () => {
    const caps = getFhirCapabilityStatement();
    assert.equal(caps.resourceType, "CapabilityStatement");
    assert.equal(caps.fhirVersion, "4.0.1");
    assert.equal(caps.rest[0].resource[0].type, "AdverseEvent");
  });
});

test("Direct Regulatory Gateway (FDA ESG & AS2 Protocol Engine)", async (t) => {
  await t.test("computes RFC 4130 SHA-256 MIC digest correctly", () => {
    const sampleXml = "<ichicsr><safetyreportid>TEST-001</safetyreportid></ichicsr>";
    const mic = computeAs2Mic(sampleXml);
    assert.ok(mic.endsWith(", sha256"));
    assert.ok(mic.length > 20);
  });

  await t.test("packages AS2 transport envelope with required headers", () => {
    const sampleXml = "<ichicsr><safetyreportid>TEST-001</safetyreportid></ichicsr>";
    const envelope = packageAs2Envelope(sampleXml, "RPT-12345", { gateway: "FDA_ESG" });

    assert.equal(envelope.gateway, "FDA_ESG");
    assert.equal(envelope.headers["AS2-Version"], "1.2");
    assert.equal(envelope.headers["AS2-From"], "PHARMAGUARD_SAFETY_SYSTEM");
    assert.ok(envelope.headers["Message-ID"].includes("@pharmaguard.ai"));
    assert.ok(envelope.rawEnvelope.includes("AS2-Version: 1.2"));
    assert.ok(envelope.rawEnvelope.includes("<safetyreportid>TEST-001</safetyreportid>"));
  });

  await t.test("validates E2B(R3) prerequisites and rejects missing tags", () => {
    const invalidXml = "<ichicsr><broken>incomplete</broken></ichicsr>";
    const validation = validateE2BXmlPrerequisites(invalidXml);
    assert.equal(validation.valid, false);
    assert.ok(validation.errors.length > 0);
  });

  await t.test("successfully transmits valid E2B XML and returns positive MDN receipt", () => {
    const validXml = `<?xml version="1.0" encoding="UTF-8"?>
<ichicsr>
  <ichicsrmessageheader></ichicsrmessageheader>
  <safetyreport>
    <safetyreportid>PHARMAGUARD-001</safetyreportid>
    <seriousness>1</seriousness>
    <medicinalproduct>Ciprofloxacin</medicinalproduct>
    <reactionmeddrapt>Tendon rupture</reactionmeddrapt>
  </safetyreport>
</ichicsr>`;

    const result = transmitToRegulatoryGateway(validXml, "PHARMAGUARD-001", { gateway: "FDA_ESG" });
    assert.equal(result.success, true);
    assert.equal(result.gateway, "FDA_ESG");
    assert.ok(result.transmissionId.startsWith("TXN-FDA_ESG-"));
    assert.equal(result.mdn.status, "acknowledged");
    assert.ok(result.mdn.disposition.includes("processed"));
    assert.ok(result.mdn.fdaCoreId.includes("CORE-"));
  });
});

test("Active Learning & Fine-Tuning Dataset Exporter", async (t) => {
  await t.test("exports feedback examples to CoNLL BIO NER format", () => {
    const examples = [
      {
        rawText: "Patient took Warfarin and developed hematuria within 48 hours.",
        goldExtraction: {
          suspectDrug: "Warfarin",
          symptoms: ["hematuria"],
        },
      },
    ];

    const bio = exportToBioNerFormat(examples);
    assert.ok(bio.includes("Warfarin\tB-DRUG"));
    assert.ok(bio.includes("hematuria\tB-ADR"));
    assert.ok(bio.includes("Patient\tO"));
  });

  await t.test("exports feedback examples to ShareGPT / Alpaca JSONL format", () => {
    const examples = [
      {
        _id: "670aa2233445566778899001",
        rawText: "Severe rash after starting Allopurinol.",
        aiProposedExtraction: { suspectDrug: "Allopurinol", symptoms: ["rash"] },
        goldExtraction: { suspectDrug: "Allopurinol", symptoms: ["Severe rash"], severity: "serious" },
        clinicianDiff: { severity: { original: "moderate", corrected: "serious" } },
      },
    ];

    const jsonl = exportToInstructionJsonl(examples);
    const parsed = JSON.parse(jsonl.trim());
    assert.equal(parsed.messages.length, 3);
    assert.equal(parsed.messages[0].role, "system");
    assert.ok(parsed.messages[1].content.includes("Allopurinol"));
    assert.ok(parsed.messages[2].content.includes("Allopurinol"));
    assert.equal(parsed.metadata.humanVerified, true);
  });
});

test("Regulatory SLA Urgency Tracking & Imminent Breach Detection", async (t) => {
  await t.test("flags 7-day clock and calculates urgent status correctly", () => {
    const fiveDaysAgo = new Date(Date.now() - 5 * 86400000);
    const report = {
      status: "pending_review",
      createdAt: fiveDaysAgo,
      isSerious: true,
      ichE2ACriteria: ["life_threatening"],
      regulatoryDueDate: new Date(fiveDaysAgo.getTime() + 7 * 86400000), // 2 days left
    };

    const sla = calculateReportSla(report);
    assert.equal(sla.clockDays, 7);
    assert.equal(sla.isExpedited7Day, true);
    assert.equal(sla.isOverdue, false);
    assert.ok(sla.hoursRemaining > 0 && sla.hoursRemaining <= 49);
  });

  await t.test("aggregates queue metrics and identifies breached and imminent reports", () => {
    const now = Date.now();
    const reports = [
      {
        status: "pending_review",
        isSerious: true,
        ichE2ACriteria: ["death"],
        regulatoryDueDate: new Date(now - 100000), // already overdue
      },
      {
        status: "pending_review",
        isSerious: true,
        ichE2ACriteria: ["life_threatening"],
        regulatoryDueDate: new Date(now + 18 * 3600000), // 18 hours left (< 24h)
      },
      {
        status: "approved", // already resolved
        isSerious: true,
        ichE2ACriteria: ["death"],
        regulatoryDueDate: new Date(now - 100000),
      },
    ];

    const metrics = aggregateQueueSlaMetrics(reports);
    assert.equal(metrics.totalActive, 2);
    assert.equal(metrics.breachedCount, 1);
    assert.equal(metrics.criticalImminentCount, 1);
    assert.equal(metrics.expeditedCount, 2);
  });
});

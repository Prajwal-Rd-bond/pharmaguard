import Report from "../models/Report.js";
import Extraction from "../models/Extraction.js";
import Classification from "../models/Classification.js";
import { parseFhirAdverseEvent, exportReportToFhir, getFhirCapabilityStatement } from "../utils/fhirAdapter.js";
import { recordAuditLog } from "../middleware/auditLogger.js";
import { enqueueReportPipeline } from "../queue/pipelineQueue.js";

/**
 * Returns HL7 FHIR R4 CapabilityStatement.
 */
export async function getCapabilityStatement(req, res) {
  const statement = getFhirCapabilityStatement();
  res.setHeader("Content-Type", "application/fhir+json");
  return res.json(statement);
}

/**
 * Ingests an HL7 FHIR R4 AdverseEvent or Bundle from an EHR system.
 */
export async function ingestFhirAdverseEvent(req, res) {
  const fhirPayload = req.body;
  if (!fhirPayload) {
    return res.status(400).json({
      resourceType: "OperationOutcome",
      issue: [{ severity: "error", code: "structure", diagnostics: "Missing request body" }],
    });
  }

  try {
    const parsed = parseFhirAdverseEvent(fhirPayload);

    // Calculate initial regulatory clock based on extracted seriousness
    const is7DayClock = parsed.seriousnessCriteria.includes("death") || parsed.seriousnessCriteria.includes("life_threatening");
    const clockDays = is7DayClock ? 7 : parsed.isSerious ? 15 : 30;
    const dueDate = new Date(Date.now() + clockDays * 86400000);

    const report = await Report.create({
      submittedBy: req.user._id,
      source: "fhir_r4",
      originalFilename: `fhir-${parsed.fhirResourceId}.json`,
      rawText: parsed.rawText,
      isSerious: parsed.isSerious,
      ichE2ACriteria: parsed.seriousnessCriteria,
      regulatoryClockDays: clockDays,
      regulatoryDueDate: dueDate,
      fhirMetadata: {
        resourceId: parsed.fhirResourceId,
        subjectIdentifier: parsed.subjectIdentifier,
        recordedDate: parsed.recordedDate,
      },
      status: "submitted",
    });

    await recordAuditLog({
      reportId: report._id,
      action: "REPORT_INGEST_FHIR",
      performedBy: req.user._id,
      details: {
        fhirResourceId: parsed.fhirResourceId,
        subjectIdentifier: parsed.subjectIdentifier,
        isSerious: parsed.isSerious,
        seriousnessCriteria: parsed.seriousnessCriteria,
      },
    });

    // Optionally enqueue async background processing pipeline
    try {
      await enqueueReportPipeline({ reportId: report._id, rawText: parsed.rawText });
    } catch {
      // In standalone/testing environments without Redis, continue
    }

    res.status(201);
    res.setHeader("Content-Type", "application/fhir+json");
    return res.json({
      resourceType: "OperationOutcome",
      issue: [
        {
          severity: "information",
          code: "informational",
          diagnostics: `AdverseEvent successfully ingested into PharmaGuard. Report ID: ${report._id}`,
        },
      ],
      reportId: report._id,
    });
  } catch (err) {
    return res.status(422).json({
      resourceType: "OperationOutcome",
      issue: [{ severity: "error", code: "processing", diagnostics: err.message }],
    });
  }
}

/**
 * Returns a report exported as HL7 FHIR R4 AdverseEvent.
 */
export async function getFhirAdverseEventById(req, res) {
  const report = await Report.findById(req.params.id).populate("submittedBy", "name email role");
  if (!report) {
    return res.status(404).json({
      resourceType: "OperationOutcome",
      issue: [{ severity: "error", code: "not-found", diagnostics: "Report not found" }],
    });
  }

  const [extraction, classification] = await Promise.all([
    Extraction.findOne({ report: report._id }).sort({ createdAt: -1 }),
    Classification.findOne({ report: report._id }).sort({ createdAt: -1 }),
  ]);

  const fhirResource = exportReportToFhir(report, extraction, classification);
  res.setHeader("Content-Type", "application/fhir+json");
  return res.json(fhirResource);
}


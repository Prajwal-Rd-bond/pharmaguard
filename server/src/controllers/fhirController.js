import Report from "../models/Report.js";
import Extraction from "../models/Extraction.js";
import Classification from "../models/Classification.js";
import { parseFhirAdverseEvent, exportReportToFhir, getFhirCapabilityStatement } from "../utils/fhirAdapter.js";
import {
  getSmartConfiguration,
  registerLaunchSession,
  createAuthorizationCode,
  exchangeSmartToken,
  simulateSmartEhrLaunch,
} from "../utils/smartAuthEngine.js";
import { realtimeEventManager } from "../utils/realtimeEvents.js";
import { recordAuditLog } from "../middleware/auditLogger.js";
import { enqueueReportPipeline } from "../queue/pipelineQueue.js";
import jwt from "jsonwebtoken";

/**
 * Returns HL7 FHIR R4 CapabilityStatement with SMART OAuth2 security extensions.
 */
export async function getCapabilityStatement(req, res) {
  const statement = getFhirCapabilityStatement();
  res.setHeader("Content-Type", "application/fhir+json");
  return res.json(statement);
}

/**
 * Returns SMART on FHIR .well-known/smart-configuration metadata.
 */
export async function getSmartConfig(req, res) {
  const baseUrl = `${req.protocol}://${req.get("host")}/api/fhir`;
  const config = getSmartConfiguration(baseUrl);
  res.setHeader("Content-Type", "application/json");
  return res.json(config);
}

/**
 * Initiates an EHR Launch sequence (e.g., from Epic Hyperspace or Cerner PowerChart).
 */
export async function initiateSmartLaunch(req, res) {
  const { launch, iss } = req.query;
  if (!launch) {
    return res.status(400).json({
      error: "invalid_request",
      error_description: "Missing launch identifier in EHR launch sequence",
    });
  }

  // Register the EHR launch context
  const session = registerLaunchSession({
    launchId: launch,
    iss: iss || "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4",
  });

  // If redirect requested or client params provided
  if (req.query.redirect_uri) {
    const authUrl = `/api/fhir/auth/authorize?launch=${encodeURIComponent(launch)}&iss=${encodeURIComponent(iss || "")}&client_id=${encodeURIComponent(req.query.client_id || "pharmaguard-ehr-client")}&redirect_uri=${encodeURIComponent(req.query.redirect_uri)}&response_type=code`;
    return res.redirect(302, authUrl);
  }

  return res.json({
    status: "launch_initiated",
    session,
    nextStep: `/api/fhir/auth/authorize?launch=${launch}&response_type=code`,
  });
}

/**
 * SMART OAuth2 Authorize endpoint.
 * Issues authorization code bound to launch context (patient, encounter).
 */
export async function authorizeSmartLaunch(req, res) {
  const params = req.method === "POST" ? req.body : req.query;
  const { client_id, redirect_uri, scope, state, launch, patient, encounter } = params;

  if (params.response_type !== "code") {
    return res.status(400).json({
      error: "unsupported_response_type",
      error_description: "response_type must be 'code'",
    });
  }

  try {
    const code = createAuthorizationCode({
      clientId: client_id || "pharmaguard-smart-client",
      redirectUri: redirect_uri,
      scope: scope || "launch/patient patient/AdverseEvent.write",
      launchId: launch,
      patientId: patient,
      encounterId: encounter,
      userId: req.user?._id?.toString() || "DR-EHR-CLINICIAN",
    });

    if (redirect_uri) {
      const redirectTarget = new URL(redirect_uri, `${req.protocol}://${req.get("host")}`);
      redirectTarget.searchParams.set("code", code);
      if (state) redirectTarget.searchParams.set("state", state);
      return res.redirect(302, redirectTarget.toString());
    }

    return res.json({
      code,
      state: state || null,
      expires_in: 600,
    });
  } catch (err) {
    return res.status(500).json({ error: "server_error", error_description: err.message });
  }
}

/**
 * SMART OAuth2 Token endpoint.
 * Exchanges authorization code for access token and launch context.
 */
export async function tokenExchangeSmartLaunch(req, res) {
  // Support both body and HTTP Basic auth for client credentials
  let clientId = req.body.client_id;
  const authHeader = req.headers.authorization;
  if (!clientId && authHeader && authHeader.startsWith("Basic ")) {
    try {
      const decoded = Buffer.from(authHeader.slice(6), "base64").toString("utf8");
      const parts = decoded.split(":");
      clientId = parts[0];
    } catch {
      // ignore
    }
  }

  const { grant_type, code, redirect_uri } = req.body;
  if (grant_type !== "authorization_code") {
    return res.status(400).json({
      error: "unsupported_grant_type",
      error_description: "grant_type must be 'authorization_code'",
    });
  }

  try {
    const tokenResponse = exchangeSmartToken({
      code,
      clientId,
      redirectUri: redirect_uri,
    });

    res.setHeader("Cache-Control", "no-store");
    res.setHeader("Pragma", "no-cache");
    return res.json(tokenResponse);
  } catch (err) {
    return res.status(400).json({
      error: "invalid_grant",
      error_description: err.message,
    });
  }
}

/**
 * SMART OAuth2 Token Introspection endpoint (RFC 7662).
 */
export async function introspectSmartToken(req, res) {
  const token = req.body.token || (req.headers.authorization || "").replace("Bearer ", "");
  if (!token) {
    return res.json({ active: false });
  }

  try {
    const jwtSecret = process.env.JWT_SECRET || "smart-fhir-dev-secret-pharma-2026";
    const payload = jwt.verify(token, jwtSecret);
    return res.json({
      active: true,
      scope: payload.scope,
      client_id: payload.client_id || "pharmaguard-smart-client",
      sub: payload.sub,
      patient: payload.patient,
      encounter: payload.encounter,
      exp: payload.exp,
    });
  } catch {
    return res.json({ active: false });
  }
}

/**
 * Simulates a SMART-on-FHIR EHR Launch (Epic / Cerner) with 1-click clinical sample data.
 */
export async function simulateSmartLaunchEndpoint(req, res) {
  const { ehrProvider, patientId, patientName, suspectDrug, reaction } = req.body || {};
  try {
    const simulation = simulateSmartEhrLaunch({
      ehrProvider,
      patientId,
      patientName,
      suspectDrug,
      reaction,
    });
    return res.json(simulation);
  } catch (err) {
    return res.status(500).json({ error: "simulation_failed", message: err.message });
  }
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
      submittedBy: req.user?._id || "640000000000000000000001",
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
      performedBy: req.user?._id || "640000000000000000000001",
      details: {
        fhirResourceId: parsed.fhirResourceId,
        subjectIdentifier: parsed.subjectIdentifier,
        isSerious: parsed.isSerious,
        seriousnessCriteria: parsed.seriousnessCriteria,
      },
    });

    // Broadcast real-time ingestion & SLA alert to connected clinical clients
    realtimeEventManager.broadcastReportCreated(report);

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

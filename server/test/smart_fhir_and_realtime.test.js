import test from "node:test";
import assert from "node:assert/strict";

process.env.JWT_SECRET = "pharmaguard-test-jwt-secret-minimum-32-chars-long-2026";

import {
  getSmartConfiguration,
  registerLaunchSession,
  createAuthorizationCode,
  exchangeSmartToken,
  simulateSmartEhrLaunch,
  verifySmartJwt,
} from "../src/utils/smartAuthEngine.js";
import { realtimeEventManager } from "../src/utils/realtimeEvents.js";
import { getFhirCapabilityStatement } from "../src/utils/fhirAdapter.js";

test("SMART on FHIR Discovery & Capability Metadata", async (t) => {
  await t.test("returns compliant SMART configuration object", () => {
    const config = getSmartConfiguration("https://hospital.org/api/fhir");
    assert.equal(config.issuer, "https://hospital.org/api/fhir");
    assert.equal(config.authorization_endpoint, "https://hospital.org/api/fhir/auth/authorize");
    assert.equal(config.token_endpoint, "https://hospital.org/api/fhir/auth/token");
    assert.ok(config.capabilities.includes("launch-ehr"));
    assert.ok(config.capabilities.includes("context-ehr-patient"));
    assert.ok(config.scopes_supported.includes("patient/AdverseEvent.write"));
    assert.ok(config.scopes_supported.includes("launch/patient"));
  });

  await t.test("embeds SMART OAuth URIs extension in FHIR CapabilityStatement", () => {
    const cap = getFhirCapabilityStatement();
    const rest = cap.rest[0];
    assert.ok(rest.security, "rest must define security");
    assert.equal(rest.security.cors, true);

    const service = rest.security.service[0];
    assert.equal(service.coding[0].code, "SMART-on-FHIR");

    const oauthExtension = rest.security.extension.find(
      (e) => e.url === "http://fhir-registry.smarthealthit.org/StructureDefinition/oauth-uris"
    );
    assert.ok(oauthExtension, "must include oauth-uris extension");
    const authUri = oauthExtension.extension.find((e) => e.url === "authorize");
    const tokenUri = oauthExtension.extension.find((e) => e.url === "token");
    assert.equal(authUri.valueUri, "/api/fhir/auth/authorize");
    assert.equal(tokenUri.valueUri, "/api/fhir/auth/token");
  });
});

test("SMART on FHIR EHR Launch & Authorization Flow", async (t) => {
  await t.test("registers launch session from EHR launch identifier", () => {
    const session = registerLaunchSession({
      launchId: "epic-launch-test-123",
      iss: "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4",
      patientId: "PATIENT-EPIC-90210",
      encounterId: "ENC-4040",
      userId: "PRACTITIONER-DR-SMITH",
    });

    assert.equal(session.launchId, "epic-launch-test-123");
    assert.equal(session.patientId, "PATIENT-EPIC-90210");
    assert.equal(session.encounterId, "ENC-4040");
    assert.ok(session.expiresAt > Date.now());
  });

  await t.test("creates authorization code bound to launch context", () => {
    const code = createAuthorizationCode({
      clientId: "pharmaguard-ehr-client",
      redirectUri: "https://hospital.org/pharmaguard/callback",
      scope: "launch/patient patient/AdverseEvent.write",
      launchId: "epic-launch-test-123",
      userId: "PRACTITIONER-DR-SMITH",
    });

    assert.ok(code.startsWith("smart_code_"));
  });

  await t.test("exchanges code for access token with patient and encounter context", () => {
    const code = createAuthorizationCode({
      clientId: "pharmaguard-ehr-client",
      patientId: "PATIENT-CERNER-5511",
      encounterId: "ENC-CERNER-8899",
      userId: "DR-JOHNSON",
    });

    const tokenResponse = exchangeSmartToken({
      code,
      clientId: "pharmaguard-ehr-client",
    });

    assert.equal(tokenResponse.token_type, "Bearer");
    assert.equal(tokenResponse.patient, "PATIENT-CERNER-5511");
    assert.equal(tokenResponse.encounter, "ENC-CERNER-8899");
    assert.equal(tokenResponse.need_patient_banner, true);
    assert.ok(tokenResponse.access_token);

    // Verify token payload
    const decoded = verifySmartJwt(tokenResponse.access_token);
    assert.equal(decoded.sub, "DR-JOHNSON");
    assert.equal(decoded.patient, "PATIENT-CERNER-5511");
    assert.equal(decoded.encounter, "ENC-CERNER-8899");
    assert.equal(decoded.smart_context, true);
  });

  await t.test("prevents replay of spent authorization code", () => {
    const code = createAuthorizationCode({
      clientId: "pharmaguard-ehr-client",
      patientId: "PATIENT-REPLAY",
    });

    // First exchange succeeds
    exchangeSmartToken({ code, clientId: "pharmaguard-ehr-client" });

    // Second exchange must fail
    assert.throws(
      () => {
        exchangeSmartToken({ code, clientId: "pharmaguard-ehr-client" });
      },
      { message: /Invalid or expired authorization code/ }
    );
  });
});

test("SMART Simulated EHR Launch (Epic & Cerner)", async (t) => {
  await t.test("simulates complete 1-click Epic launch sequence", () => {
    const sim = simulateSmartEhrLaunch({
      ehrProvider: "Epic",
      patientId: "PATIENT-EPIC-7742",
      patientName: "Eleanor Vance",
      suspectDrug: "Lisinopril 20mg",
      reaction: "Severe Angioedema with Tongue Swelling",
    });

    assert.equal(sim.ehrProvider, "Epic");
    assert.equal(sim.patient.id, "PATIENT-EPIC-7742");
    assert.equal(sim.tokenResponse.patient, "PATIENT-EPIC-7742");
    assert.ok(sim.tokenResponse.access_token);
    assert.equal(sim.sampleFhirResource.resourceType, "AdverseEvent");
    assert.equal(sim.sampleFhirResource.subject.reference, "Patient/PATIENT-EPIC-7742");
    assert.equal(sim.sampleFhirResource.suspectEntity[0].instance.display, "Lisinopril 20mg");
  });

  await t.test("simulates Cerner launch with Cerner encounter and endpoint", () => {
    const sim = simulateSmartEhrLaunch({
      ehrProvider: "Cerner",
      patientId: "PATIENT-CERNER-100",
      patientName: "Marcus Brody",
      suspectDrug: "Amoxicillin-Clavulanate",
      reaction: "Stevens-Johnson Syndrome (SJS)",
    });

    assert.equal(sim.ehrProvider, "Cerner");
    assert.equal(sim.patient.id, "PATIENT-CERNER-100");
    assert.equal(sim.patient.encounterId, "ENC-CERNER-4419");
    assert.equal(sim.tokenResponse.encounter, "ENC-CERNER-4419");
  });
});

test("Real-Time Regulatory SLA Event Manager (SSE)", async (t) => {
  await t.test("registers client and sends connection handshake headers", (done) => {
    const writtenData = [];
    const headersSet = {};

    const mockReq = {
      on: (event, handler) => {
        if (event === "close") {
          // handler registered
        }
      },
    };

    const mockRes = {
      writeHead: (code, headers) => {
        headersSet.code = code;
        Object.assign(headersSet, headers);
      },
      write: (chunk) => {
        writtenData.push(chunk);
      },
    };

    const client = realtimeEventManager.registerClient(mockReq, mockRes);
    assert.equal(headersSet.code, 200);
    assert.equal(headersSet["Content-Type"], "text/event-stream");
    assert.ok(writtenData.length > 0);
    assert.ok(writtenData[0].includes("event: connected"));

    // Cleanup client
    realtimeEventManager.clients.delete(client);
  });

  await t.test("broadcasts SLA urgent alert and dispatches formatted SSE frame", () => {
    let capturedFrame = null;
    const mockClient = {
      id: "test-client",
      res: {
        write: (chunk) => {
          capturedFrame = chunk;
        },
      },
    };

    realtimeEventManager.clients.add(mockClient);

    const dummyReport = {
      _id: "507f1f77bcf86cd799439011",
      isSerious: true,
      ichE2ACriteria: ["life_threatening"],
      regulatoryDueDate: new Date(Date.now() + 12 * 3600 * 1000), // 12h remaining
      createdAt: new Date(),
      status: "pending_review",
    };

    const alert = realtimeEventManager.broadcastSlaAlert(dummyReport);
    assert.equal(alert.type, "SLA_URGENT_ALERT");
    assert.equal(alert.isExpedited7Day, true);
    assert.equal(alert.urgencyLevel, "critical_imminent");

    assert.ok(capturedFrame.includes("event: sla_alert"));
    assert.ok(capturedFrame.includes("critical_imminent"));

    realtimeEventManager.clients.delete(mockClient);
  });

  await t.test("broadcasts gateway transmission receipt", () => {
    let capturedFrame = null;
    const mockClient = {
      id: "test-client-gw",
      res: {
        write: (chunk) => {
          capturedFrame = chunk;
        },
      },
    };

    realtimeEventManager.clients.add(mockClient);

    const dummyReport = { _id: "507f1f77bcf86cd799439012" };
    const gatewayResult = {
      transmissionId: "CORE-ESG-TEST-99",
      status: "transmitted",
      mdnStatus: "acknowledged",
      micMatch: true,
    };

    const payload = realtimeEventManager.broadcastGatewayTransmission(dummyReport, gatewayResult);
    assert.equal(payload.type, "GATEWAY_TRANSMISSION");
    assert.equal(payload.transmissionId, "CORE-ESG-TEST-99");
    assert.ok(capturedFrame.includes("event: gateway_transmission"));

    realtimeEventManager.clients.delete(mockClient);
  });
});

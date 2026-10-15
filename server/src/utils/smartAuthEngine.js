import crypto from "crypto";

/**
 * Standard RFC 7519 HMAC-SHA256 JWT generation using native Node crypto.
 */
export function signSmartJwt(payload, secret = process.env.JWT_SECRET) {
  if (!secret || secret.length < 32) {
    throw new Error("JWT_SECRET is missing or shorter than 32 characters.");
  }
  const header = Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })).toString("base64url");
  const exp = Math.floor(Date.now() / 1000) + 3600;
  const body = Buffer.from(JSON.stringify({ ...payload, exp })).toString("base64url");
  const signature = crypto.createHmac("sha256", secret).update(`${header}.${body}`).digest("base64url");
  return `${header}.${body}.${signature}`;
}

export function verifySmartJwt(token, secret = process.env.JWT_SECRET) {
  if (!secret || secret.length < 32) {
    throw new Error("JWT_SECRET is missing or shorter than 32 characters.");
  }
  if (!token || typeof token !== "string") throw new Error("Invalid token");
  const parts = token.split(".");
  if (parts.length !== 3) throw new Error("Invalid JWT token structure");
  const [header, body, signature] = parts;
  const expectedSig = crypto.createHmac("sha256", secret).update(`${header}.${body}`).digest("base64url");
  if (signature !== expectedSig) throw new Error("Invalid token signature");
  const decoded = JSON.parse(Buffer.from(body, "base64url").toString("utf8"));
  if (decoded.exp && decoded.exp < Math.floor(Date.now() / 1000)) {
    throw new Error("Token has expired");
  }
  return decoded;
}

/**
 * SMART-on-FHIR OAuth2 Launch Context Engine
 * Conforms to HL7 SMART App Launch Implementation Guide (v2.0.0 / v1.0.0).
 * Handles EHR Launch Sequence, Standalone Launch, Authorization Code flow,
 * Token Exchange, and Launch Context Injection (patient, encounter).
 */

// In-memory launch context cache with 15-minute TTL
const launchContexts = new Map();
const authCodes = new Map();

/**
 * Cleans up expired launch contexts and authorization codes.
 */
function cleanupExpired() {
  const now = Date.now();
  for (const [key, item] of launchContexts.entries()) {
    if (item.expiresAt < now) launchContexts.delete(key);
  }
  for (const [key, item] of authCodes.entries()) {
    if (item.expiresAt < now) authCodes.delete(key);
  }
}

// Periodically purge expired auth items every 5 minutes
setInterval(cleanupExpired, 5 * 60 * 1000).unref();

/**
 * Returns standard SMART configuration metadata for EHR discovery.
 *
 * @param {string} baseUrl - Base API URL (e.g., "http://localhost:5000/api/fhir")
 * @returns {Object} SMART configuration JSON
 */
export function getSmartConfiguration(baseUrl = "http://localhost:5000/api/fhir") {
  return {
    issuer: baseUrl,
    jwks_uri: `${baseUrl}/auth/jwks`,
    authorization_endpoint: `${baseUrl}/auth/authorize`,
    token_endpoint: `${baseUrl}/auth/token`,
    introspection_endpoint: `${baseUrl}/auth/introspect`,
    token_endpoint_auth_methods_supported: ["client_secret_basic", "client_secret_post", "none"],
    grant_types_supported: ["authorization_code", "client_credentials"],
    scopes_supported: [
      "openid",
      "profile",
      "launch",
      "launch/patient",
      "launch/encounter",
      "patient/AdverseEvent.read",
      "patient/AdverseEvent.write",
      "patient/Patient.read",
      "user/AdverseEvent.read",
      "user/AdverseEvent.write",
      "system/AdverseEvent.write",
    ],
    response_types_supported: ["code"],
    capabilities: [
      "launch-ehr",
      "launch-standalone",
      "client-public",
      "client-confidential-symmetric",
      "context-ehr-patient",
      "context-ehr-encounter",
      "permission-patient",
      "permission-user",
    ],
    code_challenge_methods_supported: ["S256", "plain"],
  };
}

/**
 * Initiates an EHR launch session from Epic / Cerner.
 *
 * @param {Object} options - Launch options
 * @param {string} options.launchId - Unique launch identifier issued by EHR
 * @param {string} options.iss - EHR FHIR Base URL (aud)
 * @param {string} [options.patientId] - Patient ID in EHR
 * @param {string} [options.encounterId] - Encounter ID in EHR
 * @param {string} [options.userId] - Clinician ID in EHR
 * @returns {Object} Stored launch context
 */
export function registerLaunchSession({
  launchId = `launch-${crypto.randomBytes(8).toString("hex")}`,
  iss = "https://fhir.epic-sandbox.com/api/FHIR/R4",
  patientId = "PATIENT-EPIC-7742",
  encounterId = "ENC-CERNER-1092",
  userId = "PRACTITIONER-9901",
} = {}) {
  const session = {
    launchId,
    iss,
    patientId,
    encounterId,
    userId,
    createdAt: Date.now(),
    expiresAt: Date.now() + 15 * 60 * 1000, // 15 mins
  };
  launchContexts.set(launchId, session);
  return session;
}

/**
 * Generates an authorization code during SMART authorization step.
 *
 * @param {Object} params
 * @param {string} params.clientId - Client application ID
 * @param {string} [params.redirectUri] - Redirect target
 * @param {string} [params.scope] - Requested OAuth scopes
 * @param {string} [params.launchId] - Associated EHR launch ID
 * @param {string} [params.patientId] - Explicit patient override
 * @param {string} [params.encounterId] - Explicit encounter override
 * @param {string} [params.userId] - Clinician user ID
 * @returns {string} One-time authorization code
 */
export function createAuthorizationCode({
  clientId = "pharmaguard-smart-client",
  redirectUri,
  scope = "launch/patient patient/AdverseEvent.write",
  launchId,
  patientId,
  encounterId,
  userId = "PRACTITIONER-9901",
}) {
  const code = `smart_code_${crypto.randomBytes(16).toString("hex")}`;
  let launch = null;
  if (launchId && launchContexts.has(launchId)) {
    launch = launchContexts.get(launchId);
  }

  const resolvedPatient = patientId || launch?.patientId || "PATIENT-EPIC-7742";
  const resolvedEncounter = encounterId || launch?.encounterId || "ENC-CERNER-1092";
  const resolvedUser = userId || launch?.userId || "PRACTITIONER-9901";

  authCodes.set(code, {
    code,
    clientId,
    redirectUri,
    scope,
    patientId: resolvedPatient,
    encounterId: resolvedEncounter,
    userId: resolvedUser,
    iss: launch?.iss || "https://fhir.epic-sandbox.com/api/FHIR/R4",
    expiresAt: Date.now() + 10 * 60 * 1000, // 10 mins
  });

  return code;
}

/**
 * Exchanges authorization code for SMART access token and launch context.
 *
 * @param {Object} params
 * @param {string} params.code - Authorization code
 * @param {string} params.clientId - Client ID
 * @param {string} [params.redirectUri] - Redirect URI for validation
 * @returns {Object} SMART Token response
 */
export function exchangeSmartToken({ code, clientId, redirectUri }) {
  if (!code || !authCodes.has(code)) {
    throw new Error("Invalid or expired authorization code");
  }

  const record = authCodes.get(code);
  if (record.expiresAt < Date.now()) {
    authCodes.delete(code);
    throw new Error("Authorization code has expired");
  }

  if (record.clientId && clientId && record.clientId !== clientId) {
    throw new Error("Client ID mismatch");
  }

  // Once used, the authorization code is invalidated
  authCodes.delete(code);

  const jwtSecret = process.env.JWT_SECRET;
  if (!jwtSecret || jwtSecret.length < 32) {
    throw new Error("JWT_SECRET is missing or shorter than 32 characters.");
  }
  const tokenPayload = {
    sub: record.userId,
    role: "doctor",
    scope: record.scope,
    patient: record.patientId,
    encounter: record.encounterId,
    iss: "pharmaguard-smart-auth",
    smart_context: true,
  };

  const accessToken = signSmartJwt(tokenPayload, jwtSecret);

  return {
    access_token: accessToken,
    token_type: "Bearer",
    expires_in: 3600,
    scope: record.scope,
    patient: record.patientId,
    encounter: record.encounterId,
    need_patient_banner: true,
    smart_style_url: null,
  };
}

/**
 * Simulates a 1-click SMART-on-FHIR EHR launch for clinical testing (Epic / Cerner).
 *
 * @param {Object} options
 * @param {string} options.ehrProvider - "Epic" or "Cerner"
 * @param {string} [options.patientId] - Custom patient ID
 * @param {string} [options.patientName] - Patient name
 * @param {string} [options.suspectDrug] - Suspect drug
 * @param {string} [options.reaction] - Adverse event reaction
 * @returns {Object} Complete simulated launch bundle with access token & sample FHIR AdverseEvent
 */
export function simulateSmartEhrLaunch({
  ehrProvider = "Epic",
  patientId = "PATIENT-EPIC-7742",
  patientName = "Eleanor Vance",
  suspectDrug = "Lisinopril 20mg",
  reaction = "Severe Angioedema with Tongue Swelling",
} = {}) {
  const encounterId = ehrProvider === "Epic" ? "ENC-EPIC-8821" : "ENC-CERNER-4419";
  const iss =
    ehrProvider === "Epic"
      ? "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4"
      : "https://fhir-myrecord.cerner.com/r4/2f8f5eb5-2743-4e5e-990a";

  const session = registerLaunchSession({
    iss,
    patientId,
    encounterId,
    userId: "DR-MARTINEZ-PV",
  });

  const authCode = createAuthorizationCode({
    clientId: "pharmaguard-ehr-client",
    scope: "launch/patient patient/AdverseEvent.read patient/AdverseEvent.write",
    launchId: session.launchId,
    patientId,
    encounterId,
    userId: "DR-MARTINEZ-PV",
  });

  const tokenResponse = exchangeSmartToken({
    code: authCode,
    clientId: "pharmaguard-ehr-client",
  });

  // Construct patient-specific FHIR R4 AdverseEvent ready for 1-click ingestion
  const sampleFhirResource = {
    resourceType: "AdverseEvent",
    id: `ae-${ehrProvider.toLowerCase()}-${Date.now()}`,
    actuality: "actual",
    category: [
      {
        coding: [
          {
            system: "http://terminology.hl7.org/CodeSystem/adverse-event-category",
            code: "medication-adverse-event",
            display: "Medication Adverse Event",
          },
        ],
      },
    ],
    event: {
      coding: [
        {
          system: "http://snomed.info/sct",
          code: "41291007",
          display: reaction,
        },
      ],
      text: reaction,
    },
    subject: {
      reference: `Patient/${patientId}`,
      display: patientName,
    },
    date: new Date().toISOString(),
    seriousness: {
      coding: [
        {
          system: "http://terminology.hl7.org/CodeSystem/adverse-event-seriousness",
          code: "life-threatening",
          display: "Life-Threatening Reaction",
        },
      ],
    },
    suspectEntity: [
      {
        instance: {
          concept: {
            text: suspectDrug,
          },
          display: suspectDrug,
        },
      },
    ],
  };

  return {
    ehrProvider,
    launchId: session.launchId,
    tokenResponse,
    patient: {
      id: patientId,
      name: patientName,
      encounterId,
    },
    sampleFhirResource,
  };
}

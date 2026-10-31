import { Router } from "express";
import {
  getCapabilityStatement,
  getSmartConfig,
  initiateSmartLaunch,
  authorizeSmartLaunch,
  tokenExchangeSmartLaunch,
  introspectSmartToken,
  simulateSmartLaunchEndpoint,
  ingestFhirAdverseEvent,
  getFhirAdverseEventById,
  requireSmartSandbox,
} from "../controllers/fhirController.js";
import { requireAuth } from "../middleware/auth.js";
import { requireRole } from "../middleware/rbac.js";

const router = Router();

// 1. Open SMART-on-FHIR Capability & Discovery Endpoints
router.get("/metadata", getCapabilityStatement);
router.get("/.well-known/smart-configuration", getSmartConfig);

// 2. SMART-on-FHIR OAuth2 Launch Handshake Flow
// Sandbox-only: these mint access tokens without a real EHR identity provider, so they are
// disabled in production unless SMART_SANDBOX_ENABLED=true (see requireSmartSandbox).
router.get("/auth/launch", requireSmartSandbox, initiateSmartLaunch);
router.get("/auth/authorize", requireSmartSandbox, authorizeSmartLaunch);
router.post("/auth/authorize", requireSmartSandbox, authorizeSmartLaunch);
router.post("/auth/token", requireSmartSandbox, tokenExchangeSmartLaunch);
router.post("/auth/introspect", introspectSmartToken);

// 3. Clinical Testing: 1-Click SMART EHR Launch Simulator (Epic / Cerner)
router.post("/launch/simulate", requireSmartSandbox, simulateSmartLaunchEndpoint);

// 4. FHIR AdverseEvent Ingestion & Reading
router.use(requireAuth);
router.post("/AdverseEvent", requireRole("doctor", "admin", "pharmacist"), ingestFhirAdverseEvent);
router.post("/Bundle", requireRole("doctor", "admin", "pharmacist"), ingestFhirAdverseEvent);
router.get("/AdverseEvent/:id", requireRole("doctor", "pharmacist", "researcher", "admin"), getFhirAdverseEventById);

export default router;

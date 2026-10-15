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
} from "../controllers/fhirController.js";
import { requireAuth } from "../middleware/auth.js";
import { requireRole } from "../middleware/rbac.js";

const router = Router();

// 1. Open SMART-on-FHIR Capability & Discovery Endpoints
router.get("/metadata", getCapabilityStatement);
router.get("/.well-known/smart-configuration", getSmartConfig);

// Guard to disable simulator in production
const devOnly = (req, res, next) => {
  if (process.env.NODE_ENV === "production") {
    return res.status(403).json({ error: "EHR launch simulation is disabled in production environments." });
  }
  next();
};

// 2. SMART-on-FHIR OAuth2 Launch Handshake Flow
router.get("/auth/launch", initiateSmartLaunch);
router.get("/auth/authorize", authorizeSmartLaunch);
router.post("/auth/authorize", authorizeSmartLaunch);
router.post("/auth/token", (req, res, next) => {
  if (!req.body || !req.body.code) {
    return res.status(400).json({
      error: "invalid_request",
      error_description: "Missing required 'code' parameter in authorization code grant.",
    });
  }
  return tokenExchangeSmartLaunch(req, res, next);
});
router.post("/auth/introspect", introspectSmartToken);

// 3. Clinical Testing: 1-Click SMART EHR Launch Simulator (Epic / Cerner)
router.post("/launch/simulate", devOnly, simulateSmartLaunchEndpoint);

// 4. FHIR AdverseEvent Ingestion & Reading
router.use(requireAuth);
router.post("/AdverseEvent", requireRole("doctor", "admin", "pharmacist"), ingestFhirAdverseEvent);
router.post("/Bundle", requireRole("doctor", "admin", "pharmacist"), ingestFhirAdverseEvent);
router.get("/AdverseEvent/:id", requireRole("doctor", "pharmacist", "researcher", "admin"), getFhirAdverseEventById);

export default router;

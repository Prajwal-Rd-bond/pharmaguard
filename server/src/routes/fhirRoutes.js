import { Router } from "express";
import { getCapabilityStatement, ingestFhirAdverseEvent, getFhirAdverseEventById } from "../controllers/fhirController.js";
import { requireAuth } from "../middleware/auth.js";
import { requireRole } from "../middleware/rbac.js";

const router = Router();

// CapabilityStatement is open for client capability querying
router.get("/metadata", getCapabilityStatement);

// FHIR AdverseEvent Ingestion and Reading requires authentication
router.use(requireAuth);

router.post("/AdverseEvent", requireRole("doctor", "admin", "pharmacist"), ingestFhirAdverseEvent);
router.post("/Bundle", requireRole("doctor", "admin", "pharmacist"), ingestFhirAdverseEvent);
router.get("/AdverseEvent/:id", requireRole("doctor", "pharmacist", "researcher", "admin"), getFhirAdverseEventById);

export default router;

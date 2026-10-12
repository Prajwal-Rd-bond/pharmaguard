import { Router } from "express";
import { listAuditLogs, verifyAudit } from "../controllers/auditController.js";
import { requireAuth } from "../middleware/auth.js";
import { requireRole } from "../middleware/rbac.js";

const router = Router();

router.use(requireAuth, requireRole("admin", "pharmacist"));
router.get("/verify", verifyAudit);
router.get("/", listAuditLogs);

export default router;

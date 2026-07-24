import { Router } from "express";
import { listAuditLogs } from "../controllers/auditController.js";
import { requireAuth } from "../middleware/auth.js";
import { requireRole } from "../middleware/rbac.js";

const router = Router();

router.use(requireAuth, requireRole("admin", "pharmacist"));
router.get("/", listAuditLogs);

export default router;

import { Router } from "express";
import multer from "multer";
import {
  createReport,
  runReportPipeline,
  getReport,
  listReports,
  reviewReport,
} from "../controllers/reportController.js";
import { requireAuth } from "../middleware/auth.js";
import { requireRole } from "../middleware/rbac.js";

const upload = multer({ storage: multer.memoryStorage(), limits: { fileSize: 10 * 1024 * 1024 } });
const router = Router();

router.use(requireAuth);

// Intake — Doctors submit, Admins can too. (PDF/DOCX text extraction happens in this route's handler
// in a full implementation; this scaffold accepts pasted text / already-extracted text.)
router.post("/", requireRole("doctor", "admin"), upload.single("file"), createReport);

// Queue + detail — Pharmacists/Researchers/Admins can view.
router.get("/", requireRole("pharmacist", "researcher", "admin"), listReports);
router.get("/:id", requireRole("pharmacist", "researcher", "admin", "doctor"), getReport);

// Run pipeline — Pharmacist or Admin triggers processing.
router.post("/:id/run-pipeline", requireRole("pharmacist", "admin"), runReportPipeline);

// Human approval workflow — Module 9. Pharmacist-only.
router.post("/:id/review", requireRole("pharmacist", "admin"), reviewReport);

export default router;

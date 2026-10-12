import { Router } from "express";
import multer from "multer";
import {
  createReport,
  runReportPipeline,
  getReport,
  getPipelineStatus,
  listReports,
  reviewReport,
  exportFeedbackDataset,
  exportReportE2BXml,
  checkDuplicateReports,
  updateReportCausality,
} from "../controllers/reportController.js";
import { requireAuth } from "../middleware/auth.js";
import { requireRole } from "../middleware/rbac.js";

const upload = multer({ storage: multer.memoryStorage(), limits: { fileSize: 10 * 1024 * 1024 } });
const router = Router();

router.use(requireAuth);

// Intake — Doctors submit, Admins can too.
router.post("/", requireRole("doctor", "admin"), upload.single("file"), createReport);

// Phase 2D: Curated gold-standard labeled feedback dataset export
router.get("/eval/feedback-dataset", requireRole("pharmacist", "researcher", "admin"), exportFeedbackDataset);

// Queue + detail + async status — Pharmacists/Researchers/Admins can view.
router.get("/", requireRole("pharmacist", "researcher", "admin"), listReports);
router.get("/:id", requireRole("pharmacist", "researcher", "admin", "doctor"), getReport);
router.get("/:id/status", requireRole("pharmacist", "researcher", "admin", "doctor"), getPipelineStatus);

// Phase 2B: E2B(R3) ICSR XML Export
router.get("/:id/export/e2b", requireRole("pharmacist", "researcher", "admin"), exportReportE2BXml);

// Phase 2B: Duplicate ICSR check
router.get("/:id/duplicate-check", requireRole("pharmacist", "researcher", "admin"), checkDuplicateReports);

// Phase 2B: Confirm or override Causality Assessment
router.post("/:id/causality", requireRole("pharmacist", "admin"), updateReportCausality);

// Run pipeline — Pharmacist or Admin triggers processing.
router.post("/:id/run-pipeline", requireRole("pharmacist", "admin"), runReportPipeline);

// Human approval workflow — Module 9. Pharmacist-only.
router.post("/:id/review", requireRole("pharmacist", "admin"), reviewReport);

export default router;

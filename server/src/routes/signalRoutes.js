import express from "express";
import { authenticate } from "../middleware/auth.js";
import { getSignalDashboard, detectSignal, getKnowledgeGraph } from "../controllers/signalController.js";

const router = express.Router();

router.use(authenticate);

// Pharmacovigilance FAERS signal analytics overview
router.get("/dashboard", getSignalDashboard);

// Quantitative disproportionality detection (PRR / ROR / Evans) for a specific drug & reaction
router.get("/detect", detectSignal);

// Drug-event clinical knowledge graph explorer
router.get("/knowledge-graph", getKnowledgeGraph);

export default router;


import { Router } from "express";
import { register, login, me, setupMFA, verifyMFA, disableMFA } from "../controllers/authController.js";
import { requireAuth } from "../middleware/auth.js";

const router = Router();

router.post("/register", register);
router.post("/login", login);
router.get("/me", requireAuth, me);

// Phase 2E: Two-Factor Authentication (TOTP)
router.post("/mfa/setup", requireAuth, setupMFA);
router.post("/mfa/verify", requireAuth, verifyMFA);
router.post("/mfa/disable", requireAuth, disableMFA);

export default router;

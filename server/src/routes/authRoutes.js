import { Router } from "express";
import { register, login, me, setupMFA, verifyMFA, disableMFA } from "../controllers/authController.js";
import { requireAuth } from "../middleware/auth.js";
import { rateLimiter } from "../middleware/rateLimiter.js";

const router = Router();

const authLimiter = rateLimiter({
  windowMs: 15 * 60 * 1000,
  max: 50,
  message: "Too many authentication attempts, please try again later."
});

router.post("/register", authLimiter, register);
router.post("/login", authLimiter, login);
router.get("/me", requireAuth, me);

// Phase 2E: Two-Factor Authentication (TOTP)
router.post("/mfa/setup", requireAuth, setupMFA);
router.post("/mfa/verify", requireAuth, verifyMFA);
router.post("/mfa/disable", requireAuth, disableMFA);

export default router;

import { Router } from "express";
import { listUsers, createUser, setUserActive } from "../controllers/userController.js";
import { requireAuth } from "../middleware/auth.js";
import { requireRole } from "../middleware/rbac.js";

const router = Router();

router.use(requireAuth, requireRole("admin"));
router.get("/", listUsers);
router.post("/", createUser);
router.patch("/:id/active", setUserActive);

export default router;

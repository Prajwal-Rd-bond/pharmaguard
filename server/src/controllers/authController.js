import jwt from "jsonwebtoken";
import User, { ROLES } from "../models/User.js";
import { logAction } from "../middleware/auditLogger.js";

function signToken(user) {
  return jwt.sign({ sub: user._id.toString(), role: user.role }, process.env.JWT_SECRET, {
    expiresIn: process.env.JWT_EXPIRES_IN || "8h",
  });
}

// Admin-only in practice (see routes/userRoutes.js for the RBAC-gated version).
// Left here as a standalone registration path for initial bootstrap/dev seeding.
export async function register(req, res) {
  const { name, email, password, role } = req.body;
  if (!name || !email || !password || !role) {
    return res.status(400).json({ error: "name, email, password, role are required" });
  }
  if (!ROLES.includes(role)) return res.status(400).json({ error: `role must be one of ${ROLES.join(", ")}` });

  const existing = await User.findOne({ email: email.toLowerCase() });
  if (existing) return res.status(409).json({ error: "Email already registered" });

  const user = new User({ name, email, role });
  await user.setPassword(password);
  await user.save();

  await logAction({ actor: user._id, actorType: "user", action: "user.register", details: { role } });

  res.status(201).json({ user: user.toSafeJSON() });
}

export async function login(req, res) {
  const { email, password } = req.body;
  if (!email || !password) return res.status(400).json({ error: "email and password are required" });

  const user = await User.findOne({ email: email.toLowerCase() });
  if (!user || !user.active || !(await user.checkPassword(password))) {
    return res.status(401).json({ error: "Invalid credentials" });
  }

  const token = signToken(user);
  await logAction({ actor: user._id, actorType: "user", action: "user.login" });

  res.json({ token, user: user.toSafeJSON() });
}

export async function me(req, res) {
  res.json({ user: req.user.toSafeJSON() });
}

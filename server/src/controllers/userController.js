import User, { ROLES } from "../models/User.js";
import { logAction } from "../middleware/auditLogger.js";

// Module 1 — Admin-only user management.
export async function listUsers(req, res) {
  const users = await User.find().sort({ createdAt: -1 });
  res.json({ users: users.map((u) => u.toSafeJSON()) });
}

export async function createUser(req, res) {
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

  await logAction({ actor: req.user._id, action: "user.create", details: { createdUser: user._id, role } });

  res.status(201).json({ user: user.toSafeJSON() });
}

export async function setUserActive(req, res) {
  const { active } = req.body;
  const user = await User.findById(req.params.id);
  if (!user) return res.status(404).json({ error: "User not found" });

  user.active = !!active;
  await user.save();

  await logAction({ actor: req.user._id, action: active ? "user.activate" : "user.deactivate", details: { targetUser: user._id } });

  res.json({ user: user.toSafeJSON() });
}

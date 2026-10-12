import jwt from "jsonwebtoken";
import User, { ROLES } from "../models/User.js";
import { logAction } from "../middleware/auditLogger.js";
import { generateTOTPSecret, verifyTOTPToken } from "../utils/totp.js";

function signToken(user) {
  return jwt.sign({ sub: user._id.toString(), role: user.role }, process.env.JWT_SECRET, {
    expiresIn: process.env.JWT_EXPIRES_IN || "8h",
  });
}

// Standalone registration: Allows initial bootstrap admin if DB is empty,
// or self-registration strictly as 'doctor'. Creating 'admin', 'pharmacist',
// or 'researcher' requires an authenticated admin (see routes/userRoutes.js).
export async function register(req, res) {
  const { name, email, password, role } = req.body;
  if (!name || !email || !password) {
    return res.status(400).json({ error: "name, email, and password are required" });
  }

  const userCount = await User.countDocuments();
  let assignedRole = role || "doctor";

  if (userCount === 0) {
    // Initial bootstrap: allow first user to be admin if requested
    assignedRole = role || "admin";
  } else {
    // If public registration is explicitly disabled
    if (process.env.ALLOW_PUBLIC_REGISTRATION === "false") {
      return res.status(403).json({ error: "Public registration is disabled. Contact an administrator." });
    }
    // Non-bootstrap self-registration: only 'doctor' role is permitted
    if (role && role !== "doctor") {
      return res.status(403).json({ error: "Self-registration is restricted to the 'doctor' role. Contact an admin for elevated privileges." });
    }
    assignedRole = "doctor";
  }

  if (!ROLES.includes(assignedRole)) {
    return res.status(400).json({ error: `role must be one of ${ROLES.join(", ")}` });
  }

  const existing = await User.findOne({ email: email.toLowerCase() });
  if (existing) return res.status(409).json({ error: "Email already registered" });

  const user = new User({ name, email, role: assignedRole });
  await user.setPassword(password);
  await user.save();

  await logAction({ actor: user._id, actorType: "user", action: "user.register", details: { role: assignedRole } });

  res.status(201).json({ user: user.toSafeJSON() });
}

export async function login(req, res) {
  const { email, password, mfaToken } = req.body;
  if (!email || !password) return res.status(400).json({ error: "email and password are required" });

  const user = await User.findOne({ email: email.toLowerCase() });
  if (!user || !user.active || !(await user.checkPassword(password))) {
    return res.status(401).json({ error: "Invalid credentials" });
  }

  // Phase 2E: Two-Factor Authentication Check
  if (user.mfaEnabled) {
    if (!mfaToken) {
      return res.json({
        mfaRequired: true,
        userId: user._id,
        email: user.email,
        message: "Two-factor authentication code required.",
      });
    }

    const isValidToken = verifyTOTPToken(user.mfaSecret, mfaToken);
    if (!isValidToken) {
      return res.status(401).json({ error: "Invalid two-factor authentication code." });
    }
  }

  const token = signToken(user);
  await logAction({ actor: user._id, actorType: "user", action: "user.login" });

  res.json({ token, user: user.toSafeJSON() });
}

export async function me(req, res) {
  res.json({ user: req.user.toSafeJSON() });
}

// Phase 2E: Initiate MFA Setup (Generates secret and otpauth URL)
export async function setupMFA(req, res) {
  const user = await User.findById(req.user._id);
  if (!user) return res.status(404).json({ error: "User not found" });

  const { secret, otpauthUrl } = generateTOTPSecret(user.email, "PharmaGuard Safety");
  user.mfaSecret = secret;
  await user.save();

  res.json({
    secret,
    otpauthUrl,
    message: "Add this secret to your authenticator app (Google Authenticator, Authy, 1Password), then submit a 6-digit code to /api/auth/mfa/verify to activate.",
  });
}

// Phase 2E: Verify and Activate MFA
export async function verifyMFA(req, res) {
  const { token } = req.body;
  if (!token) return res.status(400).json({ error: "Verification token is required" });

  const user = await User.findById(req.user._id);
  if (!user || !user.mfaSecret) {
    return res.status(400).json({ error: "MFA setup has not been initiated. Call /setup first." });
  }

  const isValid = verifyTOTPToken(user.mfaSecret, token);
  if (!isValid) {
    return res.status(400).json({ error: "Invalid verification code. Please check your authenticator clock and try again." });
  }

  user.mfaEnabled = true;
  await user.save();

  await logAction({ actor: user._id, actorType: "user", action: "user.mfa_enabled" });

  res.json({ ok: true, message: "Two-Factor Authentication successfully enabled.", user: user.toSafeJSON() });
}

// Phase 2E: Disable MFA
export async function disableMFA(req, res) {
  const { token } = req.body;
  const user = await User.findById(req.user._id);
  if (!user) return res.status(404).json({ error: "User not found" });

  if (user.mfaEnabled) {
    if (!token || !verifyTOTPToken(user.mfaSecret, token)) {
      return res.status(400).json({ error: "A valid MFA token is required to disable Two-Factor Authentication." });
    }
  }

  user.mfaEnabled = false;
  user.mfaSecret = null;
  await user.save();

  await logAction({ actor: user._id, actorType: "user", action: "user.mfa_disabled" });

  res.json({ ok: true, message: "Two-Factor Authentication disabled.", user: user.toSafeJSON() });
}

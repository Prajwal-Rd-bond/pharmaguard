import jwt from "jsonwebtoken";
import User, { ROLES } from "../models/User.js";
import { logAction } from "../middleware/auditLogger.js";
import { generateTOTPSecret } from "../utils/totp.js";
import { getJwtSecret } from "../config/secrets.js";
import {
  MFA_PENDING_TTL_SECONDS,
  signMfaPendingToken,
  verifyMfaPendingToken,
  encryptMfaSecret,
  verifyUserMfaCode,
} from "../utils/mfaService.js";

function signToken(user) {
  return jwt.sign(
    { sub: user._id.toString(), role: user.role, typ: "access" },
    getJwtSecret(),
    {
      expiresIn: process.env.JWT_EXPIRES_IN || "8h",
    }
  );
}

// Public registration is disabled to prevent unauthenticated privilege escalation.
// All users must be provisioned by an administrator via POST /api/users.
export async function register(req, res) {
  return res.status(403).json({
    error: "Public registration is disabled. User accounts must be provisioned by an administrator.",
  });
}

export async function login(req, res) {
  const { email, password, mfaToken, mfaPendingToken } = req.body || {};

  // Support completing MFA second step via /api/auth/login if mfaPendingToken is supplied
  if (mfaPendingToken && !password) {
    return verifyLogin(req, res);
  }

  // Reject any attempt to complete MFA using plaintext userId + mfaToken without password/mfaPendingToken
  if (req.body?.userId && mfaToken && (!email || !password)) {
    return res.status(401).json({
      error: "Direct userId + TOTP login is forbidden. A signed mfaPendingToken from password authentication is required.",
    });
  }

  if (!email || !password) return res.status(400).json({ error: "email and password are required" });

  const user = await User.findOne({ email: email.toLowerCase() });
  if (!user || !user.active || !(await user.checkPassword(password))) {
    return res.status(401).json({ error: "Invalid credentials" });
  }

  // Phase 2E: Two-Factor Authentication Check
  if (user.mfaEnabled) {
    if (!mfaToken) {
      const pendingToken = signMfaPendingToken(user);
      return res.json({
        mfaRequired: true,
        mfaPendingToken: pendingToken,
        expiresIn: MFA_PENDING_TTL_SECONDS,
        message: "Two-factor authentication code required.",
      });
    }

    const verification = await verifyUserMfaCode(user, mfaToken);
    if (!verification.ok) {
      return res.status(verification.status).json({ error: verification.error });
    }
  }

  const token = signToken(user);
  await logAction({ actor: user._id, actorType: "user", action: "user.login" });

  res.json({ token, user: user.toSafeJSON() });
}

// Phase 2E: Complete MFA Login using short-lived signed mfaPendingToken + TOTP code
export async function verifyLogin(req, res) {
  const { mfaPendingToken, token, mfaToken, userId } = req.body || {};
  const totpCode = token || mfaToken;

  if (!mfaPendingToken) {
    if (userId) {
      return res.status(401).json({
        error: "userId cannot be used to verify MFA login; a signed mfaPendingToken is required.",
      });
    }
    return res.status(401).json({ error: "mfaPendingToken is required" });
  }

  if (!totpCode) {
    return res.status(400).json({ error: "Two-factor authentication token is required" });
  }

  let payload;
  try {
    payload = verifyMfaPendingToken(mfaPendingToken);
  } catch {
    return res.status(401).json({ error: "Invalid or expired MFA session token" });
  }

  const user = await User.findById(payload.sub);
  if (!user || !user.active || !user.mfaEnabled) {
    return res.status(401).json({ error: "Invalid or inactive user" });
  }

  const verification = await verifyUserMfaCode(user, totpCode);
  if (!verification.ok) {
    return res.status(verification.status).json({ error: verification.error });
  }

  const accessToken = signToken(user);
  await logAction({ actor: user._id, actorType: "user", action: "user.login_mfa" });

  return res.json({ token: accessToken, user: user.toSafeJSON() });
}

export async function me(req, res) {
  res.json({ user: req.user.toSafeJSON() });
}

// Phase 2E: Initiate MFA Setup (Generates secret and otpauth URL; stores encrypted secret at rest)
export async function setupMFA(req, res) {
  const user = await User.findById(req.user._id);
  if (!user) return res.status(404).json({ error: "User not found" });

  const { secret, otpauthUrl } = generateTOTPSecret(user.email, "PharmaGuard Safety");
  user.mfaSecret = encryptMfaSecret(secret);
  user.mfaLastUsedStep = null;
  user.mfaFailedAttempts = 0;
  user.mfaLockedUntil = null;
  await user.save();

  res.json({
    secret,
    otpauthUrl,
    message: "Add this secret to your authenticator app (Google Authenticator, Authy, 1Password), then submit a 6-digit code to /api/auth/mfa/verify to activate.",
  });
}

// Phase 2E: Verify and Activate MFA
export async function verifyMFA(req, res) {
  const { token } = req.body || {};
  if (!token) return res.status(400).json({ error: "Verification token is required" });

  const user = await User.findById(req.user._id);
  if (!user || !user.mfaSecret) {
    return res.status(400).json({ error: "MFA setup has not been initiated. Call /setup first." });
  }

  const verification = await verifyUserMfaCode(user, token);
  if (!verification.ok) {
    const status = verification.reason === "locked" ? 429 : 400;
    return res.status(status).json({
      error:
        verification.reason === "invalid_code"
          ? "Invalid verification code. Please check your authenticator clock and try again."
          : verification.error,
    });
  }

  user.mfaEnabled = true;
  await user.save();

  await logAction({ actor: user._id, actorType: "user", action: "user.mfa_enabled" });

  res.json({ ok: true, message: "Two-Factor Authentication successfully enabled.", user: user.toSafeJSON() });
}

// Phase 2E: Disable MFA
export async function disableMFA(req, res) {
  const { token } = req.body || {};
  const user = await User.findById(req.user._id);
  if (!user) return res.status(404).json({ error: "User not found" });

  if (user.mfaEnabled) {
    if (!token) {
      return res.status(400).json({ error: "A valid MFA token is required to disable Two-Factor Authentication." });
    }
    const verification = await verifyUserMfaCode(user, token);
    if (!verification.ok) {
      const status = verification.reason === "locked" ? 429 : 400;
      return res.status(status).json({
        error:
          verification.reason === "invalid_code"
            ? "A valid MFA token is required to disable Two-Factor Authentication."
            : verification.error,
      });
    }
  }

  user.mfaEnabled = false;
  user.mfaSecret = null;
  user.mfaLastUsedStep = null;
  user.mfaFailedAttempts = 0;
  user.mfaLockedUntil = null;
  await user.save();

  await logAction({ actor: user._id, actorType: "user", action: "user.mfa_disabled" });

  res.json({ ok: true, message: "Two-Factor Authentication disabled.", user: user.toSafeJSON() });
}

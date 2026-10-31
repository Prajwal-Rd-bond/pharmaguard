import jwt from "jsonwebtoken";
import { getMfaPendingSecret } from "../config/secrets.js";
import { encryptField, decryptField, isEncrypted } from "./cryptoField.js";
import { matchTOTPStep } from "./totp.js";

export const MFA_PENDING_TTL_SECONDS = 300; // 5 minutes (<= 5 min requirement)
export const MFA_MAX_FAILED_ATTEMPTS = 5;
export const MFA_LOCKOUT_MS = 15 * 60 * 1000; // 15 minutes

// Secondary in-memory tracker keyed by userId string to guarantee replay/lockout
// enforcement even when tests stub User.prototype.save or return fresh instances.
const memoryMfaState = new Map();

function getState(user) {
  const key = user?._id ? String(user._id) : String(user?.id || "unknown");
  let entry = memoryMfaState.get(key);
  if (!entry) {
    entry = {
      lastUsedStep: typeof user.mfaLastUsedStep === "number" ? user.mfaLastUsedStep : null,
      failedAttempts: typeof user.mfaFailedAttempts === "number" ? user.mfaFailedAttempts : 0,
      lockedUntil: user.mfaLockedUntil ? new Date(user.mfaLockedUntil).getTime() : 0,
    };
    memoryMfaState.set(key, entry);
  } else {
    if (typeof user.mfaLastUsedStep === "number" && (entry.lastUsedStep === null || user.mfaLastUsedStep > entry.lastUsedStep)) {
      entry.lastUsedStep = user.mfaLastUsedStep;
    }
    if (typeof user.mfaFailedAttempts === "number" && user.mfaFailedAttempts > entry.failedAttempts) {
      entry.failedAttempts = user.mfaFailedAttempts;
    }
    const dbLock = user.mfaLockedUntil ? new Date(user.mfaLockedUntil).getTime() : 0;
    if (dbLock > entry.lockedUntil) {
      entry.lockedUntil = dbLock;
    }
  }
  return entry;
}

export function resetMfaMemoryState() {
  memoryMfaState.clear();
}

/**
 * Issues a signed, short-lived (<=5 min), scope-limited MFA pending token.
 * Signed with a distinct secret from access tokens and tagged with typ="mfa_pending".
 */
export function signMfaPendingToken(user) {
  const userId = user._id.toString();
  return jwt.sign(
    {
      sub: userId,
      typ: "mfa_pending",
      scope: "mfa_verify",
    },
    getMfaPendingSecret(),
    { expiresIn: MFA_PENDING_TTL_SECONDS }
  );
}

/**
 * Verifies an mfa_pending token. Rejects access tokens, expired tokens, or wrong scope.
 */
export function verifyMfaPendingToken(token) {
  if (!token || typeof token !== "string") {
    throw new Error("Missing or invalid mfaPendingToken");
  }
  const payload = jwt.verify(token, getMfaPendingSecret());
  if (payload.typ !== "mfa_pending" || payload.scope !== "mfa_verify" || !payload.sub) {
    throw new Error("Invalid MFA pending token scope");
  }
  return payload;
}

/**
 * Encrypts a plaintext TOTP secret for storage at rest.
 */
export function encryptMfaSecret(secretBase32) {
  if (!secretBase32) return null;
  return encryptField(secretBase32);
}

/**
 * Decrypts a stored TOTP secret. If a legacy plaintext secret is encountered,
 * returns the plaintext and marks `migrated = true` after encrypting `user.mfaSecret` in place.
 */
export async function resolveAndMigrateMfaSecret(user, { persist = true } = {}) {
  if (!user || !user.mfaSecret) return { secret: null, migrated: false };
  const raw = user.mfaSecret;
  if (isEncrypted(raw)) {
    return { secret: decryptField(raw), migrated: false };
  }
  // Legacy plaintext secret: migrate in place to AES-256-GCM encrypted form
  user.mfaSecret = encryptField(raw);
  if (persist && typeof user.save === "function") {
    await user.save();
  }
  return { secret: raw, migrated: true };
}

/**
 * Batch migration helper for existing users with plaintext mfaSecret values.
 */
export async function migratePlaintextMfaSecrets(UserModel) {
  const users = await UserModel.find({});
  let migratedCount = 0;
  const list = Array.isArray(users) ? users : [];
  for (const u of list) {
    if (u.mfaSecret && !isEncrypted(u.mfaSecret)) {
      u.mfaSecret = encryptField(u.mfaSecret);
      if (typeof u.save === "function") {
        await u.save();
      }
      migratedCount++;
    }
  }
  return { migratedCount };
}

/**
 * Verifies a user's TOTP token with:
 * - Per-account lockout check & enforcement
 * - Transparent encryption-at-rest migration
 * - RFC 6238 time-step replay prevention
 */
export async function verifyUserMfaCode(user, token, { nowMs = Date.now(), window = 1, timeStepSeconds = 30 } = {}) {
  const state = getState(user);

  if (state.lockedUntil && state.lockedUntil > nowMs) {
    return {
      ok: false,
      reason: "locked",
      status: 429,
      error: "Account temporarily locked due to repeated failed MFA attempts. Try again later.",
    };
  }

  const { secret } = await resolveAndMigrateMfaSecret(user, { persist: false });
  if (!secret) {
    return {
      ok: false,
      reason: "not_configured",
      status: 400,
      error: "MFA is not configured for this user.",
    };
  }

  const matchedStep = matchTOTPStep(secret, token, window, timeStepSeconds, nowMs);
  if (matchedStep === null) {
    state.failedAttempts += 1;
    user.mfaFailedAttempts = state.failedAttempts;
    if (state.failedAttempts >= MFA_MAX_FAILED_ATTEMPTS) {
      state.lockedUntil = nowMs + MFA_LOCKOUT_MS;
      user.mfaLockedUntil = new Date(state.lockedUntil);
      if (typeof user.save === "function") await user.save();
      return {
        ok: false,
        reason: "locked",
        status: 429,
        error: "Account temporarily locked due to repeated failed MFA attempts. Try again later.",
      };
    }
    if (typeof user.save === "function") await user.save();
    return {
      ok: false,
      reason: "invalid_code",
      status: 401,
      error: "Invalid two-factor authentication code.",
    };
  }

  if (state.lastUsedStep !== null && matchedStep <= state.lastUsedStep) {
    state.failedAttempts += 1;
    user.mfaFailedAttempts = state.failedAttempts;
    if (state.failedAttempts >= MFA_MAX_FAILED_ATTEMPTS) {
      state.lockedUntil = nowMs + MFA_LOCKOUT_MS;
      user.mfaLockedUntil = new Date(state.lockedUntil);
    }
    if (typeof user.save === "function") await user.save();
    return {
      ok: false,
      reason: "replay",
      status: 401,
      error: "Two-factor authentication code has already been used.",
    };
  }

  // Valid, unused code: record step and clear failed attempts
  state.lastUsedStep = matchedStep;
  state.failedAttempts = 0;
  state.lockedUntil = 0;
  user.mfaLastUsedStep = matchedStep;
  user.mfaFailedAttempts = 0;
  user.mfaLockedUntil = null;
  if (typeof user.save === "function") await user.save();

  return { ok: true, step: matchedStep };
}


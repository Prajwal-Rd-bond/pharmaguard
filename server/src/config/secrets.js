/**
 * Central secret resolution.
 *
 * Production (NODE_ENV === "production" or staging/unset): every secret MUST be configured explicitly.
 * Missing or placeholder values throw, and `assertProductionSecrets()` is called by
 * `start()` before any connection is opened, so the server refuses to start.
 *
 * Development / Test (NODE_ENV === "development" or "test"): clearly labelled, insecure
 * development fallbacks are used so local runs and the existing test-suite work without a .env file.
 * Any other NODE_ENV value (including unset, empty, "staging", or "production") requires explicit secrets.
 */

const DEV_JWT_FALLBACK = "smart-fhir-dev-secret-pharma-2026"; // dev/test only — never used in production
const DEV_PHI_FALLBACK = "pharmaguard-default-phi-secret-key-32b"; // dev/test only — never used in production
const DEV_MFA_FALLBACK = "smart-fhir-dev-secret-pharma-2026::mfa_pending::v1"; // dev/test only — never used in production
const DEV_SMART_CLIENT_FALLBACK = "pharmaguard-smart-client-secret-dev"; // dev/test only — never used in production

// Values copied from templates that must never be accepted in production.
const PLACEHOLDER_VALUES = new Set([
  "change-me-in-production",
  "changeme",
  "change-me",
  "secret",
  DEV_JWT_FALLBACK,
  DEV_PHI_FALLBACK,
  DEV_MFA_FALLBACK,
  DEV_SMART_CLIENT_FALLBACK,
]);

export function isDevOrTest(env = process.env.NODE_ENV) {
  if (typeof env !== "string") return false;
  const normalized = env.trim().toLowerCase();
  return normalized === "development" || normalized === "test";
}

export function isProduction(env = process.env.NODE_ENV) {
  return !isDevOrTest(env);
}

export function resolveEffectiveNodeEnv(env = process.env) {
  if (typeof env === "string") return env;
  if (env && typeof env.NODE_ENV === "string") return env.NODE_ENV;
  return undefined;
}

function isUsable(value) {
  return typeof value === "string" && value.trim().length >= 16 && !PLACEHOLDER_VALUES.has(value.trim());
}

export class MissingSecretError extends Error {
  constructor(name) {
    super(`${name} must be set to a non-placeholder value of at least 16 characters when NODE_ENV is not explicitly 'development' or 'test'.`);
    this.name = "MissingSecretError";
    this.secretName = name;
  }
}

export function getJwtSecret(env = process.env) {
  const value = env?.JWT_SECRET;
  const mode = resolveEffectiveNodeEnv(env);
  if (mode === undefined || !isDevOrTest(mode)) {
    if (!isUsable(value)) throw new MissingSecretError("JWT_SECRET");
    return value;
  }
  return value || DEV_JWT_FALLBACK;
}

/**
 * Key used only for short-lived "mfa_pending" tokens.
 * In production/staging, MFA_PENDING_SECRET MUST be set explicitly (no derived fallback).
 * In development/test, falls back to MFA_PENDING_SECRET, or derived from JWT_SECRET, or DEV_MFA_FALLBACK.
 */
export function getMfaPendingSecret(env = process.env) {
  const mode = resolveEffectiveNodeEnv(env);
  if (mode === undefined || !isDevOrTest(mode)) {
    if (!isUsable(env?.MFA_PENDING_SECRET)) throw new MissingSecretError("MFA_PENDING_SECRET");
    return env.MFA_PENDING_SECRET;
  }
  return env?.MFA_PENDING_SECRET || `${getJwtSecret(env)}::mfa_pending::v1`;
}

/**
 * Secret for AES-256-GCM field encryption (cryptoField.js).
 * Non-dev/test environments require PHI_ENCRYPTION_KEY explicitly.
 */
export function getPhiEncryptionSecret(env = process.env) {
  const mode = resolveEffectiveNodeEnv(env);
  if (mode === undefined || !isDevOrTest(mode)) {
    if (!isUsable(env?.PHI_ENCRYPTION_KEY)) throw new MissingSecretError("PHI_ENCRYPTION_KEY");
    return env.PHI_ENCRYPTION_KEY;
  }
  return env?.PHI_ENCRYPTION_KEY || env?.JWT_SECRET || DEV_PHI_FALLBACK;
}

/**
 * SMART-on-FHIR client secret for confidential client flows in sandbox.
 * Mandatory in production when SMART_SANDBOX_ENABLED is true.
 */
export function getSmartClientSecret(env = process.env) {
  const mode = resolveEffectiveNodeEnv(env);
  const sandboxEnabled = env?.SMART_SANDBOX_ENABLED === "true";
  if (mode === undefined || !isDevOrTest(mode)) {
    if (sandboxEnabled) {
      if (!isUsable(env?.SMART_CLIENT_SECRET)) throw new MissingSecretError("SMART_CLIENT_SECRET");
      return env.SMART_CLIENT_SECRET;
    }
    return env?.SMART_CLIENT_SECRET || undefined;
  }
  return env?.SMART_CLIENT_SECRET || DEV_SMART_CLIENT_FALLBACK;
}

/** Throws MissingSecretError if required secrets are absent when NODE_ENV is not development/test. */
export function assertProductionSecrets(env = process.env) {
  const mode = resolveEffectiveNodeEnv(env);
  if (mode !== undefined && isDevOrTest(mode)) return;
  if (!isUsable(env?.JWT_SECRET)) throw new MissingSecretError("JWT_SECRET");
  if (!isUsable(env?.PHI_ENCRYPTION_KEY)) throw new MissingSecretError("PHI_ENCRYPTION_KEY");
  if (!isUsable(env?.MFA_PENDING_SECRET)) throw new MissingSecretError("MFA_PENDING_SECRET");
  if (env?.SMART_SANDBOX_ENABLED === "true") {
    if (!isUsable(env?.SMART_CLIENT_SECRET)) throw new MissingSecretError("SMART_CLIENT_SECRET");
  }
}

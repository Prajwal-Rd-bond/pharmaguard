process.env.NODE_ENV = "test";
process.env.JWT_SECRET = "test-jwt-secret-pharmaguard-32chars";
process.env.PHI_ENCRYPTION_KEY = "test-phi-encryption-secret-32chars!!";

import { test, describe, before, after, beforeEach } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";
import jwt from "jsonwebtoken";

import app from "../src/app.js";
import User from "../src/models/User.js";
import AuditLog from "../src/models/AuditLog.js";
import { generateTOTP, generateTOTPSecret } from "../src/utils/totp.js";
import { isEncrypted, decryptField } from "../src/utils/cryptoField.js";
import {
  resetMfaMemoryState,
  migratePlaintextMfaSecrets,
  verifyUserMfaCode,
  MFA_PENDING_TTL_SECONDS,
} from "../src/utils/mfaService.js";
import {
  getJwtSecret,
  getPhiEncryptionSecret,
  getMfaPendingSecret,
  assertProductionSecrets,
  MissingSecretError,
} from "../src/config/secrets.js";
import { start } from "../src/index.js";
import { seedDatabase } from "../src/seed.js";
import { resolveAdminCredentials, seedAdmin } from "../scripts/seedAdmin.js";

describe("Phase 2 Step 1 — Security Fixes Verification", () => {
  let server;
  let baseUrl;
  const userStore = new Map();

  before(() => {
    User.findOne = async (query) => {
      if (query?.email) {
        for (const u of userStore.values()) {
          if (u.email.toLowerCase() === query.email.toLowerCase()) return u;
        }
      }
      return null;
    };

    User.findById = async (id) => {
      return userStore.get(id?.toString()) || null;
    };

    User.countDocuments = async (query) => {
      if (query?.role) {
        let count = 0;
        for (const u of userStore.values()) {
          if (u.role === query.role) count++;
        }
        return count;
      }
      return userStore.size;
    };

    User.find = (query) => {
      const arr = Array.from(userStore.values());
      const p = Promise.resolve(arr);
      p.sort = () => arr;
      return p;
    };

    User.create = async (doc) => {
      const u = new User(doc);
      userStore.set(u._id.toString(), u);
      return u;
    };

    User.prototype.save = async function () {
      userStore.set(this._id.toString(), this);
      return this;
    };

    AuditLog.create = async (doc) => doc;
  });

  before(async () => {
    server = http.createServer(app);
    await new Promise((resolve) => server.listen(0, resolve));
    const port = server.address().port;
    baseUrl = `http://127.0.0.1:${port}`;
  });

  after(async () => {
    if (server) {
      await new Promise((resolve) => server.close(resolve));
    }
  });

  beforeEach(() => {
    userStore.clear();
    resetMfaMemoryState();
  });

  async function createTestUser({
    name = "Dr. MFA Tester",
    email = "mfa@pharmaguard.local",
    password = "CorrectHorseBatteryStaple1!",
    role = "pharmacist",
    mfaEnabled = false,
    mfaSecret = null,
  } = {}) {
    const user = new User({ name, email, role, active: true, mfaEnabled, mfaSecret });
    await user.setPassword(password);
    userStore.set(user._id.toString(), user);
    return user;
  }

  test("1. MFA login returns short-lived mfaPendingToken (no userId), rejects userId+TOTP, and blocks mfa_pending token as Bearer access token", async () => {
    const { secret } = generateTOTPSecret("mfa@pharmaguard.local");
    const user = await createTestUser({ mfaEnabled: true, mfaSecret: secret });

    // Step 1a: Password login without TOTP returns mfaPendingToken and omits plaintext userId
    const loginRes = await fetch(`${baseUrl}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: "mfa@pharmaguard.local",
        password: "CorrectHorseBatteryStaple1!",
      }),
    });
    assert.equal(loginRes.status, 200);
    const loginBody = await loginRes.json();
    assert.equal(loginBody.mfaRequired, true);
    assert.equal(loginBody.userId, undefined, "login must NOT expose plaintext userId");
    assert.equal(typeof loginBody.mfaPendingToken, "string");
    assert.equal(loginBody.expiresIn, MFA_PENDING_TTL_SECONDS);

    // Inspect decoded claims of mfaPendingToken
    const decodedPending = jwt.decode(loginBody.mfaPendingToken);
    assert.equal(decodedPending.typ, "mfa_pending");
    assert.equal(decodedPending.scope, "mfa_verify");
    assert.ok(decodedPending.exp - decodedPending.iat <= 300, "TTL must be <= 5 minutes");

    // Step 1b: Attempting to use mfaPendingToken as an API access token must fail with 401
    const meWithPending = await fetch(`${baseUrl}/api/auth/me`, {
      headers: { Authorization: `Bearer ${loginBody.mfaPendingToken}` },
    });
    assert.equal(meWithPending.status, 401);

    // Also even if an mfa_pending payload were signed with the normal JWT_SECRET, requireAuth rejects typ !== "access"
    const forgedPending = jwt.sign(
      { sub: user._id.toString(), role: user.role, typ: "mfa_pending", scope: "mfa_verify" },
      getJwtSecret(),
      { expiresIn: "5m" }
    );
    const meWithForged = await fetch(`${baseUrl}/api/auth/me`, {
      headers: { Authorization: `Bearer ${forgedPending}` },
    });
    assert.equal(meWithForged.status, 401);

    // Step 1c: Attempting to verify-login with userId + valid TOTP (no mfaPendingToken) is rejected
    const validTotp = generateTOTP(secret, 30, Date.now());
    const userIdOnlyRes = await fetch(`${baseUrl}/api/auth/mfa/verify-login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        userId: user._id.toString(),
        token: validTotp,
      }),
    });
    assert.equal(userIdOnlyRes.status, 401);

    const loginUserIdOnlyRes = await fetch(`${baseUrl}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        userId: user._id.toString(),
        mfaToken: validTotp,
      }),
    });
    assert.equal(loginUserIdOnlyRes.status, 401);

    // Step 1d: Expired mfaPendingToken is rejected
    const expiredPending = jwt.sign(
      { sub: user._id.toString(), typ: "mfa_pending", scope: "mfa_verify" },
      getMfaPendingSecret(),
      { expiresIn: -10 }
    );
    const expiredRes = await fetch(`${baseUrl}/api/auth/mfa/verify-login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mfaPendingToken: expiredPending,
        token: validTotp,
      }),
    });
    assert.equal(expiredRes.status, 401);

    // Step 1e: Valid mfaPendingToken + valid TOTP succeeds and returns an access JWT
    const verifyRes = await fetch(`${baseUrl}/api/auth/mfa/verify-login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mfaPendingToken: loginBody.mfaPendingToken,
        token: validTotp,
      }),
    });
    assert.equal(verifyRes.status, 200);
    const verifyBody = await verifyRes.json();
    assert.ok(verifyBody.token);
    assert.equal(verifyBody.user.email, "mfa@pharmaguard.local");

    const meRes = await fetch(`${baseUrl}/api/auth/me`, {
      headers: { Authorization: `Bearer ${verifyBody.token}` },
    });
    assert.equal(meRes.status, 200);
  });

  test("2. TOTP replay rejection within time window and per-account lockout after repeated failures", async () => {
    const { secret } = generateTOTPSecret("replay@pharmaguard.local");
    const user = await createTestUser({
      email: "replay@pharmaguard.local",
      mfaEnabled: true,
      mfaSecret: secret,
    });

    const fixedNow = 1_700_000_000_000;
    const codeStep0 = generateTOTP(secret, 30, fixedNow);

    // First use at step 0 succeeds
    const first = await verifyUserMfaCode(user, codeStep0, { nowMs: fixedNow });
    assert.equal(first.ok, true);

    // Second use of the exact same code in the same window is rejected as a replay
    const replay = await verifyUserMfaCode(user, codeStep0, { nowMs: fixedNow + 5000 });
    assert.equal(replay.ok, false);
    assert.equal(replay.reason, "replay");
    assert.equal(replay.status, 401);
    assert.match(replay.error, /already been used/i);

    // A code from the NEXT 30s time step succeeds
    const nextStepMs = fixedNow + 30_000;
    const codeStep1 = generateTOTP(secret, 30, nextStepMs);
    const nextUse = await verifyUserMfaCode(user, codeStep1, { nowMs: nextStepMs });
    assert.equal(nextUse.ok, true);

    // Now trigger per-account lockout with 5 consecutive bad codes
    for (let i = 1; i <= 4; i++) {
      const bad = await verifyUserMfaCode(user, "000000", { nowMs: nextStepMs + 1000 });
      assert.equal(bad.ok, false);
      assert.equal(bad.reason, "invalid_code");
      assert.equal(bad.status, 401);
    }
    const fifthBad = await verifyUserMfaCode(user, "000000", { nowMs: nextStepMs + 2000 });
    assert.equal(fifthBad.ok, false);
    assert.equal(fifthBad.reason, "locked");
    assert.equal(fifthBad.status, 429);

    // While locked, even a fresh valid code for step+2 is rejected with 429
    const futureValidMs = nextStepMs + 60_000;
    const codeStep2 = generateTOTP(secret, 30, futureValidMs);
    const whileLocked = await verifyUserMfaCode(user, codeStep2, { nowMs: futureValidMs });
    assert.equal(whileLocked.ok, false);
    assert.equal(whileLocked.reason, "locked");
    assert.equal(whileLocked.status, 429);
  });

  test("3. TOTP secret is encrypted at rest via cryptoField, never returned after setup, and plaintext secrets migrate cleanly", async () => {
    const user = await createTestUser({
      email: "encrypt-mfa@pharmaguard.local",
      mfaEnabled: false,
      mfaSecret: null,
    });
    const accessToken = jwt.sign(
      { sub: user._id.toString(), role: user.role, typ: "access" },
      getJwtSecret(),
      { expiresIn: "1h" }
    );

    // Call /api/auth/mfa/setup
    const setupRes = await fetch(`${baseUrl}/api/auth/mfa/setup`, {
      method: "POST",
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    assert.equal(setupRes.status, 200);
    const setupBody = await setupRes.json();
    assert.ok(setupBody.secret);

    // Stored secret on User record must be encrypted (enc:v1:...)
    const storedUser = userStore.get(user._id.toString());
    assert.notEqual(storedUser.mfaSecret, setupBody.secret);
    assert.equal(isEncrypted(storedUser.mfaSecret), true);
    assert.equal(decryptField(storedUser.mfaSecret), setupBody.secret);

    // Activate MFA with a valid code
    const code = generateTOTP(setupBody.secret, 30, Date.now());
    const activateRes = await fetch(`${baseUrl}/api/auth/mfa/verify`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${accessToken}`,
      },
      body: JSON.stringify({ token: code }),
    });
    assert.equal(activateRes.status, 200);
    const activateBody = await activateRes.json();
    assert.equal(activateBody.user.mfaSecret, undefined);
    assert.equal(JSON.stringify(activateBody).includes(setupBody.secret), false);

    // Legacy plaintext migration test
    const { secret: legacyPlain } = generateTOTPSecret("legacy@pharmaguard.local");
    const legacyUser = await createTestUser({
      email: "legacy@pharmaguard.local",
      mfaEnabled: true,
      mfaSecret: legacyPlain,
    });
    assert.equal(isEncrypted(legacyUser.mfaSecret), false);

    const migResult = await migratePlaintextMfaSecrets(User);
    assert.equal(migResult.migratedCount, 1);
    assert.equal(isEncrypted(legacyUser.mfaSecret), true);
    assert.equal(decryptField(legacyUser.mfaSecret), legacyPlain);
  });

  test("4. Seed gating: production refuses to seed, seed upserts preserve existing password/role, seedAdmin supports env/prompt, Login.jsx gates demo buttons", async () => {
    // 4a. seedDatabase refuses to run in production
    await assert.rejects(
      () => seedDatabase({ env: "production", skipConnect: true }),
      /Refusing to run demo database seeder in production/i
    );
    assert.equal(userStore.size, 0, "Production seed check must create zero users");

    // 4b. Seed upsert does not overwrite existing user's passwordHash or role
    const customAdmin = await createTestUser({
      name: "Custom Admin",
      email: "admin@pharmaguard.org",
      password: "MyCustomStrongPassword99!",
      role: "pharmacist", // intentionally non-default role to verify role is not overwritten
      mfaEnabled: true,
    });
    const originalHash = customAdmin.passwordHash;

    // Stub Report.countDocuments so seedDatabase only runs user loop
    const Report = (await import("../src/models/Report.js")).default;
    const origReportCount = Report.countDocuments;
    Report.countDocuments = async () => 5;
    try {
      await seedDatabase({ env: "development", skipConnect: true });
    } finally {
      Report.countDocuments = origReportCount;
    }

    const afterSeed = userStore.get(customAdmin._id.toString());
    assert.equal(afterSeed.passwordHash, originalHash, "Seed must NOT overwrite existing passwordHash");
    assert.equal(afterSeed.role, "pharmacist", "Seed must NOT overwrite existing role");
    assert.equal(afterSeed.mfaEnabled, true, "Seed must NOT reset mfaEnabled");

    // 4c. seedAdmin resolves credentials from prompt when env is unset, and does not overwrite existing user
    const prompted = await resolveAdminCredentials({
      env: {},
      allowPrompt: true,
      promptFn: async (q) => (q.toLowerCase().includes("email") ? "prompt-admin@pharmaguard.org" : "PromptSecretPass123!"),
    });
    assert.equal(prompted.email, "prompt-admin@pharmaguard.org");
    assert.equal(prompted.password, "PromptSecretPass123!");

    const conflictRes = await seedAdmin({
      env: { ADMIN_EMAIL: "admin@pharmaguard.org", ADMIN_PASSWORD: "NewPassword123!" },
      allowPrompt: false,
      connectDB: async () => {},
      disconnectDB: async () => {},
    });
    assert.equal(conflictRes.ok, false);
    assert.equal(conflictRes.reason, "role_conflict");
    const promoteRes = await seedAdmin({
      env: { ADMIN_EMAIL: "admin@pharmaguard.org", ADMIN_PASSWORD: "NewPassword123!" },
      argv: ["--force-role"],
      allowPrompt: false,
      connectDB: async () => {},
      disconnectDB: async () => {},
    });
    assert.equal(promoteRes.ok, true);
    assert.equal(promoteRes.reason, "promoted");
    assert.equal(userStore.get(customAdmin._id.toString()).role, "admin");
    assert.equal(userStore.get(customAdmin._id.toString()).passwordHash, originalHash);

    // 4d. Client Login.jsx gates Quick Demo Access behind import.meta.env.DEV
    const serverDir = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
    const loginJsxPath = path.resolve(serverDir, "..", "client", "src", "pages", "Login.jsx");
    const loginJsx = fs.readFileSync(loginJsxPath, "utf8");
    assert.match(loginJsx, /import\.meta\.env\.DEV\s*&&/);

    // 4e. .env.example documents AUTO_SEED
    const rootEnvExample = fs.readFileSync(path.resolve(serverDir, "..", ".env.example"), "utf8");
    assert.match(rootEnvExample, /^AUTO_SEED=/m);

    // 4f. Demo credentials banner printed only when NODE_ENV === "development", not for "test" or "production"
    const capturedLogs = [];
    const origLog = console.log;
    const origCount = Report.countDocuments;
    Report.countDocuments = async () => 5;
    console.log = (...args) => capturedLogs.push(args.join(" "));
    try {
      // For "production" (refuses seedDatabase)
      await assert.rejects(
        () => seedDatabase({ env: "production", skipConnect: true }),
        /Refusing to run demo database seeder in production/i
      );
      assert.equal(
        capturedLogs.some((l) => l.includes("PharmaGuard Demo User Credentials Ready")),
        false,
        "Credentials banner must NOT be printed for production"
      );

      // For "test"
      capturedLogs.length = 0;
      const prevEnv = process.env.NODE_ENV;
      process.env.NODE_ENV = "test";
      try {
        await seedDatabase({ env: "test", skipConnect: true });
      } finally {
        process.env.NODE_ENV = prevEnv;
      }
      assert.equal(
        capturedLogs.some((l) => l.includes("PharmaGuard Demo User Credentials Ready")),
        false,
        "Credentials banner must NOT be printed for test"
      );

      // For "development"
      capturedLogs.length = 0;
      const prevEnvDev = process.env.NODE_ENV;
      process.env.NODE_ENV = "development";
      try {
        await seedDatabase({ env: "development", skipConnect: true });
      } finally {
        process.env.NODE_ENV = prevEnvDev;
      }
      assert.equal(
        capturedLogs.some((l) => l.includes("PharmaGuard Demo User Credentials Ready")),
        true,
        "Credentials banner MUST be printed for development"
      );
    } finally {
      console.log = origLog;
      Report.countDocuments = origCount;
    }
  });

  test("5. Importing app.js with Mongo and Redis unavailable opens no connections, and tracingMiddleware is first", async () => {
    const serverDir = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
    const appPath = path.resolve(serverDir, "src", "app.js");
    const appUrl = pathToFileURL(appPath).href;

    // Check source import order in app.js: tracingMiddleware is imported on line 1
    const appSrc = fs.readFileSync(appPath, "utf8");
    const firstImportLine = appSrc
      .split(/\r?\n/)
      .find((l) => l.trim().startsWith("import "));
    assert.match(firstImportLine, /tracingMiddleware/, "tracingMiddleware must be the first import in app.js");

    // Spawn a subprocess with unreachable Mongo & Redis and DISABLE_REDIS unset;
    // hook net.Socket.prototype.connect to fail if any TCP connection is attempted on import!
    const script = `
      import net from "node:net";
      const attempts = [];
      const origConnect = net.Socket.prototype.connect;
      net.Socket.prototype.connect = function(...args) {
        attempts.push(args[0]);
        return origConnect.apply(this, args);
      };
      await import(${JSON.stringify(appUrl)});
      const mongoose = (await import("mongoose")).default;
      if (mongoose.connection.readyState !== 0) {
        console.error("MONGO_CONNECTED_ON_IMPORT");
        process.exit(2);
      }
      if (attempts.length > 0) {
        console.error("SOCKET_ATTEMPTS_ON_IMPORT:" + JSON.stringify(attempts));
        process.exit(3);
      }
      console.log("APP_IMPORT_ISOLATED_OK");
    `;

    const child = spawnSync(process.execPath, ["--input-type=module", "-e", script], {
      cwd: serverDir,
      timeout: 10000,
      encoding: "utf8",
      env: {
        NODE_ENV: "test",
        MONGO_URI: "mongodb://127.0.0.1:1/unreachable",
        REDIS_URL: "redis://127.0.0.1:1",
        PATH: process.env.PATH,
        SYSTEMROOT: process.env.SYSTEMROOT,
      },
    });

    assert.equal(child.status, 0, `Subprocess failed: stdout=${child.stdout} stderr=${child.stderr}`);
    assert.match(child.stdout, /APP_IMPORT_ISOLATED_OK/);
  });

  test("6. Production startup refuses missing or fallback secrets, enforces NODE_ENV strictly without NODE_TEST_CONTEXT bypass, and blocks SMART sandbox token minting", async () => {
    // Criterion A: In development or test, development fallbacks are accepted
    assert.doesNotThrow(() => assertProductionSecrets({ NODE_ENV: "development", JWT_SECRET: "", PHI_ENCRYPTION_KEY: "" }));
    assert.doesNotThrow(() => assertProductionSecrets({ NODE_ENV: "test", JWT_SECRET: "", PHI_ENCRYPTION_KEY: "" }));

    // Criterion B: NODE_TEST_CONTEXT set with NODE_ENV unset or "production" MUST refuse to start without real secrets
    const origNodeEnv = process.env.NODE_ENV;
    const origJwt = process.env.JWT_SECRET;
    const origTestCtx = process.env.NODE_TEST_CONTEXT;
    try {
      delete process.env.NODE_ENV;
      delete process.env.JWT_SECRET;
      process.env.NODE_TEST_CONTEXT = "1";

      // With NODE_ENV unset, NODE_TEST_CONTEXT must NOT grant test-mode exemption
      assert.throws(() => assertProductionSecrets(process.env), MissingSecretError);
      assert.throws(() => getJwtSecret(process.env), MissingSecretError);

      // With NODE_ENV=production, NODE_TEST_CONTEXT must NOT grant test-mode exemption
      process.env.NODE_ENV = "production";
      assert.throws(() => assertProductionSecrets(process.env), MissingSecretError);
      assert.throws(() => getJwtSecret(process.env), MissingSecretError);
    } finally {
      process.env.NODE_ENV = origNodeEnv;
      process.env.JWT_SECRET = origJwt;
      if (origTestCtx === undefined) {
        delete process.env.NODE_TEST_CONTEXT;
      } else {
        process.env.NODE_TEST_CONTEXT = origTestCtx;
      }
    }

    // Criterion C: When NODE_ENV is unset, empty, or staging, dev fallbacks are REFUSED
    assert.throws(() => assertProductionSecrets({ NODE_ENV: "", JWT_SECRET: "smart-fhir-dev-secret-pharma-2026", PHI_ENCRYPTION_KEY: "" }), MissingSecretError);
    assert.throws(() => assertProductionSecrets({}), MissingSecretError);
    assert.throws(() => assertProductionSecrets({ NODE_ENV: "staging" }), MissingSecretError);

    // Criterion D: Full production secrets list validation (JWT_SECRET, PHI_ENCRYPTION_KEY, MFA_PENDING_SECRET, SMART_CLIENT_SECRET)
    const validJwt = "valid-production-jwt-secret-32chars!!";
    const validPhi = "valid-production-phi-encryption-key-32b";
    const validMfa = "valid-production-mfa-pending-secret-32b";
    const validSmart = "valid-production-smart-client-secret-32b";

    // Missing JWT_SECRET
    assert.throws(
      () => assertProductionSecrets({ NODE_ENV: "production", PHI_ENCRYPTION_KEY: validPhi, MFA_PENDING_SECRET: validMfa }),
      (err) => err instanceof MissingSecretError && err.secretName === "JWT_SECRET"
    );
    // Placeholder JWT_SECRET
    assert.throws(
      () => assertProductionSecrets({ NODE_ENV: "production", JWT_SECRET: "change-me-in-production", PHI_ENCRYPTION_KEY: validPhi, MFA_PENDING_SECRET: validMfa }),
      (err) => err instanceof MissingSecretError && err.secretName === "JWT_SECRET"
    );

    // Missing PHI_ENCRYPTION_KEY
    assert.throws(
      () => assertProductionSecrets({ NODE_ENV: "production", JWT_SECRET: validJwt, MFA_PENDING_SECRET: validMfa }),
      (err) => err instanceof MissingSecretError && err.secretName === "PHI_ENCRYPTION_KEY"
    );
    // Placeholder PHI_ENCRYPTION_KEY
    assert.throws(
      () => assertProductionSecrets({ NODE_ENV: "production", JWT_SECRET: validJwt, PHI_ENCRYPTION_KEY: "pharmaguard-default-phi-secret-key-32b", MFA_PENDING_SECRET: validMfa }),
      (err) => err instanceof MissingSecretError && err.secretName === "PHI_ENCRYPTION_KEY"
    );

    // Missing MFA_PENDING_SECRET (proves no derived fallback in production)
    assert.throws(
      () => assertProductionSecrets({ NODE_ENV: "production", JWT_SECRET: validJwt, PHI_ENCRYPTION_KEY: validPhi }),
      (err) => err instanceof MissingSecretError && err.secretName === "MFA_PENDING_SECRET"
    );
    assert.throws(
      () => getMfaPendingSecret({ NODE_ENV: "production", JWT_SECRET: validJwt, PHI_ENCRYPTION_KEY: validPhi }),
      (err) => err instanceof MissingSecretError && err.secretName === "MFA_PENDING_SECRET"
    );

    // When SMART_SANDBOX_ENABLED=true in production, SMART_CLIENT_SECRET is strictly required
    assert.throws(
      () => assertProductionSecrets({ NODE_ENV: "production", JWT_SECRET: validJwt, PHI_ENCRYPTION_KEY: validPhi, MFA_PENDING_SECRET: validMfa, SMART_SANDBOX_ENABLED: "true" }),
      (err) => err instanceof MissingSecretError && err.secretName === "SMART_CLIENT_SECRET"
    );
    // When SMART_SANDBOX_ENABLED is false or unset, SMART_CLIENT_SECRET is NOT required
    assert.doesNotThrow(
      () => assertProductionSecrets({ NODE_ENV: "production", JWT_SECRET: validJwt, PHI_ENCRYPTION_KEY: validPhi, MFA_PENDING_SECRET: validMfa, SMART_SANDBOX_ENABLED: "false" })
    );
    // All 4 valid non-placeholder secrets succeed with SMART sandbox enabled
    assert.doesNotThrow(
      () => assertProductionSecrets({ NODE_ENV: "production", JWT_SECRET: validJwt, PHI_ENCRYPTION_KEY: validPhi, MFA_PENDING_SECRET: validMfa, SMART_SANDBOX_ENABLED: "true", SMART_CLIENT_SECRET: validSmart })
    );

    // Criterion E: assertProductionSecrets rejects the exact placeholder strings in root .env.example and server/.env.example
    const placeholders = [
      "change-me-in-production",
      "replace_with_a_secure_random_64_character_hex_secret_in_production",
      "change-me-in-production-32-byte-secret",
      "replace_with_a_secure_32_byte_aes_key_for_phi_encryption",
    ];

    for (const ph of placeholders) {
      assert.throws(
        () => assertProductionSecrets({ NODE_ENV: "production", JWT_SECRET: ph, PHI_ENCRYPTION_KEY: validPhi, MFA_PENDING_SECRET: validMfa }),
        (err) => err instanceof MissingSecretError && err.secretName === "JWT_SECRET",
        `Must reject exact placeholder '${ph}' for JWT_SECRET`
      );
      assert.throws(
        () => assertProductionSecrets({ NODE_ENV: "production", JWT_SECRET: validJwt, PHI_ENCRYPTION_KEY: ph, MFA_PENDING_SECRET: validMfa }),
        (err) => err instanceof MissingSecretError && err.secretName === "PHI_ENCRYPTION_KEY",
        `Must reject exact placeholder '${ph}' for PHI_ENCRYPTION_KEY`
      );
      assert.throws(
        () => assertProductionSecrets({ NODE_ENV: "production", JWT_SECRET: validJwt, PHI_ENCRYPTION_KEY: validPhi, MFA_PENDING_SECRET: ph }),
        (err) => err instanceof MissingSecretError && err.secretName === "MFA_PENDING_SECRET",
        `Must reject exact placeholder '${ph}' for MFA_PENDING_SECRET`
      );
    }

    await assert.rejects(
      () =>
        start({
          env: "production",
          enforceSecrets: true,
          secrets: { JWT_SECRET: "", PHI_ENCRYPTION_KEY: "" },
          connectDB: async () => {},
          app: { listen: () => {} },
        }),
      MissingSecretError
    );

    // Verify SMART sandbox is blocked when NODE_ENV=production and SMART_SANDBOX_ENABLED is unset
    const prevEnv = process.env.NODE_ENV;
    const prevSandbox = process.env.SMART_SANDBOX_ENABLED;
    process.env.NODE_ENV = "production";
    delete process.env.SMART_SANDBOX_ENABLED;
    try {
      const simRes = await fetch(`${baseUrl}/api/fhir/launch/simulate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ehrProvider: "Epic" }),
      });
      assert.equal(simRes.status, 403);
    } finally {
      process.env.NODE_ENV = prevEnv;
      if (prevSandbox !== undefined) process.env.SMART_SANDBOX_ENABLED = prevSandbox;
    }
  });
});


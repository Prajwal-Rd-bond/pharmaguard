process.env.NODE_ENV = "test";
process.env.JWT_SECRET = "test-jwt-secret-pharmaguard-32chars";

import { test, describe, before, after, beforeEach } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import jwt from "jsonwebtoken";

import app from "../src/app.js";
import User from "../src/models/User.js";
import AuditLog from "../src/models/AuditLog.js";

describe("Phase 1 Remediation — Auth & Registration Hardening", () => {
  let server;
  let baseUrl;
  const userStore = new Map();

  // Stub Mongoose database operations with an in-memory test store
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

    User.find = () => ({
      sort: () => Array.from(userStore.values()),
    });

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
  });

  // Helper to generate test JWTs
  function createTestToken(user) {
    return jwt.sign({ sub: user._id.toString(), role: user.role }, process.env.JWT_SECRET, {
      expiresIn: "1h",
    });
  }

  // Helper to seed a user in the store
  async function seedTestUser({ name, email, password, role = "doctor" }) {
    const user = new User({ name, email, role, active: true });
    await user.setPassword(password);
    userStore.set(user._id.toString(), user);
    return user;
  }

  test("1. POST /api/auth/register returns 403 Forbidden for public registration", async () => {
    const res = await fetch(`${baseUrl}/api/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: "Self-Registered User",
        email: "user@example.com",
        password: "Password123!",
      }),
    });

    assert.equal(res.status, 403);
    const body = await res.json();
    assert.match(body.error, /Public registration is disabled/i);
    assert.equal(userStore.size, 0);
  });

  test("2. POST /api/auth/register with attempted role escalation returns 403 Forbidden", async () => {
    const res = await fetch(`${baseUrl}/api/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: "Attacker",
        email: "attacker@example.com",
        password: "AttackerPass123!",
        role: "admin",
      }),
    });

    assert.equal(res.status, 403);
    const body = await res.json();
    assert.match(body.error, /Public registration is disabled/i);
    assert.equal(userStore.size, 0);
  });

  test("3. POST /api/users without authentication returns 401 Unauthorized", async () => {
    const res = await fetch(`${baseUrl}/api/users`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: "New Pharmacist",
        email: "pharmacist@pharmaguard.local",
        password: "SecurePassword123!",
        role: "pharmacist",
      }),
    });

    assert.equal(res.status, 401);
    const body = await res.json();
    assert.match(body.error, /Missing bearer token/i);
  });

  test("4. POST /api/users with non-admin token returns 403 Forbidden", async () => {
    const doctor = await seedTestUser({
      name: "Dr. Alice",
      email: "alice@hospital.local",
      password: "Password123!",
      role: "doctor",
    });
    const doctorToken = createTestToken(doctor);

    const res = await fetch(`${baseUrl}/api/users`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${doctorToken}`,
      },
      body: JSON.stringify({
        name: "Escalated User",
        email: "escalated@pharmaguard.local",
        password: "Password123!",
        role: "admin",
      }),
    });

    assert.equal(res.status, 403);
    const body = await res.json();
    assert.match(body.error, /not permitted/i);
  });

  test("5. POST /api/users with admin token successfully provisions user", async () => {
    const admin = await seedTestUser({
      name: "Admin User",
      email: "admin@pharmaguard.local",
      password: "AdminPassword123!",
      role: "admin",
    });
    const adminToken = createTestToken(admin);

    const res = await fetch(`${baseUrl}/api/users`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${adminToken}`,
      },
      body: JSON.stringify({
        name: "Bob Pharmacist",
        email: "bob@pharmaguard.local",
        password: "BobPassword123!",
        role: "pharmacist",
      }),
    });

    assert.equal(res.status, 201);
    const body = await res.json();
    assert.equal(body.user.name, "Bob Pharmacist");
    assert.equal(body.user.email, "bob@pharmaguard.local");
    assert.equal(body.user.role, "pharmacist");
    assert.equal(body.user.active, true);
    assert.equal(body.user.passwordHash, undefined);
    assert.equal(body.user.password, undefined);

    // Verify user was stored with hashed password
    const created = Array.from(userStore.values()).find((u) => u.email === "bob@pharmaguard.local");
    assert.ok(created);
    assert.notEqual(created.passwordHash, "BobPassword123!");
    assert.ok(await created.checkPassword("BobPassword123!"));
  });

  test("6. POST /api/users validates minimum password length (>= 8 characters)", async () => {
    const admin = await seedTestUser({
      name: "Admin User",
      email: "admin@pharmaguard.local",
      password: "AdminPassword123!",
      role: "admin",
    });
    const adminToken = createTestToken(admin);

    const res = await fetch(`${baseUrl}/api/users`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${adminToken}`,
      },
      body: JSON.stringify({
        name: "Short Pass",
        email: "short@pharmaguard.local",
        password: "short",
        role: "researcher",
      }),
    });

    assert.equal(res.status, 400);
    const body = await res.json();
    assert.match(body.error, /password must be at least 8 characters/i);
  });

  test("7. POST /api/auth/login authenticates valid user and rejects invalid password", async () => {
    await seedTestUser({
      name: "Carol Researcher",
      email: "carol@pharmaguard.local",
      password: "CarolPassword123!",
      role: "researcher",
    });

    // Valid login
    const validRes = await fetch(`${baseUrl}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: "carol@pharmaguard.local",
        password: "CarolPassword123!",
      }),
    });

    assert.equal(validRes.status, 200);
    const validBody = await validRes.json();
    assert.ok(validBody.token);
    assert.equal(validBody.user.email, "carol@pharmaguard.local");
    assert.equal(validBody.user.role, "researcher");

    // Invalid login
    const invalidRes = await fetch(`${baseUrl}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: "carol@pharmaguard.local",
        password: "WrongPassword!",
      }),
    });

    assert.equal(invalidRes.status, 401);
    const invalidBody = await invalidRes.json();
    assert.match(invalidBody.error, /Invalid credentials/i);
  });

  test("8. GET /api/auth/me returns current user profile with valid JWT", async () => {
    const user = await seedTestUser({
      name: "Dave Doctor",
      email: "dave@hospital.local",
      password: "DavePassword123!",
      role: "doctor",
    });
    const token = createTestToken(user);

    const res = await fetch(`${baseUrl}/api/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    assert.equal(res.status, 200);
    const body = await res.json();
    assert.equal(body.user.name, "Dave Doctor");
    assert.equal(body.user.email, "dave@hospital.local");
    assert.equal(body.user.role, "doctor");
    assert.equal(body.user.passwordHash, undefined);
  });

  test("9. shouldAutoSeed enables seeding ONLY when NODE_ENV is explicitly development/test AND AUTO_SEED=true", async () => {
    const { shouldAutoSeed } = await import("../src/index.js");

    // Positive combinations
    assert.equal(shouldAutoSeed("development", "true"), true);
    assert.equal(shouldAutoSeed("test", "true"), true);
    assert.equal(shouldAutoSeed("DEVELOPMENT", "true"), true);
    assert.equal(shouldAutoSeed("TEST", "true"), true);
  });

  test("10. shouldAutoSeed disables seeding for production, missing/empty, unrecognized envs, or missing AUTO_SEED", async () => {
    const { shouldAutoSeed } = await import("../src/index.js");

    // Negative combinations: production
    assert.equal(shouldAutoSeed("production", "true"), false);
    assert.equal(shouldAutoSeed("prod", "true"), false);

    // Negative combinations: missing or empty NODE_ENV
    assert.equal(shouldAutoSeed(undefined, "true"), false);
    assert.equal(shouldAutoSeed(null, "true"), false);
    assert.equal(shouldAutoSeed("", "true"), false);
    assert.equal(shouldAutoSeed("   ", "true"), false);

    // Negative combinations: unrecognized environments
    assert.equal(shouldAutoSeed("staging", "true"), false);
    assert.equal(shouldAutoSeed("preview", "true"), false);
    assert.equal(shouldAutoSeed("local", "true"), false);

    // Negative combinations: AUTO_SEED missing, false, or malformed
    assert.equal(shouldAutoSeed("development", undefined), false);
    assert.equal(shouldAutoSeed("development", "false"), false);
    assert.equal(shouldAutoSeed("development", "1"), false);
    assert.equal(shouldAutoSeed("test", undefined), false);
    assert.equal(shouldAutoSeed("test", "0"), false);
  });
});



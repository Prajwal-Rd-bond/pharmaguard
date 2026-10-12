import { describe, it } from "node:test";
import assert from "node:assert";
import crypto from "crypto";

describe("Audit Hash-Chaining & Integrity", () => {
  it("computes valid SHA-256 chain where each record links to prevHash", () => {
    const chain = [];
    let prevHash = "GENESIS";

    const entries = [
      { actor: "user1", action: "user.register", details: { role: "admin" } },
      { actor: "user1", action: "report.submit", details: { source: "pasted_text" } },
      { actor: "ai", action: "pipeline.complete", details: { summary: "Anaphylaxis to amoxicillin" } },
      { actor: "pharmacist1", action: "review.approve", details: { comment: "Verified" } },
    ];

    for (const entry of entries) {
      const payload = [
        prevHash,
        entry.actor,
        "user",
        entry.action,
        "report_123",
        "pipeline_abc",
        JSON.stringify(entry.details),
      ].join("|");

      const hash = crypto.createHash("sha256").update(payload).digest("hex");
      chain.push({ ...entry, prevHash, hash });
      prevHash = hash;
    }

    assert.strictEqual(chain.length, 4);
    assert.strictEqual(chain[0].prevHash, "GENESIS");
    assert.strictEqual(chain[1].prevHash, chain[0].hash);
    assert.strictEqual(chain[2].prevHash, chain[1].hash);
    assert.strictEqual(chain[3].prevHash, chain[2].hash);

    // Tampering test: simulate modifying a historical record's details
    chain[1].details.source = "tampered_source";
    const tamperedPayload = [
      chain[1].prevHash,
      chain[1].actor,
      "user",
      chain[1].action,
      "report_123",
      "pipeline_abc",
      JSON.stringify(chain[1].details),
    ].join("|");
    const recomputedTamperedHash = crypto.createHash("sha256").update(tamperedPayload).digest("hex");

    assert.notStrictEqual(recomputedTamperedHash, chain[1].hash, "Tampering must break the hash signature");
  });
});

describe("Report State Machine Transitions", () => {
  const validTransitions = {
    submitted: ["processing"],
    processing: ["pending_review", "submitted"],
    pending_review: ["approved", "rejected", "needs_more_info"],
    needs_more_info: ["pending_review", "approved", "rejected"],
    approved: [],
    rejected: [],
  };

  function canTransition(current, next) {
    return (validTransitions[current] || []).includes(next);
  }

  it("prevents direct approval of submitted reports without running pipeline", () => {
    assert.strictEqual(canTransition("submitted", "approved"), false);
  });

  it("permits approval from pending_review", () => {
    assert.strictEqual(canTransition("pending_review", "approved"), true);
  });

  it("prevents transitions once approved", () => {
    assert.strictEqual(canTransition("approved", "pending_review"), false);
    assert.strictEqual(canTransition("approved", "rejected"), false);
  });

  it("handles needs_more_info transition", () => {
    assert.strictEqual(canTransition("pending_review", "needs_more_info"), true);
  });
});

describe("Doctor Report Isolation", () => {
  it("restricts doctor to only self-submitted reports", () => {
    const doctorA = { id: "doc_A", role: "doctor" };
    const doctorB = { id: "doc_B", role: "doctor" };
    const pharmacist = { id: "pharm_1", role: "pharmacist" };

    const report = { id: "rep_1", submittedBy: "doc_A" };

    function canAccess(user, rep) {
      if (user.role === "doctor") {
        return rep.submittedBy === user.id;
      }
      return ["pharmacist", "admin", "researcher"].includes(user.role);
    }

    assert.strictEqual(canAccess(doctorA, report), true);
    assert.strictEqual(canAccess(doctorB, report), false);
    assert.strictEqual(canAccess(pharmacist, report), true);
  });
});

describe("Rate Limiter Middleware", () => {
  it("allows requests under the limit and blocks excess requests", () => {
    const windowMs = 1000;
    const max = 3;
    const store = new Map();

    function checkLimit(ip) {
      const now = Date.now();
      const timestamps = (store.get(ip) || []).filter((t) => now - t < windowMs);
      if (timestamps.length >= max) {
        return { allowed: false, remaining: 0 };
      }
      timestamps.push(now);
      store.set(ip, timestamps);
      return { allowed: true, remaining: max - timestamps.length };
    }

    assert.strictEqual(checkLimit("192.168.1.1").allowed, true);
    assert.strictEqual(checkLimit("192.168.1.1").allowed, true);
    assert.strictEqual(checkLimit("192.168.1.1").allowed, true);
    assert.strictEqual(checkLimit("192.168.1.1").allowed, false, "4th request within window must be blocked");
    assert.strictEqual(checkLimit("10.0.0.1").allowed, true, "Different IP should not be blocked");
  });
});

describe("Asynchronous Job Queue State Tracking", () => {
  it("initializes job in queued state and advances to completed", () => {
    const jobs = new Map();
    const jobId = "job_test_123";

    jobs.set(jobId, { status: "queued", reportId: "rep_456" });
    assert.strictEqual(jobs.get(jobId).status, "queued");

    jobs.set(jobId, { status: "processing", step: "running_ai_models", reportId: "rep_456" });
    assert.strictEqual(jobs.get(jobId).status, "processing");

    jobs.set(jobId, { status: "completed", reportId: "rep_456", summary: "Clinical narrative synthesized" });
    assert.strictEqual(jobs.get(jobId).status, "completed");
    assert.ok(jobs.get(jobId).summary.includes("Clinical"));
  });
});


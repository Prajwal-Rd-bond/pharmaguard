import crypto from "crypto";
import AuditLog from "../models/AuditLog.js";

let writeLock = Promise.resolve();

// Module 12 — call this from controllers after any state-changing action.
// Never exposed for update/delete: append-only with cryptographic hash chaining and sequence serialization.
export async function logAction({ actor, actorType = "user", action, report, pipelineRunId, modelVersion, details }) {
  return new Promise((resolve, reject) => {
    writeLock = writeLock
      .catch(() => {})
      .then(async () => {
        try {
          const entry = await AuditLog.create({ actor, actorType, action, report, pipelineRunId, modelVersion, details });
          resolve(entry);
        } catch (err) {
          reject(err);
        }
      });
  });
}

export const recordAuditLog = logAction;

// Verifies that the audit log chain has not been tampered with or truncated
export async function verifyAuditChain() {
  const logs = await AuditLog.find().sort({ sequenceNumber: 1, createdAt: 1 });
  let expectedPrevHash = "GENESIS";

  for (let i = 0; i < logs.length; i++) {
    const entry = logs[i];
    if (entry.prevHash !== expectedPrevHash) {
      return {
        valid: false,
        brokenAtIndex: i,
        entryId: entry._id,
        reason: `Previous hash mismatch: expected '${expectedPrevHash}', found '${entry.prevHash}'`,
      };
    }

    const payload = [
      entry.prevHash,
      entry.actor?.toString() || "",
      entry.actorType,
      entry.action,
      entry.report?.toString() || "",
      entry.pipelineRunId || "",
      JSON.stringify(entry.details || {}),
    ].join("|");

    const recomputedHash = crypto.createHash("sha256").update(payload).digest("hex");
    if (entry.hash !== recomputedHash) {
      return {
        valid: false,
        brokenAtIndex: i,
        entryId: entry._id,
        reason: `Hash signature mismatch on record ${entry._id}`,
      };
    }

    expectedPrevHash = entry.hash;
  }

  return { valid: true, totalEntries: logs.length };
}

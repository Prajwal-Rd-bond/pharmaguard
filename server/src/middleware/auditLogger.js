import AuditLog from "../models/AuditLog.js";

// Module 12 — call this from controllers after any state-changing action.
// Never exposed for update/delete: append-only.
export async function logAction({ actor, actorType = "user", action, report, pipelineRunId, modelVersion, details }) {
  await AuditLog.create({ actor, actorType, action, report, pipelineRunId, modelVersion, details });
}

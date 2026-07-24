import mongoose from "mongoose";

// Module 12 — append-only audit trail.
const auditLogSchema = new mongoose.Schema(
  {
    actor: { type: mongoose.Schema.Types.ObjectId, ref: "User" }, // null for system/AI-originated entries
    actorType: { type: String, enum: ["user", "ai_pipeline", "system"], required: true },
    action: { type: String, required: true }, // e.g. "report.submit", "pipeline.run", "review.approve"
    report: { type: mongoose.Schema.Types.ObjectId, ref: "Report" },
    pipelineRunId: String,
    modelVersion: String,
    details: { type: mongoose.Schema.Types.Mixed },
  },
  { timestamps: true, capped: false }
);

// Append-only by convention: no update/delete routes are exposed for this collection (see routes/auditRoutes.js).
export default mongoose.model("AuditLog", auditLogSchema);

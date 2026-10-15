import mongoose from "mongoose";
import crypto from "crypto";

// Module 12 — Cryptographically hash-chained, tamper-evident, append-only audit trail.
const auditLogSchema = new mongoose.Schema(
  {
    actor: { type: mongoose.Schema.Types.ObjectId, ref: "User" }, // null for system/AI-originated entries
    actorType: { type: String, enum: ["user", "ai_pipeline", "system"], required: true },
    action: { type: String, required: true }, // e.g. "report.submit", "pipeline.run", "review.approve"
    report: { type: mongoose.Schema.Types.ObjectId, ref: "Report" },
    pipelineRunId: String,
    modelVersion: String,
    details: { type: mongoose.Schema.Types.Mixed },
    prevHash: { type: String, default: "GENESIS" },
    hash: { type: String },
    sequenceNumber: { type: Number, index: true },
  },
  { timestamps: true, capped: false }
);

// Compute hash and sequence number before saving new audit entries
auditLogSchema.pre("save", async function (next) {
  if (this.isNew) {
    const lastEntry = await this.constructor.findOne().sort({ sequenceNumber: -1, createdAt: -1 });
    if (!this.sequenceNumber) {
      this.sequenceNumber = (lastEntry?.sequenceNumber || 0) + 1;
    }
    if (!this.prevHash || this.prevHash === "GENESIS") {
      this.prevHash = lastEntry?.hash || "GENESIS";
    }

    const payload = [
      this.prevHash,
      this.actor?.toString() || "",
      this.actorType,
      this.action,
      this.report?.toString() || "",
      this.pipelineRunId || "",
      JSON.stringify(this.details || {}),
    ].join("|");

    this.hash = crypto.createHash("sha256").update(payload).digest("hex");
  }
  next();
});

// Enforce append-only at the database/ODM level: block any updates or deletes
const rejectModification = function () {
  throw new Error("AuditLog is strictly immutable and append-only. Modifying or deleting audit records is forbidden.");
};

auditLogSchema.pre(["updateOne", "updateMany", "findOneAndUpdate", "deleteOne", "deleteMany", "findOneAndDelete"], rejectModification);

export default mongoose.model("AuditLog", auditLogSchema);

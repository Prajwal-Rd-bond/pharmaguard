import mongoose from "mongoose";

// Module 5 output — ML ADR risk classification.
const classificationSchema = new mongoose.Schema(
  {
    report: { type: mongoose.Schema.Types.ObjectId, ref: "Report", required: true },
    pipelineRunId: { type: String, required: true },
    severity: { type: String, enum: ["mild", "moderate", "serious", "life_threatening"], required: true },
    confidence: { type: Number, min: 0, max: 1, required: true },
    modelName: String, // e.g. "ollama:llama3.2:3b", "rule_based_baseline"
    modelVersion: String,
    promptVersion: String, // "n/a" when produced by the rule-based fallback (no prompt used)
    rationale: String,
    priorityReview: { type: Boolean, default: false }, // auto-set true for serious/life_threatening
  },
  { timestamps: true }
);

export default mongoose.model("Classification", classificationSchema);

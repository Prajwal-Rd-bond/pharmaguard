import mongoose from "mongoose";

// Module 5 output — ML ADR risk classification.
const classificationSchema = new mongoose.Schema(
  {
    report: { type: mongoose.Schema.Types.ObjectId, ref: "Report", required: true },
    pipelineRunId: { type: String, required: true },
    severity: { type: String, enum: ["mild", "moderate", "serious", "life_threatening"], required: true },
    isSerious: { type: Boolean, default: false },
    is_serious: { type: Boolean, default: false },
    seriousnessCriteria: [
      {
        type: String,
        enum: ["death", "hospitalization", "disability", "congenital_anomaly", "life_threatening", "medically_important", "medically_significant", "other_serious"],
      },
    ],
    ichE2ACriteria: [String],
    ich_e2a_criteria: [String],
    regulatoryClockDays: { type: Number, default: 15 },
    regulatory_clock_days: { type: Number, default: 15 },
    periodicClockDays: { type: Number },
    periodic_clock_days: { type: Number },
    expeditedClockLabel: { type: String },
    expedited_clock_label: { type: String },
    confidence: { type: Number, min: 0, max: 1, required: true },
    modelName: String, // e.g. "ollama:llama3.2:3b", "rule_based_baseline"
    modelVersion: String,
    promptVersion: String, // "n/a" when produced by the rule-based fallback (no prompt used)
    rationale: String,
    priorityReview: { type: Boolean, default: false }, // auto-set true for serious/life_threatening or ICH serious criteria
  },
  { timestamps: true }
);

export default mongoose.model("Classification", classificationSchema);

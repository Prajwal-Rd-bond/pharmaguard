import mongoose from "mongoose";

// Module 5 output — ML ADR risk classification.
const classificationSchema = new mongoose.Schema(
  {
    report: { type: mongoose.Schema.Types.ObjectId, ref: "Report", required: true },
    pipelineRunId: { type: String, required: true },
    severity: { type: String, enum: ["mild", "moderate", "serious", "life_threatening"], required: true },
    confidence: { type: Number, min: 0, max: 1, required: true },
    modelName: String, // e.g. "xgboost_v1", "clinicalbert_v1"
    modelVersion: String,
    priorityReview: { type: Boolean, default: false }, // auto-set true for serious/life_threatening
  },
  { timestamps: true }
);

export default mongoose.model("Classification", classificationSchema);

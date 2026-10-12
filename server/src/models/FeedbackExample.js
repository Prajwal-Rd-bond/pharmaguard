import mongoose from "mongoose";

// Module 9 / Phase 2D — Stores human reviewer corrections as labeled ground-truth data for model evaluation & fine-tuning.
const feedbackExampleSchema = new mongoose.Schema(
  {
    report: { type: mongoose.Schema.Types.ObjectId, ref: "Report", required: true },
    reviewer: { type: mongoose.Schema.Types.ObjectId, ref: "User", required: true },
    rawText: { type: String, required: true },
    deidentifiedText: { type: String },
    aiExtraction: { type: mongoose.Schema.Types.Mixed },
    aiSeverity: { type: String },
    aiConfidence: { type: Number },
    humanCorrections: { type: mongoose.Schema.Types.Mixed },
    fieldDiffs: [
      {
        field: String,
        aiValue: mongoose.Schema.Types.Mixed,
        humanValue: mongoose.Schema.Types.Mixed,
      },
    ],
  },
  { timestamps: true }
);

export default mongoose.model("FeedbackExample", feedbackExampleSchema);


import mongoose from "mongoose";

// Module 4 output — structured JSON extracted by the LLM extraction engine.
const extractionSchema = new mongoose.Schema(
  {
    report: { type: mongoose.Schema.Types.ObjectId, ref: "Report", required: true },
    pipelineRunId: { type: String, required: true },
    drugName: String,
    genericName: String,
    brandName: String,
    dosage: String,
    frequency: String,
    route: String,
    duration: String,
    symptoms: [String],
    onsetTimeline: String,
    age: Number,
    gender: String,
    comorbidities: [String],
    concomitantDrugs: [String],
    incomplete: { type: Boolean, default: false }, // flagged instead of silently dropped
    modelVersion: String,
    promptVersion: String,
  },
  { timestamps: true }
);

export default mongoose.model("Extraction", extractionSchema);

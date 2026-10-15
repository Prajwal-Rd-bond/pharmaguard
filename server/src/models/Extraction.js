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
    rxNormId: String, // RxNorm RxCUI standard drug code
    meddraCodes: [
      {
        term: String,
        pt: String, // MedDRA Preferred Term
        soc: String, // System Organ Class
        code: String,
      },
    ],
    originalAiExtraction: { type: mongoose.Schema.Types.Mixed }, // Preserves original AI output if edited
    modelVersion: String,
    promptVersion: String,
  },
  { timestamps: true }
);

export default mongoose.model("Extraction", extractionSchema);

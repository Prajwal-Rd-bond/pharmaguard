import mongoose from "mongoose";

// Module 6/7 output — evidence retrieved from Qdrant (drug labels, similar cases, literature).
const retrievalSchema = new mongoose.Schema(
  {
    report: { type: mongoose.Schema.Types.ObjectId, ref: "Report", required: true },
    pipelineRunId: { type: String, required: true },
    sourceCollection: { type: String, required: true }, // drug_labels | research_papers | fda_alerts | clinical_guidelines | historical_cases
    sourceId: String,
    title: String,
    snippet: String,
    similarityScore: Number,
    retrievalMode: String, // "qdrant" | "fallback_baseline"
  },
  { timestamps: true }
);

export default mongoose.model("Retrieval", retrievalSchema);

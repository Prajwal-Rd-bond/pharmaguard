import mongoose from "mongoose";

// Module 2 (ADR Report Intake) + Module 3 (de-identification) storage.
const reportSchema = new mongoose.Schema(
  {
    submittedBy: { type: mongoose.Schema.Types.ObjectId, ref: "User", required: true },
    source: { type: String, enum: ["pdf", "docx", "pasted_text", "manual_form"], required: true },
    originalFilename: { type: String },
    rawText: { type: String, required: true }, // as submitted, pre-deidentification
    deidentifiedText: { type: String }, // set once Module 3 runs
    deidentificationLog: [
      {
        type: { type: String }, // e.g. "name", "phone", "email", "address", "hospital_id"
        span: { type: String }, // NOT the actual redacted value in normal display paths
      },
    ],
    status: {
      type: String,
      enum: [
        "submitted", // just intake, pipeline not yet run
        "processing", // pipeline running
        "pending_review", // pipeline complete, awaiting pharmacist
        "approved",
        "rejected",
        "needs_more_info",
      ],
      default: "submitted",
    },
    pipelineRunId: { type: String }, // ties this report to Extraction/Classification/Retrieval/AuditLog records
  },
  { timestamps: true }
);

export default mongoose.model("Report", reportSchema);

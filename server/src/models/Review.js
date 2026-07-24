import mongoose from "mongoose";

// Module 9 — human approval workflow.
const reviewSchema = new mongoose.Schema(
  {
    report: { type: mongoose.Schema.Types.ObjectId, ref: "Report", required: true },
    reviewer: { type: mongoose.Schema.Types.ObjectId, ref: "User", required: true },
    action: { type: String, enum: ["approve", "reject", "edit", "request_more_info"], required: true },
    comment: String,
    editedFields: { type: mongoose.Schema.Types.Mixed }, // diff of what the reviewer changed vs. AI output
  },
  { timestamps: true }
);

export default mongoose.model("Review", reviewSchema);

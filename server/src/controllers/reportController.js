import crypto from "crypto";
import Report from "../models/Report.js";
import Extraction from "../models/Extraction.js";
import Classification from "../models/Classification.js";
import Retrieval from "../models/Retrieval.js";
import Review from "../models/Review.js";
import { runPipeline } from "../utils/mlServiceClient.js";
import { logAction } from "../middleware/auditLogger.js";

// Module 2 — intake (pasted text or manual form; file upload handled by multer in routes).
export async function createReport(req, res) {
  const { source, rawText, originalFilename } = req.body;
  if (!source || !rawText) return res.status(400).json({ error: "source and rawText are required" });

  const report = await Report.create({
    submittedBy: req.user._id,
    source,
    rawText,
    originalFilename,
    status: "submitted",
  });

  await logAction({ actor: req.user._id, action: "report.submit", report: report._id });

  res.status(201).json({ report });
}

// Module 7 — triggers the full LLM/ML/RAG chain in the FastAPI service, then persists each stage's output.
export async function runReportPipeline(req, res) {
  const report = await Report.findById(req.params.id);
  if (!report) return res.status(404).json({ error: "Report not found" });

  const pipelineRunId = crypto.randomUUID();
  report.status = "processing";
  report.pipelineRunId = pipelineRunId;
  await report.save();

  await logAction({ actor: req.user._id, action: "pipeline.start", report: report._id, pipelineRunId });

  let result;
  try {
    result = await runPipeline({ pipelineRunId, rawText: report.rawText });
  } catch (err) {
    report.status = "submitted";
    await report.save();
    return res.status(502).json({ error: "ML pipeline call failed", detail: err.message });
  }

  report.deidentifiedText = result.deidentified_text;
  report.deidentificationLog = result.deidentification_log || [];
  report.status = "pending_review";
  await report.save();

  const extraction = await Extraction.create({
    report: report._id,
    pipelineRunId,
    ...result.extraction,
  });

  const classification = await Classification.create({
    report: report._id,
    pipelineRunId,
    severity: result.classification.severity,
    confidence: result.classification.confidence,
    modelName: result.classification.model_name,
    modelVersion: result.classification.model_version,
    promptVersion: result.classification.prompt_version,
    rationale: result.classification.rationale,
    priorityReview: ["serious", "life_threatening"].includes(result.classification.severity),
  });

  const retrievals = await Retrieval.insertMany(
    (result.retrievals || []).map((r) => ({
      report: report._id,
      pipelineRunId,
      sourceCollection: r.source_collection,
      sourceId: r.source_id,
      title: r.title,
      snippet: r.snippet,
      similarityScore: r.similarity_score,
      retrievalMode: r.retrieval_mode,
    }))
  );

  await logAction({
    actor: null,
    actorType: "ai_pipeline",
    action: "pipeline.complete",
    report: report._id,
    pipelineRunId,
    modelVersion: classification.modelVersion,
    details: { summary: result.summary },
  });

  res.json({ report, extraction, classification, retrievals, summary: result.summary });
}

export async function getReport(req, res) {
  const report = await Report.findById(req.params.id).populate("submittedBy", "name email role");
  if (!report) return res.status(404).json({ error: "Report not found" });

  const [extraction, classification, retrievals, reviews] = await Promise.all([
    Extraction.findOne({ report: report._id }).sort({ createdAt: -1 }),
    Classification.findOne({ report: report._id }).sort({ createdAt: -1 }),
    Retrieval.find({ report: report._id }),
    Review.find({ report: report._id }).populate("reviewer", "name role").sort({ createdAt: 1 }),
  ]);

  res.json({ report, extraction, classification, retrievals, reviews });
}

// Module 2's queue view — Pharmacists triage from here (Serious/Life-threatening surfaced first).
export async function listReports(req, res) {
  const { status } = req.query;
  const filter = status ? { status } : {};
  const reports = await Report.find(filter).sort({ createdAt: -1 }).limit(200).lean();

  const reportIds = reports.map(r => r._id);
  
  const [classifications, retrievals] = await Promise.all([
    Classification.find({ report: { $in: reportIds } }).lean(),
    Retrieval.find({ report: { $in: reportIds } }).lean()
  ]);

  const classMap = {};
  for (const c of classifications) {
    if (!classMap[c.report] || c.createdAt > classMap[c.report].createdAt) {
      classMap[c.report] = c;
    }
  }

  const retMap = {};
  for (const r of retrievals) {
    if (!retMap[r.report]) retMap[r.report] = [];
    retMap[r.report].push(r);
  }

  const enrichedReports = reports.map(r => ({
    ...r,
    classification: classMap[r._id] || null,
    retrievals: retMap[r._id] || []
  }));

  res.json({ reports: enrichedReports });
}

// Module 9 — human approval workflow. Every action is logged; edits are diffed against AI output.
export async function reviewReport(req, res) {
  const { action, comment, editedFields } = req.body;
  const allowed = ["approve", "reject", "edit", "request_more_info"];
  if (!allowed.includes(action)) return res.status(400).json({ error: `action must be one of ${allowed.join(", ")}` });

  const report = await Report.findById(req.params.id);
  if (!report) return res.status(404).json({ error: "Report not found" });

  const review = await Review.create({
    report: report._id,
    reviewer: req.user._id,
    action,
    comment,
    editedFields,
  });

  const statusByAction = {
    approve: "approved",
    reject: "rejected",
    edit: "pending_review",
    request_more_info: "needs_more_info",
  };
  report.status = statusByAction[action];
  await report.save();

  await logAction({
    actor: req.user._id,
    action: `review.${action}`,
    report: report._id,
    pipelineRunId: report.pipelineRunId,
    details: { comment, editedFields },
  });

  res.status(201).json({ review, report });
}

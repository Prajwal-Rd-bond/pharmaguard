import crypto from "crypto";
import Report from "../models/Report.js";
import Extraction from "../models/Extraction.js";
import Classification from "../models/Classification.js";
import Retrieval from "../models/Retrieval.js";
import { runPipeline } from "../utils/mlServiceClient.js";
import { logAction } from "../middleware/auditLogger.js";

// In-memory job state store for status polling
const jobStates = new Map();

/**
 * Worker handler that executes the full multi-stage AI pipeline
 * and persists results independently to MongoDB.
 */
export async function executePipelineTask({ reportId, userId, jobId }) {
  const report = await Report.findById(reportId);
  if (!report) {
    jobStates.set(jobId, { status: "failed", error: "Report not found", updatedAt: new Date() });
    return;
  }

  const pipelineRunId = crypto.randomUUID();
  report.status = "processing";
  report.pipelineRunId = pipelineRunId;
  await report.save();

  jobStates.set(jobId, { status: "processing", step: "running_ai_models", reportId, updatedAt: new Date() });
  await logAction({ actor: userId, action: "pipeline.start", report: report._id, pipelineRunId });

  let result;
  try {
    const rawTextForInference = report.getDecryptedRawText ? report.getDecryptedRawText() : report.rawText;
    result = await runPipeline({ pipelineRunId, rawText: rawTextForInference });
  } catch (err) {
    report.status = "submitted";
    await report.save();
    jobStates.set(jobId, {
      status: "failed",
      error: `ML pipeline call failed: ${err.message}`,
      updatedAt: new Date(),
    });
    await logAction({
      actor: null,
      actorType: "ai_pipeline",
      action: "pipeline.failed",
      report: report._id,
      pipelineRunId,
      details: { error: err.message },
    });
    return;
  }

  report.deidentifiedText = result.deidentified_text;
  report.deidentificationLog = result.deidentification_log || [];
  report.summary = result.summary;
  report.summaryModelVersion = result.extraction?.modelVersion || "summary-v1";

  // Phase 2B & 2C: Regulatory, Causality, Terminology, Citations
  report.ichE2ACriteria = result.classification?.ich_e2a_criteria || [];
  report.isSerious = Boolean(result.classification?.is_serious);
  const clockDays = result.classification?.regulatory_clock_days || 15;
  report.regulatoryClockDays = clockDays;
  report.regulatoryDueDate = new Date(Date.now() + clockDays * 24 * 60 * 60 * 1000);
  report.causality = result.causality || null;
  report.terminology = result.extraction?.terminology || null;
  report.citationVerification = result.citation_verification || null;

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

  jobStates.set(jobId, {
    status: "completed",
    reportId,
    pipelineRunId,
    summary: result.summary,
    severity: classification.severity,
    updatedAt: new Date(),
  });
}

// Queue setup: Hybrid BullMQ with automatic resilient fallback
let bullQueue = null;
let bullWorker = null;

async function initQueue() {
  if (process.env.DISABLE_REDIS === "true") return;

  try {
    const { Queue, Worker } = await import("bullmq");
    const { default: IORedis } = await import("ioredis");

    const redisUrl = process.env.REDIS_URL || "redis://localhost:6379";
    const connection = new IORedis(redisUrl, {
      maxRetriesPerRequest: null,
      enableReadyCheck: false,
      lazyConnect: true,
      retryStrategy: () => null, // Do not spam retries if Redis is down
    });

    await connection.connect();

    bullQueue = new Queue("report-processing-queue", { connection });
    bullWorker = new Worker(
      "report-processing-queue",
      async (job) => {
        await executePipelineTask(job.data);
      },
      { connection, concurrency: 3 }
    );

    console.log("[Queue] BullMQ + Redis queue initialized on 'report-processing-queue'.");
  } catch (err) {
    console.log("[Queue] Redis not detected, using resilient in-process async worker fallback.");
    bullQueue = null;
    bullWorker = null;
  }
}

initQueue().catch(() => {});

/**
 * Enqueue report pipeline processing.
 * Dispatches via BullMQ if Redis is active, or via async worker fallback.
 */
export async function enqueuePipelineJob({ reportId, userId }) {
  const jobId = crypto.randomUUID();
  jobStates.set(jobId, { status: "queued", reportId, createdAt: new Date() });

  if (bullQueue) {
    try {
      await bullQueue.add("process-report", { reportId, userId, jobId }, { jobId });
      return { jobId, status: "queued", engine: "bullmq" };
    } catch (err) {
      console.warn("[Queue] BullMQ add failed, falling back to in-process worker:", err.message);
    }
  }

  // Resilient asynchronous in-process dispatch
  setImmediate(() => {
    executePipelineTask({ reportId, userId, jobId }).catch((err) => {
      console.error("[Queue] In-process pipeline task failed:", err);
    });
  });

  return { jobId, status: "queued", engine: "in_process" };
}

/**
 * Get status of an enqueued pipeline job.
 */
export function getJobStatus(jobId) {
  return jobStates.get(jobId) || { status: "unknown" };
}

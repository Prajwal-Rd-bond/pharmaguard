import crypto from "crypto";
import Report from "../models/Report.js";
import Extraction from "../models/Extraction.js";
import Classification from "../models/Classification.js";
import Retrieval from "../models/Retrieval.js";
import Review from "../models/Review.js";
import FeedbackExample from "../models/FeedbackExample.js";
import { runPipeline } from "../utils/mlServiceClient.js";
import { logAction } from "../middleware/auditLogger.js";
import { enqueuePipelineJob, getJobStatus, executePipelineTask } from "../queue/pipelineQueue.js";
import { parseClinicalDocument } from "../utils/documentParser.js";

// Module 2 — intake (pasted text or file upload handled by multer in routes).
export async function createReport(req, res) {
  let { source, rawText, originalFilename } = req.body;

  if (req.file) {
    originalFilename = originalFilename || req.file.originalname;
    source = source || (req.file.originalname.endsWith(".pdf") ? "pdf" : req.file.originalname.endsWith(".docx") ? "docx" : "uploaded_file");
    if (!rawText && req.file.buffer) {
      rawText = parseClinicalDocument(req.file.buffer, req.file.originalname, req.file.mimetype);
    }
  }

  if (!source || !rawText) return res.status(400).json({ error: "source and rawText (or file upload) are required" });

  const report = await Report.create({
    submittedBy: req.user._id,
    source,
    rawText,
    originalFilename,
    status: "submitted",
  });

  await logAction({ actor: req.user._id, action: "report.submit", report: report._id, details: { source, originalFilename } });

  res.status(201).json({ report });
}

// Module 7 — triggers the full LLM/ML/RAG chain asynchronously via BullMQ / background queue.
export async function runReportPipeline(req, res) {
  const report = await Report.findById(req.params.id);
  if (!report) return res.status(404).json({ error: "Report not found" });

  if (report.status === "processing") {
    return res.status(409).json({ error: "Report is already currently processing" });
  }

  // Synchronous execution path for testing / debugging
  if (req.query.sync === "true") {
    const jobId = crypto.randomUUID();
    await executePipelineTask({ reportId: report._id.toString(), userId: req.user._id.toString(), jobId });
    const updated = await Report.findById(report._id);
    const [extraction, classification, retrievals] = await Promise.all([
      Extraction.findOne({ report: report._id }).sort({ createdAt: -1 }),
      Classification.findOne({ report: report._id }).sort({ createdAt: -1 }),
      Retrieval.find({ report: report._id }),
    ]);
    return res.json({ report: updated, extraction, classification, retrievals, summary: updated.summary });
  }

  // Asynchronous queue dispatch (BullMQ + Redis / background worker)
  report.status = "processing";
  await report.save();

  const job = await enqueuePipelineJob({
    reportId: report._id.toString(),
    userId: req.user._id.toString(),
  });

  res.status(202).json({
    message: "Report pipeline job accepted",
    jobId: job.jobId,
    engine: job.engine,
    reportId: report._id,
    status: "processing",
  });
}

export async function getPipelineStatus(req, res) {
  const report = await Report.findById(req.params.id);
  if (!report) return res.status(404).json({ error: "Report not found" });

  const job = req.query.jobId ? getJobStatus(req.query.jobId) : null;
  res.json({
    reportId: report._id,
    status: report.status,
    job,
    summary: report.summary,
  });
}

export async function getReport(req, res) {
  const report = await Report.findById(req.params.id).populate("submittedBy", "name email role");
  if (!report) return res.status(404).json({ error: "Report not found" });

  // Doctor access scoping: Doctors can only view their own submissions
  if (req.user.role === "doctor" && report.submittedBy?._id.toString() !== req.user._id.toString()) {
    return res.status(403).json({ error: "Access denied: Doctors may only view reports they submitted" });
  }

  const [extraction, classification, retrievals, reviews] = await Promise.all([
    Extraction.findOne({ report: report._id }).sort({ createdAt: -1 }),
    Classification.findOne({ report: report._id }).sort({ createdAt: -1 }),
    Retrieval.find({ report: report._id }),
    Review.find({ report: report._id }).populate("reviewer", "name role").sort({ createdAt: 1 }),
  ]);

  const reportObj = report.toObject ? report.toObject() : { ...report };
  reportObj.rawText = report.getDecryptedRawText ? report.getDecryptedRawText() : report.rawText;

  res.json({ report: reportObj, extraction, classification, retrievals, reviews, summary: report.summary });
}

// Module 2's queue view — Pharmacists triage from here (Serious/Life-threatening surfaced first).
export async function listReports(req, res) {
  const { status } = req.query;
  const filter = status ? { status } : {};

  // Doctor access scoping: only see self-submitted reports
  if (req.user.role === "doctor") {
    filter.submittedBy = req.user._id;
  }

  const reports = await Report.find(filter)
    .populate("submittedBy", "name email role")
    .sort({ createdAt: -1 })
    .limit(200)
    .lean();

  const reportIds = reports.map((r) => r._id);
  const [classifications, extractions] = await Promise.all([
    Classification.find({ report: { $in: reportIds } }).sort({ createdAt: -1 }),
    Extraction.find({ report: { $in: reportIds } }).sort({ createdAt: -1 }),
  ]);

  const classMap = new Map();
  for (const c of classifications) {
    const key = c.report.toString();
    if (!classMap.has(key)) classMap.set(key, c);
  }
  const extMap = new Map();
  for (const e of extractions) {
    const key = e.report.toString();
    if (!extMap.has(key)) extMap.set(key, e);
  }

  const severityWeight = {
    life_threatening: 4,
    serious: 3,
    moderate: 2,
    mild: 1,
  };

  const now = new Date();
  const populated = reports.map((r) => {
    const c = classMap.get(r._id.toString());
    const e = extMap.get(r._id.toString());

    // Regulatory clock SLA computation
    const clockDays = r.regulatoryClockDays || (c?.severity === "life_threatening" ? 7 : 15);
    const dueDate = r.regulatoryDueDate || new Date(new Date(r.createdAt).getTime() + clockDays * 86400000);
    const hoursRemaining = Math.round((dueDate.getTime() - now.getTime()) / 3600000);
    let clockStatus = "ON_TRACK";
    if (hoursRemaining <= 0) {
      clockStatus = "OVERDUE";
    } else if (hoursRemaining <= 48) {
      clockStatus = "EXPEDITED_CRITICAL";
    }

    return {
      ...r,
      classification: c ? { severity: c.severity, confidence: c.confidence } : null,
      extraction: e ? { drugName: e.drugName, symptoms: e.symptoms } : null,
      regulatoryDueDate: dueDate,
      regulatoryClockDays: clockDays,
      hoursRemaining,
      clockStatus,
    };
  });

  // Sort queue by severity priority (life-threatening > serious > moderate > mild), then date
  populated.sort((a, b) => {
    const weightA = severityWeight[a.classification?.severity] || 0;
    const weightB = severityWeight[b.classification?.severity] || 0;
    if (weightB !== weightA) return weightB - weightA;
    return new Date(b.createdAt) - new Date(a.createdAt);
  });

  res.json({ reports: populated });
}

// Module 9 — human approval workflow. Every action is logged; edits are diffed against AI output.
export async function reviewReport(req, res) {
  const { action, comment, editedFields } = req.body;
  const allowed = ["approve", "reject", "edit", "request_more_info"];
  if (!allowed.includes(action)) return res.status(400).json({ error: `action must be one of ${allowed.join(", ")}` });

  const report = await Report.findById(req.params.id);
  if (!report) return res.status(404).json({ error: "Report not found" });

  // State-machine guards: Cannot review an unprocessed or already finalized report
  if (report.status === "submitted" || report.status === "processing") {
    return res.status(400).json({
      error: `Cannot review report in '${report.status}' status. Run the AI pipeline first.`,
    });
  }

  if (["approved", "rejected"].includes(report.status) && action !== "edit") {
    return res.status(400).json({
      error: `Report is already finalized as '${report.status}'.`,
    });
  }

  // If action is edit, apply edited fields to latest Extraction / Classification
  if (action === "edit" && editedFields && typeof editedFields === "object") {
    const latestExtraction = await Extraction.findOne({ report: report._id }).sort({ createdAt: -1 });
    const latestClassification = await Classification.findOne({ report: report._id }).sort({ createdAt: -1 });
    const fieldDiffs = [];

    if (latestExtraction) {
      if (editedFields.drugName !== undefined && editedFields.drugName !== latestExtraction.drugName) {
        fieldDiffs.push({ field: "drugName", aiValue: latestExtraction.drugName, humanValue: editedFields.drugName });
        latestExtraction.drugName = editedFields.drugName;
      }
      if (editedFields.symptoms !== undefined) {
        const parsedSymptoms = Array.isArray(editedFields.symptoms)
          ? editedFields.symptoms
          : editedFields.symptoms.split(",").map((s) => s.trim()).filter(Boolean);
        fieldDiffs.push({ field: "symptoms", aiValue: latestExtraction.symptoms, humanValue: parsedSymptoms });
        latestExtraction.symptoms = parsedSymptoms;
      }
      if (editedFields.dosage !== undefined && editedFields.dosage !== latestExtraction.dosage) {
        fieldDiffs.push({ field: "dosage", aiValue: latestExtraction.dosage, humanValue: editedFields.dosage });
        latestExtraction.dosage = editedFields.dosage;
      }
      if (editedFields.frequency !== undefined && editedFields.frequency !== latestExtraction.frequency) {
        fieldDiffs.push({ field: "frequency", aiValue: latestExtraction.frequency, humanValue: editedFields.frequency });
        latestExtraction.frequency = editedFields.frequency;
      }
      if (editedFields.route !== undefined && editedFields.route !== latestExtraction.route) {
        fieldDiffs.push({ field: "route", aiValue: latestExtraction.route, humanValue: editedFields.route });
        latestExtraction.route = editedFields.route;
      }
      await latestExtraction.save();
    }

    if (editedFields.severity && latestClassification) {
      if (editedFields.severity !== latestClassification.severity) {
        fieldDiffs.push({ field: "severity", aiValue: latestClassification.severity, humanValue: editedFields.severity });
        latestClassification.severity = editedFields.severity;
        latestClassification.priorityReview = ["serious", "life_threatening"].includes(editedFields.severity);
        await latestClassification.save();
      }
    }

    // Persist to Gold-Standard Curated Feedback dataset (Phase 2D)
    if (fieldDiffs.length > 0) {
      await FeedbackExample.create({
        report: report._id,
        reviewer: req.user._id,
        rawText: report.rawText,
        deidentifiedText: report.deidentifiedText,
        aiExtraction: latestExtraction?.toObject ? latestExtraction.toObject() : latestExtraction,
        aiSeverity: latestClassification?.severity,
        aiConfidence: latestClassification?.confidence,
        humanCorrections: editedFields,
        fieldDiffs,
      });
    }
  }

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

// Phase 2D — Export labeled evaluation dataset generated from human reviewer corrections
export async function exportFeedbackDataset(req, res) {
  const examples = await FeedbackExample.find()
    .populate("reviewer", "name role")
    .sort({ createdAt: -1 })
    .limit(1000)
    .lean();

  res.json({
    total: examples.length,
    description: "Gold-standard human-corrected ADR dataset for model evaluation and fine-tuning",
    examples,
  });
}

// Phase 2B — ICH E2B(R3) ICSR XML Exporter for regulatory submission (FDA FAERS / EMA EudraVigilance)
export async function exportReportE2BXml(req, res) {
  const report = await Report.findById(req.params.id).populate("submittedBy", "name email role");
  if (!report) return res.status(404).json({ error: "Report not found" });

  const [extraction, classification] = await Promise.all([
    Extraction.findOne({ report: report._id }).sort({ createdAt: -1 }),
    Classification.findOne({ report: report._id }).sort({ createdAt: -1 }),
  ]);

  const messageDate = new Date().toISOString().replace(/[-:T.]/g, "").slice(0, 14);
  const reportId = `PHARMAGUARD-${report._id.toString().toUpperCase()}`;
  const drugName = extraction?.drugName || "UNKNOWN_DRUG";
  const rxcui = report.terminology?.drugRxNorm?.rxcui || "UNKNOWN";
  const symptoms = extraction?.symptoms || [];
  const primaryReaction = symptoms[0] || "Adverse Event";
  const meddraPt = report.terminology?.meddraAdverseEvents?.[0]?.pt || primaryReaction;
  const meddraSoc = report.terminology?.meddraAdverseEvents?.[0]?.soc || "General disorders";
  const seriousnessCode = report.isSerious ? "1" : "2";

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<ichicsr lang="en">
  <ichicsrmessageheader>
    <messagetype>ichicsr</messagetype>
    <messageformatversion>2.1</messageformatversion>
    <messagereleaseversion>2.0</messagereleaseversion>
    <messagesenderidentifier>PHARMAGUARD_SAFETY_SYSTEM</messagesenderidentifier>
    <messagereceiveridentifier>FDA_FAERS_ELECTRONIC_SUBMISSION</messagereceiveridentifier>
    <messagedateformat>204</messagedateformat>
    <messagedate>${messageDate}</messagedate>
  </ichicsrmessageheader>
  <safetyreport>
    <safetyreportversion>1</safetyreportversion>
    <safetyreportid>${reportId}</safetyreportid>
    <primarysourcecountry>US</primarysourcecountry>
    <occurcountry>US</occurcountry>
    <transmissiondateformat>102</transmissiondateformat>
    <transmissiondate>${messageDate.slice(0, 8)}</transmissiondate>
    <reporttype>1</reporttype>
    <serious>${seriousnessCode}</serious>
    <seriousnessdeath>${report.ichE2ACriteria?.includes("death") ? "1" : "2"}</seriousnessdeath>
    <seriousnesslifethreatening>${report.ichE2ACriteria?.includes("life_threatening") ? "1" : "2"}</seriousnesslifethreatening>
    <seriousnesshospitalization>${report.ichE2ACriteria?.includes("hospitalization") ? "1" : "2"}</seriousnesshospitalization>
    <seriousnessdisabling>${report.ichE2ACriteria?.includes("disability") ? "1" : "2"}</seriousnessdisabling>
    <seriousnesscongenitalanomali>${report.ichE2ACriteria?.includes("congenital_anomaly") ? "1" : "2"}</seriousnesscongenitalanomali>
    <seriousnessother>${report.ichE2ACriteria?.includes("medically_significant") ? "1" : "2"}</seriousnessother>
    <primarysource>
      <reporterqualification>1</reporterqualification>
      <reportergivename>${report.submittedBy?.name || "Healthcare Provider"}</reportergivename>
    </primarysource>
    <patient>
      <patientinitial>ANON</patientinitial>
      <patientonsetage>${extraction?.age || "UNK"}</patientonsetage>
      <patientsex>${extraction?.gender?.toLowerCase() === "female" ? "2" : extraction?.gender?.toLowerCase() === "male" ? "1" : "0"}</patientsex>
      <medicalhistorytext>${(extraction?.comorbidities || []).join(", ") || "None recorded"}</medicalhistorytext>
      <reaction>
        <primarysourcereaction>${primaryReaction}</primarysourcereaction>
        <reactionmeddraversionpt>26.1</reactionmeddraversionpt>
        <reactionmeddrapt>${meddraPt}</reactionmeddrapt>
        <reactionsoc>${meddraSoc}</reactionsoc>
        <reactionoutcome>1</reactionoutcome>
      </reaction>
      <drug>
        <drugcharacterization>1</drugcharacterization>
        <medicinalproduct>${drugName}</medicinalproduct>
        <drugstructuredosagenumb>${extraction?.dosage || "UNSPECIFIED"}</drugstructuredosagenumb>
        <drugadministrationroute>${extraction?.route || "Oral"}</drugadministrationroute>
        <drugrxnormcui>${rxcui}</drugrxnormcui>
        <drugassessment>
          <drugcausalitynaranjoscore>${report.causality?.naranjoScore || "0"}</drugcausalitynaranjoscore>
          <drugcausalitywhoumc>${report.causality?.whoUmcCategory || "Possible"}</drugcausalitywhoumc>
        </drugassessment>
      </drug>
    </patient>
    <summary>
      <narrativeincludeclinical>${report.summary || "No narrative generated."}</narrativeincludeclinical>
      <reportercomment>${report.causality?.rationale || ""}</reportercomment>
    </summary>
  </safetyreport>
</ichicsr>`;

  res.setHeader("Content-Type", "application/xml");
  res.setHeader("Content-Disposition", `attachment; filename="${reportId}.xml"`);
  res.send(xml);
}

// Phase 2B — Duplicate ICSR Detection across patient demographics, suspect drug, and symptoms
export async function checkDuplicateReports(req, res) {
  const currentReport = await Report.findById(req.params.id);
  if (!currentReport) return res.status(404).json({ error: "Report not found" });

  const currentExt = await Extraction.findOne({ report: currentReport._id });
  if (!currentExt || !currentExt.drugName) {
    return res.json({ duplicates: [] });
  }

  const candidateExtractions = await Extraction.find({
    report: { $ne: currentReport._id },
    drugName: { $regex: new RegExp(`^${currentExt.drugName}$`, "i") },
  }).populate("report").limit(50);

  const duplicates = [];
  const currentSymptoms = new Set((currentExt.symptoms || []).map((s) => s.toLowerCase()));

  for (const ext of candidateExtractions) {
    if (!ext.report) continue;
    let score = 0.4;

    const candSymptoms = new Set((ext.symptoms || []).map((s) => s.toLowerCase()));
    const intersection = [...currentSymptoms].filter((s) => candSymptoms.has(s));
    if (intersection.length > 0) {
      score += 0.3 * (intersection.length / Math.max(1, currentSymptoms.size));
    }

    if (currentExt.gender && ext.gender && currentExt.gender.toLowerCase() === ext.gender.toLowerCase()) {
      score += 0.15;
    }
    if (currentExt.age && ext.age && Math.abs(currentExt.age - ext.age) <= 5) {
      score += 0.15;
    }

    if (score >= 0.55) {
      duplicates.push({
        reportId: ext.report._id,
        createdAt: ext.report.createdAt,
        status: ext.report.status,
        similarityScore: Math.round(score * 100) / 100,
        overlappingDrug: ext.drugName,
        overlappingSymptoms: intersection,
        age: ext.age,
        gender: ext.gender,
      });
    }
  }

  duplicates.sort((a, b) => b.similarityScore - a.similarityScore);
  res.json({ duplicates });
}

// Phase 2B — Confirm / Override Causality Assessment
export async function updateReportCausality(req, res) {
  const { confirmedByPharmacist, pharmacistNotes, overrideCategory } = req.body;
  const report = await Report.findById(req.params.id);
  if (!report) return res.status(404).json({ error: "Report not found" });

  if (!report.causality) {
    report.causality = {};
  }

  if (confirmedByPharmacist !== undefined) {
    report.causality.confirmedByPharmacist = Boolean(confirmedByPharmacist);
  }
  if (pharmacistNotes) {
    report.causality.pharmacistNotes = pharmacistNotes;
  }
  if (overrideCategory) {
    report.causality.whoUmcCategory = overrideCategory;
  }

  await report.save();
  await logAction({
    actor: req.user._id,
    action: "report.causality_confirm",
    report: report._id,
    details: { causality: report.causality },
  });

  res.json({ ok: true, causality: report.causality });
}


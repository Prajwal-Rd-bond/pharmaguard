import mongoose from "mongoose";
import axios from "axios";
import Report from "../models/Report.js";
import { verifyAuditChain } from "../middleware/auditLogger.js";

const ML_SERVICE_URL = process.env.ML_SERVICE_URL || "http://localhost:8000";

export async function getDetailedHealth(req, res) {
  const mongoStatus = mongoose.connection.readyState === 1 ? "connected" : "disconnected";

  // Check ML service
  let mlServiceStatus = "unreachable";
  try {
    const mlRes = await axios.get(`${ML_SERVICE_URL}/health`, { timeout: 1500 });
    if (mlRes.data?.ok) mlServiceStatus = "healthy";
  } catch {
    mlServiceStatus = "offline";
  }

  // Audit Log integrity verification
  let auditIntegrity = { valid: true };
  try {
    auditIntegrity = await verifyAuditChain();
  } catch (err) {
    auditIntegrity = { valid: false, error: err.message };
  }

  const mem = process.memoryUsage();
  const uptimeSeconds = Math.round(process.uptime());

  const isHealthy = mongoStatus === "connected";

  res.status(isHealthy ? 200 : 503).json({
    status: isHealthy ? "healthy" : "degraded",
    service: "pharmaguard-server",
    timestamp: new Date().toISOString(),
    uptimeSeconds,
    traceId: req.traceId,
    dependencies: {
      mongodb: mongoStatus,
      mlService: mlServiceStatus,
      auditLogIntegrity: auditIntegrity.valid ? "intact" : "tampered_or_broken",
    },
    system: {
      nodeVersion: process.version,
      memory: {
        rssMb: Math.round(mem.rss / 1024 / 1024),
        heapUsedMb: Math.round(mem.heapUsed / 1024 / 1024),
        heapTotalMb: Math.round(mem.heapTotal / 1024 / 1024),
      },
    },
  });
}

export async function getOperationalMetrics(req, res) {
  const [totalReports, reportsByStatus, seriousReports] = await Promise.all([
    Report.countDocuments(),
    Report.aggregate([{ $group: { _id: "$status", count: { $sum: 1 } } }]),
    Report.countDocuments({ isSerious: true }),
  ]);

  const statusMap = {};
  for (const item of reportsByStatus) {
    statusMap[item._id] = item.count;
  }

  // Count overdue cases
  const overdueCount = await Report.countDocuments({
    status: { $in: ["submitted", "processing", "pending_review", "needs_more_info"] },
    regulatoryDueDate: { $lt: new Date() },
  });

  res.json({
    timestamp: new Date().toISOString(),
    metrics: {
      totalReports,
      seriousReports,
      overdueReports: overdueCount,
      reportsByStatus: statusMap,
    },
  });
}


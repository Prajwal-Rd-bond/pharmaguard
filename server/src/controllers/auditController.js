import AuditLog from "../models/AuditLog.js";

// Module 12 — read-only. No update/delete route exists for this resource by design.
export async function listAuditLogs(req, res) {
  const { report, action } = req.query;
  const filter = {};
  if (report) filter.report = report;
  if (action) filter.action = action;

  const logs = await AuditLog.find(filter).populate("actor", "name role").sort({ createdAt: -1 }).limit(500);
  res.json({ logs });
}

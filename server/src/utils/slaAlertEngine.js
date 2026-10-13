/**
 * Pharmacist Regulatory Clock & SLA Urgency Tracking Engine
 * Enforces ICH E2A expedited regulatory compliance rules (7-day / 15-day clocks).
 */

/**
 * Calculates current SLA status and urgency metrics for a report.
 *
 * @param {Object} report - Mongoose Report object
 * @returns {Object} SLA status details
 */
export function calculateReportSla(report) {
  if (!report) return null;

  const now = new Date();
  const createdAt = report.createdAt ? new Date(report.createdAt) : now;
  const isExpedited7Day =
    report.isSerious &&
    Array.isArray(report.ichE2ACriteria) &&
    (report.ichE2ACriteria.includes("death") || report.ichE2ACriteria.includes("life_threatening"));

  const clockDays = isExpedited7Day ? 7 : report.isSerious ? 15 : 30;
  const dueDate =
    report.regulatoryDueDate ? new Date(report.regulatoryDueDate) : new Date(createdAt.getTime() + clockDays * 86400000);

  const msRemaining = dueDate.getTime() - now.getTime();
  const hoursRemaining = Math.round(msRemaining / (1000 * 60 * 60));
  const isOverdue = msRemaining < 0;

  let urgencyLevel = "normal";
  if (isOverdue) {
    urgencyLevel = "breached";
  } else if (hoursRemaining <= 24) {
    urgencyLevel = "critical_imminent";
  } else if (hoursRemaining <= 48) {
    urgencyLevel = "warning_approaching";
  } else if (isExpedited7Day) {
    urgencyLevel = "expedited_active";
  }

  return {
    clockDays,
    dueDate,
    msRemaining,
    hoursRemaining,
    isOverdue,
    urgencyLevel,
    isExpedited7Day,
    status: report.status,
  };
}

/**
 * Evaluates an array of reports and aggregates SLA metrics for the clinical dashboard.
 *
 * @param {Array} reports - List of reports
 * @returns {Object} Aggregated SLA metrics
 */
export function aggregateQueueSlaMetrics(reports) {
  if (!Array.isArray(reports)) {
    return {
      totalActive: 0,
      breachedCount: 0,
      criticalImminentCount: 0,
      expeditedCount: 0,
      averageHoursRemaining: 0,
    };
  }

  let breached = 0;
  let criticalImminent = 0;
  let expedited = 0;
  let totalHours = 0;
  let activeReportsCount = 0;

  for (const report of reports) {
    if (report.status === "approved" || report.status === "rejected") continue; // resolved

    activeReportsCount++;
    const sla = calculateReportSla(report);

    if (sla.isOverdue) breached++;
    if (sla.urgencyLevel === "critical_imminent") criticalImminent++;
    if (sla.isExpedited7Day) expedited++;
    totalHours += Math.max(0, sla.hoursRemaining);
  }

  return {
    totalActive: activeReportsCount,
    breachedCount: breached,
    criticalImminentCount: criticalImminent,
    expeditedCount: expedited,
    averageHoursRemaining:
      activeReportsCount > 0 ? Math.round((totalHours / activeReportsCount) * 10) / 10 : 0,
  };
}

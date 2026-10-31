import { EventEmitter } from "events";
import { calculateReportSla, aggregateQueueSlaMetrics } from "./slaAlertEngine.js";

/**
 * PharmaGuard Real-Time Regulatory SLA Alerting & Event Streaming Engine
 * Native HTTP/1.1 Server-Sent Events (SSE) broadcaster with zero external dependencies.
 * Streams real-time 7-day expedited countdowns, imminent breach alerts, ingestion notifications,
 * and regulatory gateway transmission receipts to connected clinical clients.
 */
class RealtimeEventManager extends EventEmitter {
  constructor() {
    super();
    this.clients = new Set();
    this.heartbeatInterval = null;
    this.startHeartbeat();
  }

  /**
   * Starts a 25-second keepalive heartbeat ping for active SSE streams.
   */
  startHeartbeat() {
    if (this.heartbeatInterval) return;
    this.heartbeatInterval = setInterval(() => {
      this.broadcast("ping", { timestamp: Date.now() });
    }, 25000);
    this.heartbeatInterval.unref();
  }

  /**
   * Registers a new client HTTP response as an active SSE stream.
   *
   * @param {Object} req - Express request object
   * @param {Object} res - Express response object
   * @param {Array} [currentReports=[]] - Optional active reports to calculate immediate SLA snapshot
   */
  registerClient(req, res, currentReports = []) {
    res.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
      "Access-Control-Allow-Origin": "*",
    });

    const client = {
      id: `sse-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      res,
      user: req?.user || null,
      connectedAt: new Date(),
    };

    this.clients.add(client);

    // Send initial handshake
    this.sendEventToClient(client, "connected", {
      clientId: client.id,
      timestamp: Date.now(),
      activeClients: this.clients.size,
    });

    // Send immediate SLA snapshot if reports are available
    if (Array.isArray(currentReports) && currentReports.length > 0) {
      const summary = aggregateQueueSlaMetrics(currentReports);
      this.sendEventToClient(client, "sla_snapshot", summary);
    }

    req.on("close", () => {
      this.clients.delete(client);
    });

    return client;
  }

  /**
   * Sends an SSE formatted message to an individual client.
   */
  sendEventToClient(client, eventType, data) {
    try {
      const payload = typeof data === "string" ? data : JSON.stringify(data);
      client.res.write(`event: ${eventType}\ndata: ${payload}\n\n`);
    } catch {
      this.clients.delete(client);
    }
  }

  /**
   * Broadcasts an event to connected clients with doctor role filtering.
   *
   * @param {string} eventType - Event name
   * @param {Object} data - Event data
   */
  broadcast(eventType, data) {
    this.emit(eventType, data);
    for (const client of this.clients) {
      if (client.user?.role === "doctor") {
        const eventAuthor = data?.submittedBy?.toString();
        const clientUserId = client.user._id?.toString();
        if (eventAuthor && clientUserId && eventAuthor !== clientUserId) {
          continue; // Doctor never sees another clinician's report events
        }
      }
      this.sendEventToClient(client, eventType, data);
    }
  }

  /**
   * Broadcasts an urgent regulatory SLA alert (e.g. 7-day expedited under 24 hours).
   *
   * @param {Object} report - Mongoose Report object
   * @param {Object} [slaData] - Pre-calculated SLA details
   */
  broadcastSlaAlert(report, slaData = null) {
    const sla = slaData || calculateReportSla(report);
    const alert = {
      type: "SLA_URGENT_ALERT",
      reportId: report._id,
      submittedBy: report.submittedBy?._id || report.submittedBy,
      isExpedited7Day: sla.isExpedited7Day,
      clockDays: sla.clockDays,
      hoursRemaining: sla.hoursRemaining,
      urgencyLevel: sla.urgencyLevel,
      isOverdue: sla.isOverdue,
      message: sla.isOverdue
        ? `REGULATORY BREACH: Case #${report._id} has exceeded the ${sla.clockDays}-day expedited regulatory clock!`
        : `URGENT SLA WARNING: Case #${report._id} has ${sla.hoursRemaining}h remaining before ${sla.clockDays}-day regulatory deadline.`,
      timestamp: new Date().toISOString(),
    };

    this.broadcast("sla_alert", alert);
    return alert;
  }

  /**
   * Broadcasts an ingestion event when a new report is created.
   */
  broadcastReportCreated(report) {
    const isSerious = Boolean(report.isSerious);
    const criteria = Array.isArray(report.ichE2ACriteria) ? report.ichE2ACriteria : [];
    const isExpedited = criteria.includes("death") || criteria.includes("life_threatening");

    const payload = {
      type: "REPORT_INGESTED",
      reportId: report._id,
      submittedBy: report.submittedBy?._id || report.submittedBy,
      source: report.source || "intake",
      isSerious,
      isExpedited,
      criteria,
      status: report.status || "submitted",
      timestamp: new Date().toISOString(),
    };

    this.broadcast("report_created", payload);

    // If life-threatening / fatal expedited case, also trigger immediate SLA alert
    if (isExpedited) {
      this.broadcastSlaAlert(report);
    }

    return payload;
  }

  /**
   * Broadcasts a regulatory gateway transmission receipt (FDA ESG / AS2).
   */
  broadcastGatewayTransmission(report, gatewayResult) {
    const payload = {
      type: "GATEWAY_TRANSMISSION",
      reportId: report._id,
      transmissionId: gatewayResult.transmissionId,
      status: gatewayResult.status,
      mdnStatus: gatewayResult.mdnStatus,
      micMatch: gatewayResult.micMatch,
      timestamp: new Date().toISOString(),
    };

    this.broadcast("gateway_transmission", payload);
    return payload;
  }

  /**
   * Broadcasts a report status transition (e.g. approved, rejected, edited).
   */
  broadcastReportStatusChange(report, action, reviewerId = null) {
    const payload = {
      type: "STATUS_TRANSITION",
      reportId: report._id,
      action,
      status: report.status,
      reviewerId,
      timestamp: new Date().toISOString(),
    };

    this.broadcast("report_status_change", payload);
    return payload;
  }

  /**
   * Checks a list of reports and emits SLA alerts for all imminent or breached cases.
   */
  evaluateAndBroadcastQueueAlerts(reports) {
    const alerts = [];
    if (!Array.isArray(reports)) return alerts;

    for (const report of reports) {
      if (report.status === "approved" || report.status === "rejected") continue;
      const sla = calculateReportSla(report);
      if (sla && (sla.isOverdue || sla.urgencyLevel === "critical_imminent")) {
        const alert = this.broadcastSlaAlert(report, sla);
        alerts.push(alert);
      }
    }
    return alerts;
  }
}

// Export singleton instance
export const realtimeEventManager = new RealtimeEventManager();

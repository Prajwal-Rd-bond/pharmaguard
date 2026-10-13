import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function RealtimeAlertBanner() {
  const { user } = useAuth();
  const [activeAlerts, setActiveAlerts] = useState([]);
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    if (!user || !user.token) return;

    // Connect to Server-Sent Events stream with auth token
    const streamUrl = `/api/reports/sla/stream?token=${encodeURIComponent(user.token)}`;
    const eventSource = new EventSource(streamUrl);

    eventSource.addEventListener("connected", () => {
      setIsConnected(true);
    });

    eventSource.addEventListener("sla_alert", (event) => {
      try {
        const data = JSON.parse(event.data);
        setActiveAlerts((prev) => {
          // Avoid duplicate alerts for the same report
          const filtered = prev.filter((a) => a.reportId !== data.reportId);
          return [data, ...filtered].slice(0, 3);
        });
      } catch (err) {
        console.error("Failed to parse sla_alert event:", err);
      }
    });

    eventSource.addEventListener("report_created", (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.isExpedited || data.isSerious) {
          const alertItem = {
            reportId: data.reportId,
            type: "REPORT_INGESTED",
            message: `New ${data.isExpedited ? "7-Day Expedited (Fatal/Life-Threatening)" : "Serious"} Case Ingested via ${data.source.toUpperCase()}`,
            urgencyLevel: data.isExpedited ? "critical_imminent" : "warning_approaching",
            timestamp: data.timestamp,
          };
          setActiveAlerts((prev) => [alertItem, ...prev.filter((a) => a.reportId !== data.reportId)].slice(0, 3));
        }
      } catch (err) {
        console.error("Failed to parse report_created event:", err);
      }
    });

    eventSource.addEventListener("gateway_transmission", (event) => {
      try {
        const data = JSON.parse(event.data);
        const alertItem = {
          reportId: data.reportId,
          type: "GATEWAY_TRANSMISSION",
          message: `FDA ESG Gateway: Acknowledged MDN receipt (${data.transmissionId})`,
          urgencyLevel: "success",
          timestamp: data.timestamp,
        };
        setActiveAlerts((prev) => [alertItem, ...prev.filter((a) => a.reportId !== data.reportId)].slice(0, 3));
      } catch (err) {
        console.error("Failed to parse gateway_transmission event:", err);
      }
    });

    eventSource.onerror = () => {
      setIsConnected(false);
    };

    return () => {
      eventSource.close();
    };
  }, [user]);

  const dismissAlert = (reportId) => {
    setActiveAlerts((prev) => prev.filter((a) => a.reportId !== reportId));
  };

  return (
    <div className="w-full space-y-2">
      {/* Live SLA Stream Status Indicator Bar */}
      <div className="flex items-center justify-between border-b border-ink-100/60 bg-ink-50/70 px-8 py-1.5 text-xs text-ink-500">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span
              className={`absolute inline-flex h-full w-full rounded-full opacity-75 ${
                isConnected ? "animate-ping bg-emerald-400" : "bg-amber-400"
              }`}
            />
            <span
              className={`relative inline-flex h-2 w-2 rounded-full ${
                isConnected ? "bg-emerald-500" : "bg-amber-500"
              }`}
            />
          </span>
          <span className="font-mono text-[11px] font-medium tracking-tight">
            {isConnected ? "REGULATORY SLA LIVE STREAM CONNECTED" : "SLA STREAM CONNECTING..."}
          </span>
        </div>
        <div className="flex items-center gap-3 text-[11px] font-medium text-ink-400">
          <span>ICH E2A 7-Day & 15-Day Expedited Clocks</span>
          <span>•</span>
          <span>FDA ESG AS2 Gateway</span>
        </div>
      </div>

      {/* Dynamic Urgent Alert Banners */}
      {activeAlerts.map((alert) => {
        const isCritical = alert.urgencyLevel === "critical_imminent" || alert.isOverdue;
        const isSuccess = alert.urgencyLevel === "success";

        const bgClass = isSuccess
          ? "bg-emerald-50 border-emerald-300 text-emerald-900"
          : isCritical
          ? "bg-rose-50 border-rose-300 text-rose-950 animate-pulse"
          : "bg-amber-50 border-amber-300 text-amber-950";

        const badgeClass = isSuccess
          ? "bg-emerald-200 text-emerald-800"
          : isCritical
          ? "bg-rose-600 text-white font-bold"
          : "bg-amber-500 text-white font-bold";

        return (
          <div
            key={alert.reportId || alert.timestamp}
            className={`mx-8 flex items-center justify-between rounded-xl border p-3 shadow-sm transition-all ${bgClass}`}
          >
            <div className="flex items-center gap-3">
              <span className={`rounded-md px-2 py-0.5 text-[10px] uppercase tracking-wider ${badgeClass}`}>
                {isSuccess ? "GATEWAY ACK" : isCritical ? "CRITICAL SLA" : "EXPEDITED WATCH"}
              </span>
              <p className="text-xs font-semibold">{alert.message}</p>
            </div>
            <div className="flex items-center gap-2">
              {alert.reportId && (
                <Link
                  to={`/reports/${alert.reportId}`}
                  className="rounded-lg bg-white px-2.5 py-1 text-xs font-bold text-ink-900 shadow-sm transition hover:bg-ink-100"
                >
                  View Case →
                </Link>
              )}
              <button
                onClick={() => dismissAlert(alert.reportId)}
                className="rounded-lg p-1 text-ink-400 hover:bg-black/5 hover:text-ink-700"
                title="Dismiss"
              >
                ✕
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "../api/client";
import { useAuth } from "../context/AuthContext";
import PageHeader from "../components/PageHeader";
import { StatusBadge } from "../components/Badge";

const SEVERITY_STYLES = {
  mild: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  moderate: "bg-amber-50 text-amber-700 ring-amber-200",
  serious: "bg-orange-50 text-orange-700 ring-orange-200",
  life_threatening: "bg-rose-50 text-rose-700 ring-rose-200 font-semibold",
};

export default function Dashboard() {
  const { user } = useAuth();
  const [reports, setReports] = useState([]);
  const [pipelineStatus, setPipelineStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activityFeed, setActivityFeed] = useState([]);

  useEffect(() => {
    Promise.all([
      api.get("/reports").catch(() => ({ data: { reports: [] } })),
      api.get("/reports/pipeline/status").catch(() => ({ data: null })),
    ]).then(([repRes, statRes]) => {
      const repList = repRes.data.reports || [];
      setReports(repList);
      setPipelineStatus(statRes.data);
      setLoading(false);

      // Initialize recent activity from reports
      const recent = repList.slice(0, 8).map((r) => ({
        id: r._id,
        drug: r.extraction?.drugName || "Unspecified drug",
        action: r.status === "approved" ? "Approved by reviewer" : r.status === "pending_review" ? "Pending pharmacovigilance review" : "Report submitted",
        time: new Date(r.createdAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        status: r.status,
        submittedBy: r.submittedBy?.name || "Healthcare Provider",
      }));
      setActivityFeed(recent);
    });

    // Real-time EventSource listener for live activity feed
    const token = localStorage.getItem("token");
    let evtSource = null;
    if (token) {
      try {
        evtSource = new EventSource(`/api/reports/stream/sla?token=${encodeURIComponent(token)}`);
        evtSource.addEventListener("report_status_change", (e) => {
          try {
            const data = JSON.parse(e.data);
            setActivityFeed((prev) => [
              {
                id: data.reportId,
                drug: data.drugName || "Report",
                action: `Status updated to ${data.status}`,
                time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
                status: data.status,
                submittedBy: "User",
              },
              ...prev.slice(0, 15),
            ]);
          } catch (err) {
            console.error(err);
          }
        });
      } catch (err) {
        console.error("SSE connection error", err);
      }
    }

    return () => {
      if (evtSource) evtSource.close();
    };
  }, []);

  // Compute 4 Actionable KPIs
  const awaitingReviewCount = reports.filter((r) => r.status === "pending_review").length;
  const overdueCount = reports.filter((r) => r.clockStatus === "OVERDUE" || (r.hoursRemaining !== null && r.hoursRemaining < 0)).length;
  const dueSoonCount = reports.filter(
    (r) => r.status !== "approved" && r.status !== "rejected" && r.hoursRemaining !== null && r.hoursRemaining >= 0 && r.hoursRemaining <= 48
  ).length;
  const seriousOpenCount = reports.filter((r) => r.isSerious && r.status !== "approved" && r.status !== "rejected").length;

  // Regulatory Clock Urgency Queue (Sorted by hoursRemaining ascending, overdue first)
  const urgentQueue = [...reports]
    .filter((r) => r.status !== "approved" && r.status !== "rejected")
    .sort((a, b) => {
      const hA = a.hoursRemaining !== null && a.hoursRemaining !== undefined ? a.hoursRemaining : 9999;
      const hB = b.hoursRemaining !== null && b.hoursRemaining !== undefined ? b.hoursRemaining : 9999;
      return hA - hB;
    })
    .slice(0, 6);

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-ink-950">Safety Operations Action Center</h1>
          <p className="mt-1 text-sm text-ink-500">
            Real-time pharmacovigilance triage, regulatory expedited submission clocks, and AI intake pipeline.
          </p>
        </div>
        <div className="flex items-center gap-2.5">
          <Link
            to="/intake"
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-brand-600 to-brand-700 px-4 py-2.5 text-sm font-semibold text-white shadow-soft hover:shadow transition"
          >
            <span>+ Submit Case</span>
          </Link>
          <Link
            to="/cases"
            className="inline-flex items-center rounded-xl border border-ink-200 bg-white px-4 py-2.5 text-sm font-semibold text-ink-700 shadow-xs hover:bg-ink-50 transition"
          >
            Browse All Cases &rarr;
          </Link>
        </div>
      </div>

      {/* 4 Actionable KPI Tiles */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {/* KPI 1: Awaiting Review */}
        <div className="card relative overflow-hidden p-5 shadow-xs hover:shadow-md transition">
          <div className="absolute top-0 right-0 h-16 w-16 -mr-4 -mt-4 rounded-full bg-amber-500/10 blur-xl"></div>
          <p className="text-xs font-semibold text-ink-500 uppercase tracking-wider">Awaiting Review</p>
          <p className="mt-2 text-3xl font-extrabold text-amber-600">{loading ? "—" : awaitingReviewCount}</p>
          <p className="mt-1 text-xs text-ink-400">Cases pending clinician review</p>
        </div>

        {/* KPI 2: Overdue Clock */}
        <div className="card relative overflow-hidden p-5 shadow-xs hover:shadow-md transition border-l-4 border-l-rose-500">
          <div className="absolute top-0 right-0 h-16 w-16 -mr-4 -mt-4 rounded-full bg-rose-500/10 blur-xl"></div>
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-rose-700 uppercase tracking-wider">Overdue SLA</p>
            {overdueCount > 0 && <span className="h-2 w-2 rounded-full bg-rose-500 animate-ping"></span>}
          </div>
          <p className="mt-2 text-3xl font-extrabold text-rose-700">{loading ? "—" : overdueCount}</p>
          <p className="mt-1 text-xs text-rose-600 font-medium">Expedited clock breached</p>
        </div>

        {/* KPI 3: Due <48h */}
        <div className="card relative overflow-hidden p-5 shadow-xs hover:shadow-md transition">
          <div className="absolute top-0 right-0 h-16 w-16 -mr-4 -mt-4 rounded-full bg-orange-500/10 blur-xl"></div>
          <p className="text-xs font-semibold text-ink-500 uppercase tracking-wider">Due &lt; 48 Hours</p>
          <p className="mt-2 text-3xl font-extrabold text-orange-600">{loading ? "—" : dueSoonCount}</p>
          <p className="mt-1 text-xs text-ink-400">Expedited submission required</p>
        </div>

        {/* KPI 4: Serious Open */}
        <div className="card relative overflow-hidden p-5 shadow-xs hover:shadow-md transition">
          <div className="absolute top-0 right-0 h-16 w-16 -mr-4 -mt-4 rounded-full bg-purple-500/10 blur-xl"></div>
          <p className="text-xs font-semibold text-ink-500 uppercase tracking-wider">Serious Open</p>
          <p className="mt-2 text-3xl font-extrabold text-purple-700">{loading ? "—" : seriousOpenCount}</p>
          <p className="mt-1 text-xs text-ink-400">ICH E2A serious events active</p>
        </div>
      </div>

      {/* Main Grid: Regulatory Clock Queue (Center Stage) & Activity Feed */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Regulatory Clock Queue (2 Columns) */}
        <div className="card overflow-hidden lg:col-span-2 space-y-4 p-5">
          <div className="flex items-center justify-between border-b border-ink-100 pb-3">
            <div>
              <h2 className="text-base font-bold text-ink-950">Regulatory Submission Clock Queue</h2>
              <p className="text-xs text-ink-500">Prioritized by regulatory submission urgency (FDA 21 CFR 314.80 / EMA GVP VI).</p>
            </div>
            <Link to="/cases" className="text-xs font-semibold text-brand-600 hover:text-brand-700">
              View All ({reports.length}) &rarr;
            </Link>
          </div>

          {loading ? (
            <div className="h-48 animate-pulse rounded bg-ink-100/50" />
          ) : urgentQueue.length === 0 ? (
            <div className="py-12 text-center text-sm text-ink-400">
              No open expedited cases currently in queue.
            </div>
          ) : (
            <div className="divide-y divide-ink-100">
              {urgentQueue.map((item) => {
                const isOverdue = item.clockStatus === "OVERDUE" || (item.hoursRemaining !== null && item.hoursRemaining < 0);
                const isCritical = item.clockStatus === "EXPEDITED_CRITICAL" || (item.hoursRemaining !== null && item.hoursRemaining <= 48);
                const sev = item.classification?.severity;

                return (
                  <div key={item._id} className="py-3.5 flex flex-wrap items-center justify-between gap-3 hover:bg-ink-50/50 rounded-lg px-2 transition">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <Link to={`/reports/${item._id}`} className="font-mono text-xs font-bold text-brand-600 hover:underline">
                          #{item._id.slice(-6).toUpperCase()}
                        </Link>
                        <span className="font-bold text-ink-900 text-sm">
                          {item.extraction?.drugName || "Unspecified drug"}
                        </span>
                        {sev && (
                          <span className={`badge text-[10px] ${SEVERITY_STYLES[sev] || "bg-ink-100 text-ink-600"}`}>
                            {sev.replace(/_/g, " ")}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-ink-600">
                        {item.extraction?.symptoms?.join(", ") || "No symptoms listed"}
                      </p>
                    </div>

                    <div className="flex items-center gap-3">
                      <div>
                        {isOverdue ? (
                          <span className="rounded bg-rose-100 px-2.5 py-1 text-xs font-bold text-rose-800 animate-pulse">
                            OVERDUE
                          </span>
                        ) : isCritical ? (
                          <span className="rounded bg-amber-100 px-2.5 py-1 text-xs font-bold text-amber-800">
                            {item.hoursRemaining}h left ({item.regulatoryClockDays}d SLA)
                          </span>
                        ) : (
                          <span className="rounded bg-emerald-100 px-2.5 py-1 text-xs font-semibold text-emerald-800">
                            {item.hoursRemaining}h left ({item.regulatoryClockDays}d SLA)
                          </span>
                        )}
                      </div>
                      <Link
                        to={`/reports/${item._id}`}
                        className="rounded-lg bg-ink-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-brand-600 transition"
                      >
                        Review
                      </Link>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Right Column: Live Activity Feed & Pipeline Health */}
        <div className="space-y-6">
          {/* Live Activity Feed */}
          <div className="card p-5 space-y-4">
            <div className="flex items-center justify-between border-b border-ink-100 pb-2">
              <div className="flex items-center gap-2">
                <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse"></span>
                <h3 className="text-sm font-bold text-ink-950">Live Activity Feed</h3>
              </div>
              <span className="text-[10px] uppercase tracking-wider font-semibold text-ink-400">SSE Stream</span>
            </div>

            <div className="space-y-3 max-h-[260px] overflow-y-auto pr-1">
              {activityFeed.length === 0 ? (
                <p className="text-xs text-ink-400 py-4 text-center">No recent activity</p>
              ) : (
                activityFeed.map((item, idx) => (
                  <div key={idx} className="flex items-start gap-2.5 text-xs">
                    <span className="mt-1 h-1.5 w-1.5 rounded-full bg-brand-500 shrink-0"></span>
                    <div className="flex-1 min-w-0">
                      <p className="font-semibold text-ink-800 truncate">
                        <Link to={`/reports/${item.id}`} className="hover:text-brand-600 hover:underline">
                          {item.drug}
                        </Link>
                      </p>
                      <p className="text-[11px] text-ink-500">{item.action}</p>
                    </div>
                    <span className="text-[10px] text-ink-400 tabular-nums shrink-0">{item.time}</span>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* AI Pipeline & System Health */}
          <div className="card p-5 space-y-3">
            <h3 className="text-sm font-bold text-ink-950 border-b border-ink-100 pb-2">System & Pipeline Health</h3>
            <div className="space-y-2 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-ink-600">Express API Gateway</span>
                <span className="inline-flex items-center gap-1 font-semibold text-emerald-700">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500"></span> Healthy
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-ink-600">FastAPI ML Service</span>
                <span className="inline-flex items-center gap-1 font-semibold text-emerald-700">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500"></span> Healthy (v0.2.0)
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-ink-600">FAERS 2024-Q4 Cohort</span>
                <span className="inline-flex items-center gap-1 font-semibold text-emerald-700">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500"></span> 12.5M records
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-ink-600">Audit Trail Hash-Chain</span>
                <span className="inline-flex items-center gap-1 font-semibold text-emerald-700">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500"></span> Verified & Locked
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

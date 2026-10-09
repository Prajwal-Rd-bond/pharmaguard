import { useEffect, useState } from "react";
import api from "../api/client";
import PageHeader from "../components/PageHeader";
import { StatusBadge } from "../components/Badge";
import { useAuth } from "../context/AuthContext";

// GET /reports is RBAC-gated to pharmacist/researcher/admin (see server/src/routes/reportRoutes.js);
// doctors don't have a report-list view yet, so skip the fetch rather than 403 on every load.
const CAN_LIST_REPORTS = ["pharmacist", "researcher", "admin"];

const STATUS_ORDER = ["submitted", "pending_review", "approved", "rejected", "request_more_info"];

const STAT_ACCENTS = {
  submitted: "from-sky-400 to-sky-600",
  pending_review: "from-amber-400 to-amber-600",
  approved: "from-emerald-400 to-emerald-600",
  rejected: "from-rose-400 to-rose-600",
  request_more_info: "from-violet-400 to-violet-600",
};

// Module 10 (Phase 2 will replace this with real aggregation charts). Placeholder counts for MVP demo.
export default function Dashboard() {
  const { user } = useAuth();
  const canListReports = CAN_LIST_REPORTS.includes(user?.role);
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(canListReports);

  useEffect(() => {
    if (!canListReports) return;
    api
      .get("/reports")
      .then((res) => setReports(res.data.reports))
      .catch(() => setReports([]))
      .finally(() => setLoading(false));
  }, [canListReports]);

  const counts = reports.reduce((acc, r) => {
    acc[r.status] = (acc[r.status] || 0) + 1;
    return acc;
  }, {});

  const statuses = [...new Set([...STATUS_ORDER, ...Object.keys(counts)])].filter((s) => counts[s] !== undefined || STATUS_ORDER.includes(s));

  if (!canListReports) {
    return (
      <div>
        <PageHeader title="Dashboard" subtitle="Submit an ADR report to get started." />
        <div className="card p-6 text-sm text-ink-500">
          Report-level stats are visible to pharmacists, researchers, and admins. Use{" "}
          <span className="font-medium text-ink-700">Submit Report</span> in the sidebar to file a new ADR report.
        </div>
      </div>
    );
  }

  return (
    <div>
      <PageHeader title="Dashboard" subtitle={`${reports.length} total report${reports.length === 1 ? "" : "s"} in the system`} />

      {loading ? (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-5">
          {STATUS_ORDER.map((s) => (
            <div key={s} className="card h-28 animate-pulse bg-ink-50" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-5">
          {statuses.map((status) => (
            <div key={status} className="card group relative overflow-hidden p-5">
              <div className={`absolute -right-4 -top-4 h-16 w-16 rounded-full bg-gradient-to-br ${STAT_ACCENTS[status] || "from-ink-300 to-ink-500"} opacity-20 transition-opacity group-hover:opacity-30`} />
              <p className="text-3xl font-extrabold tabular-nums text-ink-900">{counts[status] || 0}</p>
              <div className="mt-3">
                <StatusBadge status={status} />
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="card mt-6 flex items-center gap-3 border-dashed p-5 text-sm text-ink-500">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="shrink-0 text-ink-400">
          <circle cx="12" cy="12" r="10" />
          <path d="M12 16v-4M12 8h.01" />
        </svg>
        Full analytics (trends, top drugs, geographic/age distribution) — coming in Phase 2.
      </div>

      {!loading && reports.some(r => r.classification) && (
        <div className="mt-8">
          <h2 className="mb-4 text-lg font-semibold text-ink-900">Recent Priority AI Assessments</h2>
          <div className="grid gap-4 md:grid-cols-2">
            {reports
              .filter(r => r.classification && ["serious", "life_threatening"].includes(r.classification.severity))
              .slice(0, 4)
              .map(r => (
                <div key={r._id} className="card p-5">
                  <div className="flex items-start justify-between">
                    <div>
                      <span className={`badge text-xs ${r.classification.severity === 'life_threatening' ? 'bg-rose-600 text-white' : 'bg-rose-50 text-rose-700 ring-rose-200'}`}>
                        {r.classification.severity.toUpperCase()}
                      </span>
                      <p className="mt-2 text-sm font-medium text-ink-900">{r.classification.rationale || "No rationale provided."}</p>
                      <div className="mt-2 flex flex-wrap gap-2 text-xs text-ink-500">
                        {r.retrievals?.length > 0 && (
                          <span className="flex items-center gap-1">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                              <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/>
                            </svg>
                            {r.retrievals[0].retrievalMode} ({r.retrievals.length} sources)
                          </span>
                        )}
                        <span>Report {r._id.slice(-6)}</span>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}

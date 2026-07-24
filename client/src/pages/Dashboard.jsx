import { useEffect, useState } from "react";
import api from "../api/client";
import PageHeader from "../components/PageHeader";
import { StatusBadge } from "../components/Badge";

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
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/reports").then((res) => {
      setReports(res.data.reports);
      setLoading(false);
    });
  }, []);

  const counts = reports.reduce((acc, r) => {
    acc[r.status] = (acc[r.status] || 0) + 1;
    return acc;
  }, {});

  const statuses = [...new Set([...STATUS_ORDER, ...Object.keys(counts)])].filter((s) => counts[s] !== undefined || STATUS_ORDER.includes(s));

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
    </div>
  );
}

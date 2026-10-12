import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "../api/client";
import PageHeader from "../components/PageHeader";
import { StatusBadge } from "../components/Badge";

const SEVERITY_STYLES = {
  mild: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  moderate: "bg-amber-50 text-amber-700 ring-amber-200",
  serious: "bg-orange-50 text-orange-700 ring-orange-200",
  life_threatening: "bg-rose-50 text-rose-700 ring-rose-200 font-semibold",
};

export default function ReviewQueue() {
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/reports").then((res) => {
      setReports(res.data.reports || []);
      setLoading(false);
    });
  }, []);

  return (
    <div>
      <PageHeader
        title="Review & Regulatory Triage Queue"
        subtitle="Prioritized queue with ICH E2A seriousness classification and 7-day / 15-day expedited reporting clocks."
      />

      <div className="table-shell">
        <table>
          <thead>
            <tr>
              <th>Priority / Severity</th>
              <th>Regulatory Clock (SLA)</th>
              <th>Suspect Drug & Symptoms</th>
              <th>Status</th>
              <th>Submitted</th>
              <th>Source</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={7} className="py-8 text-center text-ink-400">
                  Loading reports…
                </td>
              </tr>
            )}
            {!loading && reports.length === 0 && (
              <tr>
                <td colSpan={7} className="py-8 text-center text-ink-400">
                  No reports in the queue.
                </td>
              </tr>
            )}
            {reports.map((r) => {
              const sev = r.classification?.severity;
              const clockDays = r.regulatoryClockDays || 15;
              const hours = r.hoursRemaining;
              const isOverdue = r.clockStatus === "OVERDUE";
              const isCritical = r.clockStatus === "EXPEDITED_CRITICAL";

              return (
                <tr key={r._id} className={sev === "life_threatening" ? "bg-rose-50/20" : ""}>
                  <td>
                    {sev ? (
                      <span className={`badge text-xs ${SEVERITY_STYLES[sev] || "bg-ink-100 text-ink-600"}`}>
                        {sev.replace(/_/g, " ")}
                      </span>
                    ) : (
                      <span className="text-xs text-ink-400 italic">Unprocessed</span>
                    )}
                    {r.ichE2ACriteria?.length > 0 && (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {r.ichE2ACriteria.map((crit, idx) => (
                          <span
                            key={idx}
                            className="rounded bg-rose-100/80 px-1.5 py-0.2 text-[9px] font-bold text-rose-800"
                          >
                            {crit.replace(/_/g, " ")}
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td>
                    {isOverdue ? (
                      <span className="inline-flex items-center gap-1 rounded bg-rose-100 px-2 py-0.5 text-xs font-bold text-rose-700 animate-pulse">
                        &bull; OVERDUE
                      </span>
                    ) : isCritical ? (
                      <span className="inline-flex items-center gap-1 rounded bg-amber-100 px-2 py-0.5 text-xs font-bold text-amber-800">
                        &bull; {hours}h left ({clockDays}d SLA)
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-700">
                        {hours}h left ({clockDays}d SLA)
                      </span>
                    )}
                  </td>
                  <td>
                    <div className="font-semibold text-ink-900">
                      {r.extraction?.drugName || <span className="text-ink-400 italic">Pending extraction</span>}
                    </div>
                    {r.extraction?.symptoms?.length > 0 && (
                      <div className="text-xs text-ink-500 mt-0.5 line-clamp-1">
                        {r.extraction.symptoms.join(", ")}
                      </div>
                    )}
                  </td>
                  <td>
                    <StatusBadge status={r.status} />
                  </td>
                  <td className="text-xs text-ink-500">{new Date(r.createdAt).toLocaleString()}</td>
                  <td className="capitalize text-xs text-ink-600">{r.source?.replace(/_/g, " ")}</td>
                  <td className="text-right">
                    <Link to={`/reports/${r._id}`} className="btn-secondary text-xs py-1.5 px-3">
                      Review →
                    </Link>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

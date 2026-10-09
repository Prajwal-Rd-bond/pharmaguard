import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "../api/client";
import PageHeader from "../components/PageHeader";
import { StatusBadge } from "../components/Badge";

// Module 2/9 — Pharmacist triage queue.
export default function ReviewQueue() {
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/reports").then((res) => {
      setReports(res.data.reports);
      setLoading(false);
    });
  }, []);

  return (
    <div>
      <PageHeader title="Review Queue" subtitle="Triage submitted ADR reports and track them through the approval workflow." />

      <div className="table-shell">
        <table>
          <thead>
            <tr>
              <th>Submitted</th>
              <th>Source</th>
              <th>Status</th>
              <th>AI Assessment</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={5} className="py-8 text-center text-ink-400">
                  Loading reports…
                </td>
              </tr>
            )}
            {!loading && reports.length === 0 && (
              <tr>
                <td colSpan={5} className="py-8 text-center text-ink-400">
                  No reports in the queue.
                </td>
              </tr>
            )}
            {reports.map((r) => (
              <tr key={r._id}>
                <td className="text-ink-500">{new Date(r.createdAt).toLocaleString()}</td>
                <td className="capitalize text-ink-700">{r.source?.replace(/_/g, " ")}</td>
                <td>
                  <StatusBadge status={r.status} />
                </td>
                <td>
                  {r.classification ? (
                    <div className="flex flex-col gap-1 text-xs">
                       <span className="font-semibold text-ink-700">{r.classification.severity.toUpperCase()}</span>
                       {r.classification.rationale && (
                         <span className="text-ink-500 truncate max-w-xs" title={r.classification.rationale}>
                           {r.classification.rationale}
                         </span>
                       )}
                       {r.retrievals?.length > 0 && (
                          <span className="text-ink-400">
                             Evidence: {r.retrievals[0].retrievalMode} ({r.retrievals.length} sources)
                          </span>
                       )}
                    </div>
                  ) : (
                    <span className="text-ink-400 text-xs italic">Pending Pipeline</span>
                  )}
                </td>
                <td className="text-right">
                  <Link to={`/reports/${r._id}`} className="btn-secondary">
                    Open →
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

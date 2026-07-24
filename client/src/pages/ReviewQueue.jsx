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
              <th />
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={4} className="py-8 text-center text-ink-400">
                  Loading reports…
                </td>
              </tr>
            )}
            {!loading && reports.length === 0 && (
              <tr>
                <td colSpan={4} className="py-8 text-center text-ink-400">
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

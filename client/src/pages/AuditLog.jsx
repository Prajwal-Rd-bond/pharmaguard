import { useEffect, useState } from "react";
import api from "../api/client";
import PageHeader from "../components/PageHeader";

// Module 12 — read-only audit trail view.
export default function AuditLog() {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/audit-logs").then((res) => {
      setLogs(res.data.logs);
      setLoading(false);
    });
  }, []);

  return (
    <div>
      <PageHeader title="Audit Log" subtitle="Read-only trail of every action taken by users and the AI pipeline." />

      <div className="table-shell">
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Actor</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={3} className="py-8 text-center text-ink-400">
                  Loading audit trail…
                </td>
              </tr>
            )}
            {!loading && logs.length === 0 && (
              <tr>
                <td colSpan={3} className="py-8 text-center text-ink-400">
                  No log entries yet.
                </td>
              </tr>
            )}
            {logs.map((l) => (
              <tr key={l._id}>
                <td className="whitespace-nowrap text-ink-500">{new Date(l.createdAt).toLocaleString()}</td>
                <td>
                  {l.actorType === "ai_pipeline" ? (
                    <span className="badge bg-violet-50 text-violet-700 ring-violet-200">AI pipeline</span>
                  ) : (
                    <span className="font-medium text-ink-800">{l.actor?.name || "system"}</span>
                  )}
                </td>
                <td className="text-ink-700">{l.action}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

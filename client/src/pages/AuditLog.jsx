import { useEffect, useState } from "react";
import api from "../api/client";
import PageHeader from "../components/PageHeader";

export default function AuditLog() {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [verification, setVerification] = useState(null);
  const [verifying, setVerifying] = useState(false);

  useEffect(() => {
    api.get("/audit-logs").then((res) => {
      setLogs(res.data.logs);
      setLoading(false);
    });
  }, []);

  async function verifyIntegrity() {
    setVerifying(true);
    try {
      const res = await api.get("/audit-logs/verify");
      setVerification(res.data);
    } catch {
      setVerification({ valid: false, reason: "Verification request failed" });
    } finally {
      setVerifying(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Tamper-Evident Audit Trail"
        subtitle="Cryptographically hash-chained immutable log of every action taken by users and AI pipeline models."
        action={
          <button
            onClick={verifyIntegrity}
            disabled={verifying}
            className="btn-secondary flex items-center gap-2 text-xs"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
            {verifying ? "Auditing Hash Chain…" : "Verify Chain Integrity"}
          </button>
        }
      />

      {/* Verification status banner */}
      {verification && (
        <div
          className={`rounded-xl border p-4 text-xs font-medium flex items-center justify-between ${
            verification.valid
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-rose-200 bg-rose-50 text-rose-800"
          }`}
        >
          <div className="flex items-center gap-2">
            <span className="text-base">{verification.valid ? "🛡️" : "⚠️"}</span>
            <span>
              {verification.valid
                ? `Cryptographic Audit Chain Intact: All ${verification.totalRecords} records verified against SHA-256 genesis.`
                : `Tamper Alert: ${verification.reason}`}
            </span>
          </div>
          <button
            onClick={() => setVerification(null)}
            className="text-ink-400 hover:text-ink-600 underline"
          >
            Dismiss
          </button>
        </div>
      )}

      <div className="table-shell">
        <table>
          <thead>
            <tr>
              <th>Timestamp</th>
              <th>Actor</th>
              <th>Action</th>
              <th>Hash Fingerprint</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={4} className="py-8 text-center text-ink-400 text-xs">
                  Loading cryptographic audit trail…
                </td>
              </tr>
            )}
            {!loading && logs.length === 0 && (
              <tr>
                <td colSpan={4} className="py-8 text-center text-ink-400 text-xs">
                  No log entries yet.
                </td>
              </tr>
            )}
            {logs.map((l) => (
              <tr key={l._id}>
                <td className="whitespace-nowrap text-ink-500 text-xs">
                  {new Date(l.createdAt).toLocaleString()}
                </td>
                <td className="text-xs">
                  {l.actorType === "ai_pipeline" ? (
                    <span className="badge bg-violet-50 text-violet-700 ring-violet-200">
                      AI Pipeline
                    </span>
                  ) : (
                    <span className="font-semibold text-ink-800">{l.actor?.name || "System"}</span>
                  )}
                </td>
                <td className="font-mono text-xs text-ink-700">{l.action}</td>
                <td className="font-mono text-[11px] text-ink-400">
                  {l.hash ? `${l.hash.slice(0, 16)}…` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}


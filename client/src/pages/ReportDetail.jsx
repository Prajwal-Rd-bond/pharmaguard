import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import api from "../api/client";
import PageHeader from "../components/PageHeader";
import { StatusBadge } from "../components/Badge";

// Modules 4/5/6/7/8/9 — extraction, classification, evidence, and the approval workflow, in one view.
export default function ReportDetail() {
  const { id } = useParams();
  const [data, setData] = useState(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    const res = await api.get(`/reports/${id}`);
    setData(res.data);
  }

  useEffect(() => {
    load();
  }, [id]);

  async function runPipeline() {
    setBusy(true);
    try {
      await api.post(`/reports/${id}/run-pipeline`);
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function review(action) {
    setBusy(true);
    try {
      await api.post(`/reports/${id}/review`, { action, comment });
      setComment("");
      await load();
    } finally {
      setBusy(false);
    }
  }

  if (!data) {
    return (
      <div className="flex h-64 items-center justify-center text-ink-400">
        <span className="animate-pulse">Loading report…</span>
      </div>
    );
  }

  const { report, extraction, classification, retrievals } = data;
  const severityStyles = {
    mild: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    moderate: "bg-amber-50 text-amber-700 ring-amber-200",
    serious: "bg-rose-50 text-rose-700 ring-rose-200",
    life_threatening: "bg-rose-600 text-white ring-rose-700",
  };

  return (
    <div>
      <PageHeader
        title={`Report ${report._id}`}
        subtitle={<StatusBadge status={report.status} />}
        action={
          report.status === "submitted" && (
            <button disabled={busy} onClick={runPipeline} className="btn-primary">
              {busy ? "Running…" : "Run AI pipeline"}
            </button>
          )
        }
      />

      <div className="space-y-5">
        {classification && (
          <section className="card p-6">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">ML Risk Classification</h3>
            <div className="mt-3 flex flex-wrap items-center gap-4">
              <span className={`badge text-sm ${severityStyles[classification.severity] || "bg-ink-100 text-ink-600 ring-ink-200"}`}>
                {classification.severity}
              </span>
              <div className="flex items-center gap-2">
                <div className="h-2 w-32 overflow-hidden rounded-full bg-ink-100">
                  <div
                    className="h-full rounded-full bg-brand-500"
                    style={{ width: `${Math.round(classification.confidence * 100)}%` }}
                  />
                </div>
                <span className="text-sm font-medium text-ink-600">
                  {Math.round(classification.confidence * 100)}% confidence
                </span>
              </div>
              <span className="text-xs text-ink-400">
                {classification.modelName} v{classification.modelVersion}
              </span>
            </div>
            {classification.rationale && (
              <p className="mt-3 text-sm text-ink-600">{classification.rationale}</p>
            )}
          </section>
        )}

        {extraction && (
          <section className="card p-6">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">Extracted Structured Data</h3>
            {extraction.incomplete && (
              <div className="mt-3 flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-medium text-amber-700">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="shrink-0">
                  <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
                  <path d="M12 9v4M12 17h.01" />
                </svg>
                Flagged: extraction incomplete — verify manually.
              </div>
            )}
            <pre className="mt-3 max-h-96 overflow-auto rounded-xl bg-ink-950 p-4 text-xs leading-relaxed text-brand-200">
              {JSON.stringify(extraction, null, 2)}
            </pre>
          </section>
        )}

        {retrievals?.length > 0 && (
          <section className="card p-6">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">Supporting Evidence (Explainable AI)</h3>
            <ul className="mt-3 space-y-3">
              {retrievals.map((r) => (
                <li key={r._id} className="rounded-xl border border-ink-100 bg-ink-50/60 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="badge bg-brand-50 text-brand-700 ring-brand-200">{r.sourceCollection}</span>
                    <strong className="text-sm text-ink-900">{r.title}</strong>
                    <span className="text-xs text-ink-400">similarity {r.similarityScore}</span>
                    <span className="text-xs text-ink-400">· {r.retrievalMode}</span>
                  </div>
                  <p className="mt-1.5 text-sm text-ink-600">{r.snippet}</p>
                </li>
              ))}
            </ul>
          </section>
        )}

        {report.status === "pending_review" && (
          <section className="card p-6">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">Human Approval</h3>
            <textarea
              placeholder="Reviewer comment"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              rows={3}
              className="field mt-3"
            />
            <div className="mt-3 flex gap-2">
              <button disabled={busy} onClick={() => review("approve")} className="btn-primary">
                Approve
              </button>
              <button disabled={busy} onClick={() => review("reject")} className="btn-danger">
                Reject
              </button>
              <button disabled={busy} onClick={() => review("request_more_info")} className="btn-secondary">
                Request more info
              </button>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

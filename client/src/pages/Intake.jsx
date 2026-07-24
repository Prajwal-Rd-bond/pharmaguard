import { useState } from "react";
import api from "../api/client";
import PageHeader from "../components/PageHeader";

// Module 2 — ADR Report Intake (pasted-text path; file upload wired via multipart in server routes).
export default function Intake() {
  const [rawText, setRawText] = useState("");
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setStatus(null);
    try {
      await api.post("/reports", { source: "pasted_text", rawText });
      setStatus({ tone: "success", text: "Report submitted for processing." });
      setRawText("");
    } catch (err) {
      setStatus({ tone: "error", text: err.response?.data?.error || "Submission failed." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader title="Submit ADR Report" subtitle="Paste a clinical note, ADR report, or patient complaint for AI-assisted triage." />

      <form onSubmit={handleSubmit} className="card p-6">
        <label className="field-label">Report text</label>
        <textarea
          rows={12}
          className="field resize-y font-mono text-[13px] leading-relaxed"
          placeholder="Paste clinical note, ADR report, or patient complaint..."
          value={rawText}
          onChange={(e) => setRawText(e.target.value)}
          required
        />

        <div className="mt-4 flex items-center gap-3">
          <button type="submit" disabled={busy} className="btn-primary">
            {busy ? "Submitting…" : "Submit report"}
          </button>
          {status && (
            <span
              className={`text-sm font-medium ${
                status.tone === "success" ? "text-emerald-600" : "text-rose-600"
              }`}
            >
              {status.text}
            </span>
          )}
        </div>
      </form>
    </div>
  );
}

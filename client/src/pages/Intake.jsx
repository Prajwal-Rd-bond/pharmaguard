import { useState } from "react";
import api from "../api/client";
import PageHeader from "../components/PageHeader";

// Module 2 — ADR Report Intake (pasted-text path; file upload wired via multipart in server routes).
export default function Intake() {
  const [rawText, setRawText] = useState("");
  const [file, setFile] = useState(null);
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [intakeMode, setIntakeMode] = useState("paste"); // "paste" | "upload"

  function handleFileChange(e) {
    const selected = e.target.files?.[0];
    if (!selected) return;
    setFile(selected);

    // If it's a text/markdown/json document, read into editor preview
    if (selected.type.includes("text") || selected.name.endsWith(".txt") || selected.name.endsWith(".md") || selected.name.endsWith(".json")) {
      const reader = new FileReader();
      reader.onload = (event) => {
        setRawText(event.target.result || "");
      };
      reader.readAsText(selected);
    } else {
      setRawText(`[Uploaded Document: ${selected.name} (${Math.round(selected.size / 1024)} KB)]\nDocument attached for text extraction and ingestion.`);
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setStatus(null);
    try {
      if (file) {
        const formData = new FormData();
        formData.append("file", file);
        formData.append("source", file.name.endsWith(".pdf") ? "pdf" : file.name.endsWith(".docx") ? "docx" : "uploaded_file");
        formData.append("rawText", rawText);
        formData.append("originalFilename", file.name);
        await api.post("/reports", formData, {
          headers: { "Content-Type": "multipart/form-data" },
        });
      } else {
        await api.post("/reports", { source: "pasted_text", rawText });
      }
      setStatus({ tone: "success", text: "ADR Report submitted successfully for triage and pipeline execution." });
      setRawText("");
      setFile(null);
    } catch (err) {
      setStatus({ tone: "error", text: err.response?.data?.error || "Submission failed." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Submit ADR Report"
        subtitle="Submit adverse drug reaction reports via clinical notes, pasted EHR text, or document uploads."
      />

      <div className="card p-6">
        <div className="flex gap-4 border-b border-ink-100 pb-4 mb-4 text-sm font-medium">
          <button
            type="button"
            onClick={() => setIntakeMode("paste")}
            className={`pb-2 border-b-2 transition-colors ${
              intakeMode === "paste"
                ? "border-brand-600 text-brand-600 font-semibold"
                : "border-transparent text-ink-500 hover:text-ink-800"
            }`}
          >
            Paste Clinical Text
          </button>
          <button
            type="button"
            onClick={() => setIntakeMode("upload")}
            className={`pb-2 border-b-2 transition-colors ${
              intakeMode === "upload"
                ? "border-brand-600 text-brand-600 font-semibold"
                : "border-transparent text-ink-500 hover:text-ink-800"
            }`}
          >
            Upload Document (PDF / DOCX / TXT)
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          {intakeMode === "upload" && (
            <div className="mb-4">
              <label className="field-label">Select Document</label>
              <input
                type="file"
                accept=".txt,.md,.pdf,.docx,.doc"
                onChange={handleFileChange}
                className="field file:mr-4 file:py-1 file:px-3 file:rounded-md file:border-0 file:text-xs file:font-semibold file:bg-brand-50 file:text-brand-700 hover:file:bg-brand-100 cursor-pointer"
              />
              {file && (
                <p className="mt-1 text-xs text-ink-500">
                  Selected: <span className="font-semibold text-ink-800">{file.name}</span> ({Math.round(file.size / 1024)} KB)
                </p>
              )}
            </div>
          )}

          <label className="field-label">
            {intakeMode === "upload" ? "Extracted Report Text Preview / Comments" : "Clinical Note / ADR Narrative"}
          </label>
          <textarea
            rows={12}
            className="field resize-y font-mono text-[13px] leading-relaxed"
            placeholder="Paste clinical note, patient complaint, discharge summary, or medication history..."
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
    </div>
  );
}

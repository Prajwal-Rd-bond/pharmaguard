import { useState } from "react";
import api from "../api/client";
import PageHeader from "../components/PageHeader";

// Module 2 — ADR Report Intake (pasted-text path; file upload wired via multipart in server routes).
export default function Intake() {
  const [rawText, setRawText] = useState("");
  const [file, setFile] = useState(null);
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [intakeMode, setIntakeMode] = useState("paste"); // "paste" | "upload" | "fhir"

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

  function loadSampleFhir() {
    const sample = {
      resourceType: "AdverseEvent",
      id: `ae-hosp-${Math.floor(1000 + Math.random() * 9000)}`,
      actuality: "actual",
      subject: { reference: "Patient/MRN-449102", display: "Robert Miller (62M)" },
      date: new Date().toISOString(),
      event: {
        coding: [{ system: "http://hl7.org/fhir/sid/meddra", code: "10002272", display: "Anaphylactic shock" }],
        text: "Sudden onset dyspnea, hypotension, and facial edema 15 minutes post-dose.",
      },
      seriousness: {
        coding: [{ code: "life-threatening", display: "Life-Threatening" }],
      },
      suspectEntity: [
        {
          instance: {
            concept: { text: "Intravenous Amoxicillin/Clavulanate 1.2g" },
            display: "Amoxicillin/Clavulanate",
          },
        },
      ],
    };
    setRawText(JSON.stringify(sample, null, 2));
    setIntakeMode("fhir");
  }

  async function handleSimulateSmartLaunch(provider = "Epic") {
    setBusy(true);
    setStatus(null);
    try {
      const res = await api.post("/fhir/launch/simulate", { ehrProvider: provider });
      setRawText(JSON.stringify(res.data.sampleFhirResource, null, 2));
      setIntakeMode("fhir");
      setStatus({
        tone: "success",
        text: `SMART-on-FHIR launch handshake completed with simulated ${provider} EHR. Access token issued with scopes '${res.data.tokenResponse.scope}' for Patient ${res.data.patient.name} (${res.data.patient.id}). FHIR AdverseEvent payload loaded below.`,
      });
    } catch (err) {
      setStatus({ tone: "error", text: err.response?.data?.message || err.message || "Failed to simulate SMART launch." });
    } finally {
      setBusy(false);
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setStatus(null);
    try {
      if (intakeMode === "fhir") {
        let fhirJson;
        try {
          fhirJson = JSON.parse(rawText);
        } catch {
          throw new Error("Invalid JSON format. Please provide valid HL7 FHIR R4 JSON.");
        }
        const res = await api.post("/fhir/AdverseEvent", fhirJson);
        setStatus({ tone: "success", text: `FHIR AdverseEvent ingested successfully (Report ID: ${res.data.reportId || "OK"}).` });
        setRawText("");
      } else if (file) {
        const formData = new FormData();
        formData.append("file", file);
        formData.append("source", file.name.endsWith(".pdf") ? "pdf" : file.name.endsWith(".docx") ? "docx" : "uploaded_file");
        formData.append("rawText", rawText);
        formData.append("originalFilename", file.name);
        await api.post("/reports", formData, {
          headers: { "Content-Type": "multipart/form-data" },
        });
        setStatus({ tone: "success", text: "ADR Report submitted successfully for triage and pipeline execution." });
        setRawText("");
        setFile(null);
      } else {
        await api.post("/reports", { source: "pasted_text", rawText });
        setStatus({ tone: "success", text: "ADR Report submitted successfully for triage and pipeline execution." });
        setRawText("");
      }
    } catch (err) {
      setStatus({ tone: "error", text: err.response?.data?.error || err.response?.data?.issue?.[0]?.diagnostics || err.message || "Submission failed." });
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
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ink-100 pb-3 mb-4 text-sm font-medium">
          <div className="flex gap-4">
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
            <button
              type="button"
              onClick={() => setIntakeMode("fhir")}
              className={`pb-2 border-b-2 transition-colors ${
                intakeMode === "fhir"
                  ? "border-brand-600 text-brand-600 font-semibold"
                  : "border-transparent text-ink-500 hover:text-ink-800"
              }`}
            >
              HL7 FHIR R4 JSON
            </button>
          </div>
          {intakeMode === "fhir" && (
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={loadSampleFhir}
                className="text-xs bg-ink-100 text-ink-700 hover:bg-ink-200 font-semibold px-2.5 py-1 rounded"
              >
                Sample FHIR
              </button>
              <button
                type="button"
                onClick={() => handleSimulateSmartLaunch("Epic")}
                className="text-xs bg-purple-50 text-purple-700 hover:bg-purple-100 border border-purple-200 font-semibold px-2.5 py-1 rounded"
              >
                ⚡ Epic SMART Launch
              </button>
              <button
                type="button"
                onClick={() => handleSimulateSmartLaunch("Cerner")}
                className="text-xs bg-blue-50 text-blue-700 hover:bg-blue-100 border border-blue-200 font-semibold px-2.5 py-1 rounded"
              >
                ⚡ Cerner SMART Launch
              </button>
            </div>
          )}
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
            {intakeMode === "upload"
              ? "Extracted Report Text Preview / Comments"
              : intakeMode === "fhir"
              ? "HL7 FHIR R4 JSON Payload (AdverseEvent or Bundle)"
              : "Clinical Note / ADR Narrative"}
          </label>
          <textarea
            rows={12}
            className="field resize-y font-mono text-[13px] leading-relaxed"
            placeholder={
              intakeMode === "fhir"
                ? '{\n  "resourceType": "AdverseEvent",\n  "subject": { "reference": "Patient/MRN-101" },\n  "event": { "text": "Anaphylaxis" },\n  "suspectEntity": [{ "instance": { "display": "Amoxicillin" } }]\n}'
                : "Paste clinical note, patient complaint, discharge summary, or medication history..."
            }
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

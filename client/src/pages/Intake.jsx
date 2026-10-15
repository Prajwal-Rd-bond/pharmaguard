import { useState } from "react";
import api from "../api/client";
import PageHeader from "../components/PageHeader";

// Module 2 — ADR Report Intake with 3 paths: Quick Narrative, Guided Form, and FHIR R4 / SMART EHR.
export default function Intake() {
  const [intakeMode, setIntakeMode] = useState("narrative"); // "narrative" | "guided" | "fhir"
  const [rawText, setRawText] = useState("");
  const [file, setFile] = useState(null);
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);

  // Guided Form State
  const [guidedForm, setGuidedForm] = useState({
    drugName: "",
    dosage: "",
    route: "Oral",
    frequency: "Once daily",
    symptoms: "",
    onset: "",
    age: "",
    gender: "Female",
    isHospitalized: false,
    isLifeThreatening: false,
    isFatal: false,
    additionalNotes: "",
  });

  function handleFileChange(e) {
    const selected = e.target.files?.[0];
    if (!selected) return;
    setFile(selected);

    if (selected.type.includes("text") || selected.name.endsWith(".txt") || selected.name.endsWith(".md") || selected.name.endsWith(".json")) {
      const reader = new FileReader();
      reader.onload = (event) => {
        setRawText(event.target.result || "");
      };
      reader.readAsText(selected);
    } else {
      setRawText(`[Uploaded Document: ${selected.name} (${Math.round(selected.size / 1024)} KB)]\nDocument attached for automated clinical extraction.`);
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
        text: `SMART-on-FHIR handshake completed with simulated ${provider} EHR. Access token issued for Patient ${res.data.patient.name} (${res.data.patient.id}). FHIR AdverseEvent loaded below.`,
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
      if (intakeMode === "guided") {
        // Construct clinical narrative from guided form inputs
        const parts = [];
        if (guidedForm.age || guidedForm.gender) {
          parts.push(`Patient: ${guidedForm.age ? `${guidedForm.age}-year-old` : ""} ${guidedForm.gender || ""}.`);
        }
        parts.push(`Suspect medication: ${guidedForm.drugName || "Unspecified"} ${guidedForm.dosage} administered via ${guidedForm.route} (${guidedForm.frequency}).`);
        parts.push(`Adverse reaction: Patient presented with ${guidedForm.symptoms || "unspecified adverse symptoms"}.`);
        if (guidedForm.onset) {
          parts.push(`Onset: Symptoms developed ${guidedForm.onset}.`);
        }
        const seriousEvents = [];
        if (guidedForm.isHospitalized) seriousEvents.push("hospitalization in inpatient ward");
        if (guidedForm.isLifeThreatening) seriousEvents.push("life-threatening reaction requiring resuscitation");
        if (guidedForm.isFatal) seriousEvents.push("fatal event resulting in death");
        if (seriousEvents.length > 0) {
          parts.push(`Seriousness criteria: Patient experienced ${seriousEvents.join(", ")}.`);
        }
        if (guidedForm.additionalNotes) {
          parts.push(`Clinical notes: ${guidedForm.additionalNotes}`);
        }

        const compiledNarrative = parts.join(" ");
        await api.post("/reports", { source: "guided_form", rawText: compiledNarrative });
        setStatus({ tone: "success", text: "Guided ADR case submitted successfully and queued for extraction." });
        setGuidedForm({
          drugName: "",
          dosage: "",
          route: "Oral",
          frequency: "Once daily",
          symptoms: "",
          onset: "",
          age: "",
          gender: "Female",
          isHospitalized: false,
          isLifeThreatening: false,
          isFatal: false,
          additionalNotes: "",
        });
      } else if (intakeMode === "fhir") {
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
        setStatus({ tone: "success", text: "Document uploaded and submitted successfully for triage." });
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
    <div className="space-y-6">
      <PageHeader
        title="Submit ADR Report"
        subtitle="Multi-modal intake: Quick Narrative, Guided Clinician Form, or HL7 FHIR R4 EHR interoperability."
      />

      <div className="card p-6">
        {/* 3 Tab Mode Switcher */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ink-100 pb-3 mb-6 text-sm font-medium">
          <div className="flex gap-4">
            <button
              type="button"
              onClick={() => setIntakeMode("narrative")}
              className={`pb-2 border-b-2 transition-colors ${
                intakeMode === "narrative"
                  ? "border-brand-600 text-brand-600 font-semibold"
                  : "border-transparent text-ink-500 hover:text-ink-800"
              }`}
            >
              1. Quick Narrative & File
            </button>
            <button
              type="button"
              onClick={() => setIntakeMode("guided")}
              className={`pb-2 border-b-2 transition-colors ${
                intakeMode === "guided"
                  ? "border-brand-600 text-brand-600 font-semibold"
                  : "border-transparent text-ink-500 hover:text-ink-800"
              }`}
            >
              2. Guided Clinician Form
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
              3. HL7 FHIR R4 & SMART EHR
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
          {/* TAB 1: QUICK NARRATIVE & FILE */}
          {intakeMode === "narrative" && (
            <div className="space-y-4">
              <div>
                <label className="field-label">Attach Clinical Document (Optional PDF / DOCX / TXT)</label>
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

              <div>
                <label className="field-label">Clinical Note / Unstructured ADR Narrative</label>
                <textarea
                  rows={10}
                  className="field resize-y font-mono text-[13px] leading-relaxed"
                  placeholder="Paste clinical note, patient complaint, discharge summary, or medication history (e.g. 54-year-old female admitted with acute hives and facial angioedema 2 hours after starting lisinopril 20mg daily...)"
                  value={rawText}
                  onChange={(e) => setRawText(e.target.value)}
                  required
                />
              </div>
            </div>
          )}

          {/* TAB 2: GUIDED CLINICIAN FORM */}
          {intakeMode === "guided" && (
            <div className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label className="field-label">Suspect Drug Generic Name *</label>
                  <input
                    type="text"
                    required
                    value={guidedForm.drugName}
                    onChange={(e) => setGuidedForm({ ...guidedForm, drugName: e.target.value })}
                    placeholder="e.g. Amoxicillin, Lisinopril, Ciprofloxacin"
                    className="field"
                  />
                </div>
                <div>
                  <label className="field-label">Dosage & Strength</label>
                  <input
                    type="text"
                    value={guidedForm.dosage}
                    onChange={(e) => setGuidedForm({ ...guidedForm, dosage: e.target.value })}
                    placeholder="e.g. 500mg, 10mg/ml, 2 tablets"
                    className="field"
                  />
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label className="field-label">Route of Administration</label>
                  <select
                    value={guidedForm.route}
                    onChange={(e) => setGuidedForm({ ...guidedForm, route: e.target.value })}
                    className="field"
                  >
                    <option value="Oral">Oral</option>
                    <option value="Intravenous">Intravenous (IV)</option>
                    <option value="Subcutaneous">Subcutaneous</option>
                    <option value="Intramuscular">Intramuscular (IM)</option>
                    <option value="Topical">Topical</option>
                    <option value="Inhalation">Inhalation</option>
                  </select>
                </div>
                <div>
                  <label className="field-label">Dosing Frequency</label>
                  <select
                    value={guidedForm.frequency}
                    onChange={(e) => setGuidedForm({ ...guidedForm, frequency: e.target.value })}
                    className="field"
                  >
                    <option value="Once daily">Once daily</option>
                    <option value="Twice daily">Twice daily</option>
                    <option value="Three times daily">Three times daily</option>
                    <option value="Every 8 hours">Every 8 hours</option>
                    <option value="As needed (PRN)">As needed (PRN)</option>
                  </select>
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label className="field-label">Adverse Reaction Symptoms *</label>
                  <input
                    type="text"
                    required
                    value={guidedForm.symptoms}
                    onChange={(e) => setGuidedForm({ ...guidedForm, symptoms: e.target.value })}
                    placeholder="e.g. Anaphylaxis, Rash, Tendon rupture, Dizziness"
                    className="field"
                  />
                </div>
                <div>
                  <label className="field-label">Onset Duration</label>
                  <input
                    type="text"
                    value={guidedForm.onset}
                    onChange={(e) => setGuidedForm({ ...guidedForm, onset: e.target.value })}
                    placeholder="e.g. 2 hours after intake, 3 days post dose"
                    className="field"
                  />
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label className="field-label">Patient Age</label>
                  <input
                    type="number"
                    min="0"
                    max="125"
                    value={guidedForm.age}
                    onChange={(e) => setGuidedForm({ ...guidedForm, age: e.target.value })}
                    placeholder="e.g. 52"
                    className="field"
                  />
                </div>
                <div>
                  <label className="field-label">Patient Gender</label>
                  <select
                    value={guidedForm.gender}
                    onChange={(e) => setGuidedForm({ ...guidedForm, gender: e.target.value })}
                    className="field"
                  >
                    <option value="Female">Female</option>
                    <option value="Male">Male</option>
                    <option value="Other">Other</option>
                    <option value="Unknown">Unknown</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="field-label">ICH E2A Seriousness Criteria Flags</label>
                <div className="mt-1 flex flex-wrap gap-4 text-xs font-semibold text-ink-700">
                  <label className="flex items-center gap-1.5 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={guidedForm.isHospitalized}
                      onChange={(e) => setGuidedForm({ ...guidedForm, isHospitalized: e.target.checked })}
                      className="rounded text-brand-600 focus:ring-brand-500"
                    />
                    Hospitalization (Initial / Prolonged)
                  </label>
                  <label className="flex items-center gap-1.5 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={guidedForm.isLifeThreatening}
                      onChange={(e) => setGuidedForm({ ...guidedForm, isLifeThreatening: e.target.checked })}
                      className="rounded text-brand-600 focus:ring-brand-500"
                    />
                    Life-Threatening Reaction
                  </label>
                  <label className="flex items-center gap-1.5 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={guidedForm.isFatal}
                      onChange={(e) => setGuidedForm({ ...guidedForm, isFatal: e.target.checked })}
                      className="rounded text-brand-600 focus:ring-brand-500"
                    />
                    Fatal (Death)
                  </label>
                </div>
              </div>

              <div>
                <label className="field-label">Additional Clinical Details / Context</label>
                <textarea
                  rows={4}
                  value={guidedForm.additionalNotes}
                  onChange={(e) => setGuidedForm({ ...guidedForm, additionalNotes: e.target.value })}
                  placeholder="De-challenge response, concomitant medications, patient medical history..."
                  className="field"
                />
              </div>
            </div>
          )}

          {/* TAB 3: HL7 FHIR R4 JSON */}
          {intakeMode === "fhir" && (
            <div>
              <label className="field-label">HL7 FHIR R4 JSON Payload (AdverseEvent or Bundle)</label>
              <textarea
                rows={12}
                className="field resize-y font-mono text-[13px] leading-relaxed"
                placeholder='{\n  "resourceType": "AdverseEvent",\n  "subject": { "reference": "Patient/MRN-101" },\n  "event": { "text": "Anaphylaxis" },\n  "suspectEntity": [{ "instance": { "display": "Amoxicillin" } }]\n}'
                value={rawText}
                onChange={(e) => setRawText(e.target.value)}
                required
              />
            </div>
          )}

          <div className="mt-6 flex items-center gap-3">
            <button type="submit" disabled={busy} className="btn-primary">
              {busy ? "Submitting Case…" : "Submit & Run Pipeline"}
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

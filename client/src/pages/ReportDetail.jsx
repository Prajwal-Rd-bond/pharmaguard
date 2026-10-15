import { useEffect, useState, useMemo } from "react";
import { useParams, Link } from "react-router-dom";
import api from "../api/client";
import PageHeader from "../components/PageHeader";
import { StatusBadge } from "../components/Badge";

const SEVERITY_STYLES = {
  mild: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  moderate: "bg-amber-50 text-amber-700 ring-amber-200",
  serious: "bg-orange-50 text-orange-700 ring-orange-200",
  life_threatening: "bg-rose-50 text-rose-700 ring-rose-200 font-bold",
};

const NARANJO_QUESTIONS = [
  { id: "q1", question: "1. Are there previous conclusive reports on this reaction?", options: [{ label: "Yes (+1)", score: 1 }, { label: "No (0)", score: 0 }, { label: "Do not know (0)", score: 0 }] },
  { id: "q2", question: "2. Did the adverse event appear after the suspected drug was administered?", options: [{ label: "Yes (+2)", score: 2 }, { label: "No (-1)", score: -1 }, { label: "Do not know (0)", score: 0 }] },
  { id: "q3", question: "3. Did the adverse reaction improve when the drug was discontinued or specific antagonist given?", options: [{ label: "Yes (+1)", score: 1 }, { label: "No (0)", score: 0 }, { label: "Do not know (0)", score: 0 }] },
  { id: "q4", question: "4. Did the adverse reaction reappear when the drug was readministered?", options: [{ label: "Yes (+2)", score: 2 }, { label: "No (-1)", score: -1 }, { label: "Do not know (0)", score: 0 }] },
  { id: "q5", question: "5. Are there alternative causes (other than the drug) that could have caused the reaction?", options: [{ label: "Yes (-1)", score: -1 }, { label: "No (+2)", score: 2 }, { label: "Do not know (0)", score: 0 }] },
  { id: "q6", question: "6. Did the reaction appear when a placebo was given?", options: [{ label: "Yes (-1)", score: -1 }, { label: "No (+1)", score: 1 }, { label: "Do not know (0)", score: 0 }] },
  { id: "q7", question: "7. Was the drug detected in blood or fluids in toxic concentrations?", options: [{ label: "Yes (+1)", score: 1 }, { label: "No (0)", score: 0 }, { label: "Do not know (0)", score: 0 }] },
  { id: "q8", question: "8. Was the reaction more severe when dose increased, or less severe when decreased?", options: [{ label: "Yes (+1)", score: 1 }, { label: "No (0)", score: 0 }, { label: "Do not know (0)", score: 0 }] },
  { id: "q9", question: "9. Did the patient have a similar reaction to same or similar drugs previously?", options: [{ label: "Yes (+1)", score: 1 }, { label: "No (0)", score: 0 }, { label: "Do not know (0)", score: 0 }] },
  { id: "q10", question: "10. Was the adverse event confirmed by any objective clinical evidence?", options: [{ label: "Yes (+1)", score: 1 }, { label: "No (0)", score: 0 }, { label: "Do not know (0)", score: 0 }] },
];

function getNaranjoCategory(score) {
  if (score >= 9) return "Definite";
  if (score >= 5) return "Probable";
  if (score >= 1) return "Possible";
  return "Doubtful";
}

function renderHighlightedNarrative(text, drugName, symptoms, dosage, route) {
  if (!text) return <span className="text-ink-400 italic">No narrative available.</span>;

  const targets = [];
  if (drugName && drugName.trim().length > 2) {
    targets.push({ text: drugName.trim(), type: "drug" });
  }
  (symptoms || []).forEach((s) => {
    if (s && s.trim().length > 2) targets.push({ text: s.trim(), type: "symptom" });
  });
  if (dosage && dosage.trim().length > 1) {
    targets.push({ text: dosage.trim(), type: "dosage" });
  }
  if (route && route.trim().length > 2) {
    targets.push({ text: route.trim(), type: "dosage" });
  }

  if (targets.length === 0) return text;

  // Escape special regex characters and sort descending by length
  const escaped = targets
    .map((t) => t.text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .sort((a, b) => b.length - a.length);
  const regex = new RegExp(`(${escaped.join("|")})`, "gi");

  const parts = text.split(regex);
  return parts.map((part, idx) => {
    const lower = part.toLowerCase();
    const matched = targets.find((t) => t.text.toLowerCase() === lower);
    if (!matched) return part;

    if (matched.type === "drug") {
      return (
        <mark
          key={idx}
          className="rounded bg-purple-100 px-1.5 py-0.5 font-bold text-purple-900 border border-purple-200"
          title="Extracted Suspect Medication"
        >
          {part}
        </mark>
      );
    }
    if (matched.type === "symptom") {
      return (
        <mark
          key={idx}
          className="rounded bg-rose-100 px-1.5 py-0.5 font-bold text-rose-900 border border-rose-200"
          title="Extracted Adverse Event"
        >
          {part}
        </mark>
      );
    }
    return (
      <mark
        key={idx}
        className="rounded bg-sky-100 px-1.5 py-0.5 font-semibold text-sky-900 border border-sky-200"
        title="Dosage & Route"
      >
        {part}
      </mark>
    );
  });
}

export default function ReportDetail() {
  const { id } = useParams();
  const [data, setData] = useState(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [activeStep, setActiveStep] = useState("extraction"); // "extraction" | "seriousness" | "causality" | "evidence" | "gateway"
  const [showRawText, setShowRawText] = useState(false);
  const [duplicateMatches, setDuplicateMatches] = useState(null);
  const [checkingDuplicates, setCheckingDuplicates] = useState(false);
  const [gatewaySimMode, setGatewaySimMode] = useState("ack"); // "ack" | "reject" | "timeout"

  // Edit form state
  const [isEditing, setIsEditing] = useState(false);
  const [editForm, setEditForm] = useState({
    drugName: "",
    symptoms: "",
    dosage: "",
    frequency: "",
    route: "",
    severity: "",
  });

  // Interactive Naranjo state
  const [naranjoAnswers, setNaranjoAnswers] = useState({
    q1: 1,
    q2: 2,
    q3: 1,
    q4: 0,
    q5: 2,
    q6: 0,
    q7: 0,
    q8: 0,
    q9: 0,
    q10: 1,
  });

  async function load() {
    const res = await api.get(`/reports/${id}`);
    setData(res.data);
  }

  useEffect(() => {
    load();
  }, [id]);

  // Sync initial Naranjo breakdown from server causality if available
  useEffect(() => {
    if (data?.report?.causality?.naranjoBreakdown) {
      setNaranjoAnswers((prev) => ({ ...prev, ...data.report.causality.naranjoBreakdown }));
    }
  }, [data]);

  const liveNaranjoScore = useMemo(() => {
    return Object.values(naranjoAnswers).reduce((sum, val) => sum + Number(val || 0), 0);
  }, [naranjoAnswers]);

  const liveNaranjoCategory = useMemo(() => {
    return getNaranjoCategory(liveNaranjoScore);
  }, [liveNaranjoScore]);

  function startEditing() {
    setEditForm({
      drugName: data?.extraction?.drugName || "",
      symptoms: (data?.extraction?.symptoms || []).join(", "),
      dosage: data?.extraction?.dosage || "",
      frequency: data?.extraction?.frequency || "",
      route: data?.extraction?.route || "",
      severity: data?.classification?.severity || "moderate",
    });
    setIsEditing(true);
  }

  async function saveEdit(e) {
    if (e) e.preventDefault();
    setBusy(true);
    try {
      await api.post(`/reports/${id}/review`, {
        action: "edit",
        comment: comment || "Reviewer modified structured fields",
        editedFields: {
          drugName: editForm.drugName,
          symptoms: editForm.symptoms.split(",").map((s) => s.trim()).filter(Boolean),
          dosage: editForm.dosage,
          frequency: editForm.frequency,
          route: editForm.route,
          severity: editForm.severity,
        },
      });
      setIsEditing(false);
      setComment("");
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function pollUntilDone() {
    let attempts = 0;
    while (attempts < 60) {
      await new Promise((r) => setTimeout(r, 2000));
      const res = await api.get(`/reports/${id}`);
      setData(res.data);
      if (res.data?.report?.status !== "processing") break;
      attempts++;
    }
  }

  async function runPipeline() {
    setBusy(true);
    try {
      await api.post(`/reports/${id}/run-pipeline`);
      await pollUntilDone();
    } catch (err) {
      console.error("Pipeline dispatch error:", err);
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function review(action) {
    if (action === "approve" && !data?.report?.causality?.confirmedByPharmacist) {
      alert("Causality confirmation is required before approving this case for regulatory submission.");
      return;
    }
    setBusy(true);
    try {
      await api.post(`/reports/${id}/review`, { action, comment });
      setComment("");
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function handleCheckDuplicates() {
    setCheckingDuplicates(true);
    try {
      const res = await api.get(`/reports/${id}/duplicate-check`);
      setDuplicateMatches(res.data.duplicates || []);
    } catch (err) {
      console.error(err);
    } finally {
      setCheckingDuplicates(false);
    }
  }

  async function handleConfirmCausality() {
    setBusy(true);
    try {
      await api.post(`/reports/${id}/causality`, {
        confirmedByPharmacist: true,
        pharmacistNotes: comment || `Assessed using 10 Naranjo algorithm items: Score ${liveNaranjoScore} (${liveNaranjoCategory})`,
      });
      await load();
    } finally {
      setBusy(false);
    }
  }

  function downloadE2BXml() {
    window.open(`/api/reports/${id}/export/e2b`, "_blank");
  }

  function downloadFhirJson() {
    window.open(`/api/reports/${id}/export/fhir`, "_blank");
  }

  async function transmitGateway() {
    if (!data?.report?.isSerious && data?.report?.status !== "approved") {
      alert("Only approved cases or confirmed reports may be transmitted to the regulatory gateway.");
      return;
    }
    if (!window.confirm(`Transmit ICH E2B(R3) case to regulatory gateway in '${gatewaySimMode.toUpperCase()}' simulation mode?`)) return;
    setBusy(true);
    try {
      const res = await api.post(`/reports/${id}/transmit-gateway`, {
        gateway: "FDA_ESG",
        simulationMode: gatewaySimMode,
      });
      if (res.data?.ok) {
        alert(`Gateway Transmission Success!\nTransmission ID: ${res.data.gatewayTransmission?.transmissionId}\nStatus: ${res.data.receipt?.status}\nCore ID: ${res.data.receipt?.fdaCoreId || "ACK-RECEIVED"}`);
        await load();
      } else {
        alert("Gateway Transmission Rejection:\n" + JSON.stringify(res.data?.receipt?.errors || res.data));
      }
    } catch (e) {
      alert("Gateway transmission error: " + (e.response?.data?.error || e.message));
    } finally {
      setBusy(false);
    }
  }

  if (!data) {
    return (
      <div className="flex h-64 items-center justify-center text-ink-400">
        <span className="animate-pulse">Loading case report…</span>
      </div>
    );
  }

  const { report, extraction, classification, retrievals, reviews } = data;
  const summaryText = data.summary || report.summary;
  const citationCheck = report.citationVerification;
  const causality = report.causality;
  const terminology = report.terminology || extraction?.terminology;

  const clockDays = report.regulatoryClockDays || 15;
  const dueDate = report.regulatoryDueDate ? new Date(report.regulatoryDueDate) : null;
  const hoursLeft = dueDate ? Math.round((dueDate - new Date()) / 3600000) : null;
  const isOverdue = report.clockStatus === "OVERDUE" || (hoursLeft !== null && hoursLeft < 0);

  // Compute field diffs between AI extraction and latest state
  const diffChips = [];
  if (reviews?.length > 0) {
    const latestReview = reviews[reviews.length - 1];
    if (latestReview.editedFields) {
      Object.entries(latestReview.editedFields).forEach(([k, v]) => {
        diffChips.push(`${k}: ${JSON.stringify(v)}`);
      });
    }
  }

  return (
    <div className="space-y-6 pb-24">
      {/* Top Header */}
      <PageHeader
        title={`ICSR Case Report PHARMAGUARD-${report._id.slice(-6).toUpperCase()}`}
        subtitle={
          <div className="flex items-center gap-2">
            <StatusBadge status={report.status} />
            {classification?.severity && (
              <span className={`badge text-xs ${SEVERITY_STYLES[classification.severity] || "bg-ink-100 text-ink-700"}`}>
                {classification.severity.replace(/_/g, " ")}
              </span>
            )}
            {report.isSerious && (
              <span className="rounded bg-rose-100 px-2 py-0.5 text-xs font-bold text-rose-800">
                ICH E2A Serious
              </span>
            )}
          </div>
        }
        action={
          <div className="flex items-center gap-2">
            <button
              onClick={downloadFhirJson}
              className="rounded-lg border border-teal-300 bg-teal-50 px-3 py-1.5 text-xs font-semibold text-teal-800 hover:bg-teal-100 shadow-xs"
            >
              Export FHIR R4
            </button>
            <button
              onClick={downloadE2BXml}
              className="rounded-lg border border-ink-300 bg-white px-3 py-1.5 text-xs font-semibold text-ink-700 hover:bg-ink-50 shadow-xs"
            >
              Export E2B(R3) XML
            </button>
            {report.status === "submitted" && (
              <button disabled={busy} onClick={runPipeline} className="btn-primary text-xs py-1.5">
                {busy ? "Running…" : "Run AI Pipeline"}
              </button>
            )}
          </div>
        }
      />

      {/* Pipeline Status Banner */}
      {(report.status === "processing" || busy) && (
        <div className="card border-l-4 border-l-amber-500 bg-amber-50/50 p-4 animate-pulse flex items-center gap-3">
          <svg className="h-5 w-5 animate-spin text-amber-600" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
          </svg>
          <div>
            <h4 className="text-sm font-semibold text-amber-900">AI Intelligence Pipeline In Progress</h4>
            <p className="text-xs text-amber-700 mt-0.5">
              De-identifying clinical text, extracting entities, MedDRA coding, RAG evidence retrieval, and causality evaluation...
            </p>
          </div>
        </div>
      )}

      {/* 2-COLUMN MAIN LAYOUT */}
      <div className="grid gap-6 lg:grid-cols-12">
        {/* LEFT COLUMN: Narrative with In-Place Entity Highlighting & Patient Demographics (5 Columns) */}
        <div className="lg:col-span-5 space-y-6">
          {/* Narrative Viewer Card */}
          <div className="card p-5 space-y-3">
            <div className="flex items-center justify-between border-b border-ink-100 pb-3">
              <div>
                <h3 className="text-xs font-bold uppercase tracking-wider text-ink-900">Clinical Narrative Text</h3>
                <p className="text-[11px] text-ink-500">In-place highlighted clinical entities</p>
              </div>
              <button
                type="button"
                onClick={() => setShowRawText(!showRawText)}
                className="text-xs font-semibold text-brand-600 hover:text-brand-700 underline"
              >
                {showRawText ? "Show De-identified" : "Show Raw (Protected)"}
              </button>
            </div>

            {/* Highlighting Legend */}
            {!showRawText && (
              <div className="flex flex-wrap items-center gap-3 text-[11px] font-semibold text-ink-600 bg-ink-50/70 p-2 rounded-lg border border-ink-100">
                <span className="flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-purple-600"></span>
                  Suspect Drug
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-rose-600"></span>
                  Adverse Reaction
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-sky-600"></span>
                  Dose / Route
                </span>
              </div>
            )}

            {/* Narrative Box */}
            <div className="rounded-lg border border-ink-200 bg-white p-4 text-xs font-mono leading-relaxed text-ink-900 min-h-[220px] max-h-[380px] overflow-y-auto">
              {showRawText ? (
                <div className="space-y-2">
                  <span className="rounded bg-amber-100 px-2 py-0.5 text-[10px] font-bold text-amber-800">
                    RAW CLINICAL RECORD (RESTRICTED PHI)
                  </span>
                  <p className="whitespace-pre-wrap">{report.rawText}</p>
                </div>
              ) : (
                <p className="whitespace-pre-wrap">
                  {renderHighlightedNarrative(
                    report.deidentifiedText || report.rawText,
                    extraction?.drugName,
                    extraction?.symptoms,
                    extraction?.dosage,
                    extraction?.route
                  )}
                </p>
              )}
            </div>

            {/* De-identification Audit Log Inspection */}
            {report.deidentificationLog?.length > 0 && (
              <details className="text-xs text-ink-600">
                <summary className="cursor-pointer font-semibold text-brand-600 hover:underline">
                  De-identification Redaction Log ({report.deidentificationLog.length} PHI tokens redacted)
                </summary>
                <div className="mt-2 space-y-1 bg-ink-50 p-2.5 rounded-lg border border-ink-100 max-h-36 overflow-y-auto">
                  {report.deidentificationLog.map((log, idx) => (
                    <div key={idx} className="flex justify-between text-[11px]">
                      <span className="font-mono text-ink-700">{log.type}</span>
                      <span className="font-semibold text-rose-700">{log.span}</span>
                    </div>
                  ))}
                </div>
              </details>
            )}
          </div>

          {/* Patient Demographics & Reporter Information */}
          <div className="card p-5 space-y-3">
            <h3 className="text-xs font-bold uppercase tracking-wider text-ink-900 border-b border-ink-100 pb-2">
              Patient Demographics & Source Metadata
            </h3>
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div className="rounded bg-ink-50 p-2.5">
                <span className="text-ink-400 block font-medium">Age & Gender</span>
                <span className="font-bold text-ink-900">
                  {extraction?.age ? `${extraction.age} years` : "Unspecified age"} &bull; {extraction?.gender || "Unknown"}
                </span>
              </div>
              <div className="rounded bg-ink-50 p-2.5">
                <span className="text-ink-400 block font-medium">Onset Timeline</span>
                <span className="font-bold text-ink-900">{extraction?.onsetTimeline || "Unstated"}</span>
              </div>
              <div className="rounded bg-ink-50 p-2.5">
                <span className="text-ink-400 block font-medium">Report Source</span>
                <span className="font-bold text-ink-900 capitalize">{report.source?.replace(/_/g, " ") || "Clinical Note"}</span>
              </div>
              <div className="rounded bg-ink-50 p-2.5">
                <span className="text-ink-400 block font-medium">Reported By</span>
                <span className="font-bold text-ink-900">{report.submittedBy?.name || "Healthcare Provider"}</span>
              </div>
            </div>

            {extraction?.comorbidities?.length > 0 && (
              <div className="pt-2">
                <span className="text-[11px] font-semibold text-ink-500 block">Comorbidities</span>
                <p className="text-xs text-ink-800 font-medium">{extraction.comorbidities.join(", ")}</p>
              </div>
            )}
          </div>

          {/* Duplicate Case Detection */}
          <div className="card p-5 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-bold uppercase tracking-wider text-ink-900">Duplicate ICSR Detection</h3>
              <button
                type="button"
                onClick={handleCheckDuplicates}
                disabled={checkingDuplicates}
                className="text-xs font-semibold text-brand-600 hover:text-brand-700 underline"
              >
                {checkingDuplicates ? "Scanning..." : "Run Duplicate Check"}
              </button>
            </div>
            {duplicateMatches && (
              <div className="space-y-2 text-xs">
                {duplicateMatches.length === 0 ? (
                  <p className="text-ink-500 italic">No duplicate cases identified in local database.</p>
                ) : (
                  duplicateMatches.map((dup, i) => (
                    <div key={i} className="rounded bg-ink-50 p-2.5 flex items-center justify-between">
                      <div>
                        <span className="font-bold text-ink-900">{dup.overlappingDrug}</span>
                        <p className="text-[11px] text-ink-500">Overlap: {dup.overlappingSymptoms?.join(", ")}</p>
                      </div>
                      <Link to={`/reports/${dup.reportId}`} className="text-brand-600 font-semibold hover:underline">
                        View &rarr;
                      </Link>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        </div>

        {/* RIGHT COLUMN: Stepper Workflow (7 Columns) */}
        <div className="lg:col-span-7 space-y-6">
          {/* Stepper Tabs */}
          <div className="flex border-b border-ink-200 bg-white rounded-t-xl px-2">
            {[
              { id: "extraction", label: "1. Extraction" },
              { id: "seriousness", label: "2. Seriousness & SLA" },
              { id: "causality", label: "3. Causality (10 Qs)" },
              { id: "evidence", label: "4. Evidence & RAG" },
              { id: "gateway", label: "5. Gateway Status" },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveStep(tab.id)}
                className={`flex-1 border-b-2 py-3 text-xs font-bold transition text-center ${
                  activeStep === tab.id
                    ? "border-brand-600 text-brand-600"
                    : "border-transparent text-ink-500 hover:border-ink-300 hover:text-ink-700"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* STEP 1: EXTRACTION & TERMINOLOGY */}
          {activeStep === "extraction" && (
            <div className="space-y-6">
              {/* Extraction Mode Badge */}
              <div className="card p-5 space-y-4">
                <div className="flex items-center justify-between border-b border-ink-100 pb-3">
                  <div className="flex items-center gap-2">
                    <h3 className="text-sm font-bold text-ink-900">Extracted Clinical Features</h3>
                    <span
                      className={`rounded px-2 py-0.5 text-[10px] font-bold ${
                        extraction?.extractionMode === "llm_gemini"
                          ? "bg-purple-100 text-purple-800"
                          : "bg-ink-100 text-ink-700"
                      }`}
                    >
                      {extraction?.extractionMode === "llm_gemini" ? "Gemini 2.5 Pro" : "Regex Baseline"}
                    </span>
                  </div>
                  {["pending_review", "needs_more_info"].includes(report.status) && (
                    <button
                      onClick={() => (isEditing ? setIsEditing(false) : startEditing())}
                      className="rounded bg-ink-100 px-3 py-1 text-xs font-semibold text-ink-700 hover:bg-ink-200"
                    >
                      {isEditing ? "Cancel Edit" : "Edit Values"}
                    </button>
                  )}
                </div>

                {isEditing ? (
                  <form onSubmit={saveEdit} className="space-y-3 text-xs">
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="font-semibold text-ink-700 block">Suspect Drug</label>
                        <input
                          type="text"
                          value={editForm.drugName}
                          onChange={(e) => setEditForm({ ...editForm, drugName: e.target.value })}
                          className="field mt-1"
                        />
                      </div>
                      <div>
                        <label className="font-semibold text-ink-700 block">Severity</label>
                        <select
                          value={editForm.severity}
                          onChange={(e) => setEditForm({ ...editForm, severity: e.target.value })}
                          className="field mt-1"
                        >
                          <option value="mild">Mild</option>
                          <option value="moderate">Moderate</option>
                          <option value="serious">Serious</option>
                          <option value="life_threatening">Life-threatening</option>
                        </select>
                      </div>
                    </div>
                    <div>
                      <label className="font-semibold text-ink-700 block">Symptoms (comma-separated)</label>
                      <input
                        type="text"
                        value={editForm.symptoms}
                        onChange={(e) => setEditForm({ ...editForm, symptoms: e.target.value })}
                        className="field mt-1"
                      />
                    </div>
                    <div className="grid grid-cols-3 gap-3">
                      <div>
                        <label className="font-semibold text-ink-700 block">Dosage</label>
                        <input
                          type="text"
                          value={editForm.dosage}
                          onChange={(e) => setEditForm({ ...editForm, dosage: e.target.value })}
                          className="field mt-1"
                        />
                      </div>
                      <div>
                        <label className="font-semibold text-ink-700 block">Frequency</label>
                        <input
                          type="text"
                          value={editForm.frequency}
                          onChange={(e) => setEditForm({ ...editForm, frequency: e.target.value })}
                          className="field mt-1"
                        />
                      </div>
                      <div>
                        <label className="font-semibold text-ink-700 block">Route</label>
                        <input
                          type="text"
                          value={editForm.route}
                          onChange={(e) => setEditForm({ ...editForm, route: e.target.value })}
                          className="field mt-1"
                        />
                      </div>
                    </div>
                    <div className="flex justify-end gap-2 pt-2">
                      <button type="submit" disabled={busy} className="btn-primary text-xs">
                        Save Field Edits
                      </button>
                    </div>
                  </form>
                ) : (
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 text-xs">
                    <div className="rounded bg-ink-50 p-2.5">
                      <span className="text-ink-400 block font-medium">Suspect Drug</span>
                      <span className="font-bold text-ink-900">{extraction?.drugName || "—"}</span>
                    </div>
                    <div className="rounded bg-ink-50 p-2.5">
                      <span className="text-ink-400 block font-medium">Dosage</span>
                      <span className="font-semibold text-ink-800">{extraction?.dosage || "—"}</span>
                    </div>
                    <div className="rounded bg-ink-50 p-2.5">
                      <span className="text-ink-400 block font-medium">Route</span>
                      <span className="font-semibold text-ink-800">{extraction?.route || "—"}</span>
                    </div>
                    <div className="rounded bg-ink-50 p-2.5">
                      <span className="text-ink-400 block font-medium">Frequency</span>
                      <span className="font-semibold text-ink-800">{extraction?.frequency || "—"}</span>
                    </div>
                  </div>
                )}
              </div>

              {/* Regulatory Terminology Coding (RxNorm + MedDRA) */}
              {terminology && (
                <div className="card p-5 space-y-3">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-ink-900 border-b border-ink-100 pb-2">
                    Standardized Regulatory Ontologies (RxNorm CUI & MedDRA PT/SOC)
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                    <div className="rounded bg-ink-50 p-3 space-y-1">
                      <p className="font-bold text-ink-900">RxNorm / WHO-ATC Specification</p>
                      <p className="text-ink-700">Display: <strong>{terminology.drugRxNorm?.display_name || extraction?.drugName}</strong></p>
                      <p className="text-ink-700">RxCUI: <span className="font-mono">{terminology.drugRxNorm?.rxcui || "Pending"}</span></p>
                      <p className="text-ink-700">WHO-ATC: <span className="font-mono">{terminology.drugRxNorm?.atc_code || "Pending"}</span></p>
                    </div>
                    <div className="rounded bg-ink-50 p-3 space-y-1.5">
                      <p className="font-bold text-ink-900">MedDRA Preferred Terms</p>
                      {(terminology.meddraAdverseEvents || []).map((m, idx) => (
                        <div key={idx} className="rounded bg-white p-2 border border-ink-200">
                          <p className="font-semibold text-ink-900">PT: {m.pt} (Code: {m.code})</p>
                          <p className="text-[11px] text-ink-500">SOC: {m.soc}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* STEP 2: SERIOUSNESS & SLA CLOCK */}
          {activeStep === "seriousness" && (
            <div className="space-y-6">
              <div className="card p-5 space-y-4 border-l-4 border-l-sky-600">
                <div className="flex items-center justify-between border-b border-ink-100 pb-3">
                  <div>
                    <h3 className="text-sm font-bold text-ink-900">ICH E2A Seriousness & Expedited Clock</h3>
                    <p className="text-xs text-ink-500">FDA 21 CFR 314.80 & EMA GVP Module VI reporting compliance</p>
                  </div>
                  <span
                    className={`rounded px-3 py-1 text-xs font-bold ${
                      isOverdue
                        ? "bg-rose-100 text-rose-800 animate-pulse"
                        : "bg-emerald-100 text-emerald-800"
                    }`}
                  >
                    {isOverdue ? "OVERDUE" : "ON TRACK"}
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 text-xs">
                  <div className="rounded bg-ink-50 p-3">
                    <span className="text-ink-400 block font-medium">Expedited SLA</span>
                    <span className="text-base font-extrabold text-ink-900">{clockDays}-Day Clock</span>
                  </div>
                  <div className="rounded bg-ink-50 p-3">
                    <span className="text-ink-400 block font-medium">SLA Deadline</span>
                    <span className="font-semibold text-ink-800">{dueDate ? dueDate.toLocaleDateString() : "Pending"}</span>
                  </div>
                  <div className="rounded bg-ink-50 p-3">
                    <span className="text-ink-400 block font-medium">Time Remaining</span>
                    <span className="font-bold text-ink-900">{hoursLeft !== null ? `${hoursLeft} hours` : "—"}</span>
                  </div>
                  <div className="rounded bg-ink-50 p-3">
                    <span className="text-ink-400 block font-medium">Seriousness Tier</span>
                    <span className={`font-bold ${report.isSerious ? "text-rose-700" : "text-emerald-700"}`}>
                      {report.isSerious ? "Serious ICSR" : "Non-Serious"}
                    </span>
                  </div>
                </div>

                {report.ichE2ACriteria?.length > 0 && (
                  <div>
                    <span className="text-xs font-semibold text-ink-700 block mb-1.5">ICH E2A Seriousness Criteria Met:</span>
                    <div className="flex flex-wrap gap-2">
                      {report.ichE2ACriteria.map((crit, idx) => (
                        <span key={idx} className="rounded bg-rose-100 px-2.5 py-1 text-xs font-bold text-rose-800">
                          {crit.replace(/_/g, " ")}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* STEP 3: CAUSALITY ASSESSMENT (10 INTERACTIVE NARANJO QUESTIONS) */}
          {activeStep === "causality" && (
            <div className="space-y-6">
              {/* Naranjo Live Score Card */}
              <div className="card p-5 space-y-4 border-l-4 border-l-purple-600 bg-purple-50/20">
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-purple-100 pb-3">
                  <div>
                    <h3 className="text-sm font-bold text-purple-950">Algorithmic Causality (10-Item Naranjo Scale)</h3>
                    <p className="text-xs text-purple-800">Definite (&ge;9) &bull; Probable (5-8) &bull; Possible (1-4) &bull; Doubtful (&le;0)</p>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="text-right">
                      <span className="text-2xl font-black text-purple-950">{liveNaranjoScore}</span>
                      <span className="text-xs font-bold text-purple-700 ml-1">/ 10</span>
                      <p className="text-xs font-bold text-purple-800 uppercase tracking-wider">{liveNaranjoCategory}</p>
                    </div>
                    {causality?.confirmedByPharmacist ? (
                      <span className="rounded bg-emerald-100 px-3 py-1 text-xs font-bold text-emerald-800">
                        &check; Confirmed
                      </span>
                    ) : (
                      <button
                        onClick={handleConfirmCausality}
                        disabled={busy}
                        className="rounded bg-purple-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-purple-700 shadow-sm"
                      >
                        Confirm Causality
                      </button>
                    )}
                  </div>
                </div>

                {/* 10 Interactive Naranjo Questions */}
                <div className="space-y-3 pt-2">
                  {NARANJO_QUESTIONS.map((q) => (
                    <div key={q.id} className="rounded-lg bg-white p-3 border border-purple-100 text-xs space-y-2">
                      <p className="font-semibold text-ink-900">{q.question}</p>
                      <div className="flex flex-wrap gap-2">
                        {q.options.map((opt, i) => {
                          const isSelected = naranjoAnswers[q.id] === opt.score;
                          return (
                            <button
                              key={i}
                              type="button"
                              onClick={() => setNaranjoAnswers({ ...naranjoAnswers, [q.id]: opt.score })}
                              className={`rounded px-3 py-1 text-xs font-semibold transition ${
                                isSelected
                                  ? "bg-purple-600 text-white shadow-xs"
                                  : "bg-ink-100 text-ink-700 hover:bg-ink-200"
                              }`}
                            >
                              {opt.label}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* STEP 4: EVIDENCE & RAG CITATIONS */}
          {activeStep === "evidence" && (
            <div className="space-y-6">
              {summaryText && (
                <div className="card p-5 space-y-3 border-l-4 border-l-emerald-500">
                  <div className="flex items-center justify-between">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-emerald-800">
                      Grounded Clinical Narrative Summary
                    </h3>
                    {citationCheck && (
                      <span className="rounded bg-emerald-100 px-2 py-0.5 text-[10px] font-bold text-emerald-800">
                        {citationCheck.verified_claims_count}/{citationCheck.total_claims} Claims Verified
                      </span>
                    )}
                  </div>
                  <p className="text-xs leading-relaxed text-ink-900 font-medium">
                    {citationCheck?.grounded_summary || summaryText}
                  </p>
                </div>
              )}

              {retrievals?.length > 0 && (
                <div className="card p-5 space-y-3">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-ink-900">
                    Supporting Literature & FDA Drug Labels (RAG)
                  </h3>
                  <div className="space-y-3">
                    {retrievals.map((r, i) => (
                      <div key={i} className="rounded-lg bg-ink-50 p-3 border border-ink-100 text-xs">
                        <div className="flex items-center justify-between font-bold text-ink-900">
                          <span>{r.title}</span>
                          <span className="text-[10px] text-ink-400">Score: {r.similarityScore}</span>
                        </div>
                        <p className="mt-1 text-ink-600 leading-relaxed">{r.snippet}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* STEP 5: REGULATORY TRANSMISSION & GATEWAY */}
          {activeStep === "gateway" && (
            <div className="space-y-6">
              <div className="card p-5 space-y-4">
                <h3 className="text-sm font-bold text-ink-900 border-b border-ink-100 pb-2">
                  FDA ESG & EMA E2B Direct Gateway Dispatch
                </h3>

                {report.gatewayTransmission ? (
                  <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 space-y-2 text-xs">
                    <div className="flex items-center justify-between font-bold text-emerald-900">
                      <span>Gateway Status: {report.gatewayTransmission.status?.toUpperCase()}</span>
                      <span className="font-mono text-[11px] text-emerald-700">{report.gatewayTransmission.transmissionId}</span>
                    </div>
                    <p className="text-emerald-800">Transmitted: {new Date(report.gatewayTransmission.transmittedAt).toLocaleString()}</p>
                    {report.gatewayTransmission.receipt?.fdaCoreId && (
                      <p className="text-emerald-700 font-mono">FDA ESG Core ID: {report.gatewayTransmission.receipt.fdaCoreId}</p>
                    )}
                  </div>
                ) : (
                  <div className="space-y-3 text-xs">
                    <p className="text-ink-600">
                      Transmit this validated ICH E2B(R3) safety report directly into regulatory health authority electronic gateways.
                    </p>

                    <div className="rounded bg-ink-50 p-3 space-y-2">
                      <label className="font-semibold text-ink-800 block">Gateway Simulation Mode:</label>
                      <div className="flex gap-4">
                        <label className="flex items-center gap-1.5 cursor-pointer">
                          <input
                            type="radio"
                            name="simMode"
                            value="ack"
                            checked={gatewaySimMode === "ack"}
                            onChange={() => setGatewaySimMode("ack")}
                          />
                          Positive MDN (ACK)
                        </label>
                        <label className="flex items-center gap-1.5 cursor-pointer">
                          <input
                            type="radio"
                            name="simMode"
                            value="reject"
                            checked={gatewaySimMode === "reject"}
                            onChange={() => setGatewaySimMode("reject")}
                          />
                          Schema Rejection
                        </label>
                        <label className="flex items-center gap-1.5 cursor-pointer">
                          <input
                            type="radio"
                            name="simMode"
                            value="timeout"
                            checked={gatewaySimMode === "timeout"}
                            onChange={() => setGatewaySimMode("timeout")}
                          />
                          Connection Timeout
                        </label>
                      </div>
                    </div>

                    <button
                      onClick={transmitGateway}
                      disabled={busy}
                      className="rounded bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700 shadow-sm"
                    >
                      {busy ? "Transmitting…" : "Transmit to FDA Electronic Submissions Gateway"}
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* STICKY BOTTOM ACTION BAR */}
      <div className="fixed bottom-0 left-0 right-0 z-40 border-t border-ink-200 bg-white/95 px-8 py-3.5 shadow-lg backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4">
          {/* Left: AI vs Human Diff Chips */}
          <div className="flex items-center gap-2 text-xs">
            {diffChips.length > 0 ? (
              <div className="flex items-center gap-1.5">
                <span className="font-semibold text-ink-700">Edits Applied:</span>
                {diffChips.map((chip, idx) => (
                  <span key={idx} className="rounded bg-brand-50 px-2 py-0.5 font-mono text-[10px] text-brand-800 border border-brand-200">
                    {chip}
                  </span>
                ))}
              </div>
            ) : (
              <span className="text-ink-400 text-xs">No pending modifications.</span>
            )}
          </div>

          {/* Right: Justification input & Action buttons */}
          <div className="flex items-center gap-3">
            <input
              type="text"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Clinical reviewer justification notes..."
              className="rounded-lg border border-ink-200 px-3 py-1.5 text-xs text-ink-900 focus:border-brand-500 focus:outline-none w-64"
            />

            {["pending_review", "needs_more_info"].includes(report.status) && (
              <>
                <button
                  type="button"
                  disabled={busy || !causality?.confirmedByPharmacist}
                  onClick={() => review("approve")}
                  title={!causality?.confirmedByPharmacist ? "Confirm causality first" : ""}
                  className="rounded-lg bg-emerald-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-50 transition"
                >
                  Approve Case
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => review("request_more_info")}
                  className="rounded-lg border border-ink-300 bg-white px-3 py-1.5 text-xs font-semibold text-ink-700 hover:bg-ink-50 transition"
                >
                  Request Info
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => review("reject")}
                  className="rounded-lg bg-rose-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-rose-700 transition"
                >
                  Reject
                </button>
              </>
            )}

            <button
              type="button"
              onClick={downloadE2BXml}
              className="rounded-lg border border-ink-300 bg-white px-3 py-1.5 text-xs font-semibold text-ink-700 hover:bg-ink-50 transition"
            >
              Export E2B(R3)
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import api from "../api/client";
import PageHeader from "../components/PageHeader";
import { StatusBadge } from "../components/Badge";

export default function ReportDetail() {
  const { id } = useParams();
  const [data, setData] = useState(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [duplicateMatches, setDuplicateMatches] = useState(null);
  const [checkingDuplicates, setCheckingDuplicates] = useState(false);

  const [editForm, setEditForm] = useState({
    drugName: "",
    symptoms: "",
    dosage: "",
    frequency: "",
    route: "",
    severity: "",
  });

  async function load() {
    const res = await api.get(`/reports/${id}`);
    setData(res.data);
  }

  useEffect(() => {
    load();
  }, [id]);

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
        comment: comment || "Clinical pharmacist edit",
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
      if (res.data?.report?.status !== "processing") {
        break;
      }
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
        pharmacistNotes: comment || "Verified by clinical pharmacist",
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
    if (!window.confirm("Transmit this ICH E2B(R3) case to FDA Electronic Submissions Gateway (ESG)?")) return;
    setBusy(true);
    try {
      const res = await api.post(`/reports/${id}/transmit-gateway`, { gateway: "FDA_ESG" });
      if (res.data?.ok) {
        alert(`Transmission Accepted!\nTransmission ID: ${res.data.gatewayTransmission?.transmissionId}\nReceipt Status: ${res.data.receipt?.status}\nFDA Core ID: ${res.data.receipt?.fdaCoreId || "ACK-RECEIVED"}`);
        await load();
      } else {
        alert("Transmission rejected by gateway:\n" + JSON.stringify(res.data?.receipt?.errors || res.data));
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
        <span className="animate-pulse">Loading report…</span>
      </div>
    );
  }

  const { report, extraction, classification, retrievals, reviews } = data;
  const summaryText = data.summary || report.summary;
  const citationCheck = report.citationVerification;
  const causality = report.causality;
  const terminology = report.terminology || extraction?.terminology;

  const severityStyles = {
    mild: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    moderate: "bg-amber-50 text-amber-700 ring-amber-200",
    serious: "bg-orange-50 text-orange-700 ring-orange-200",
    life_threatening: "bg-rose-50 text-rose-700 ring-rose-200 font-bold",
  };

  const clockDays = report.regulatoryClockDays || 15;
  const dueDate = report.regulatoryDueDate ? new Date(report.regulatoryDueDate) : null;
  const hoursLeft = dueDate ? Math.round((dueDate - new Date()) / 3600000) : null;

  return (
    <div className="space-y-6">
      <PageHeader
        title={`ICSR Case Report ${report._id}`}
        subtitle={<StatusBadge status={report.status} />}
        action={
          <div className="flex items-center gap-2">
            <button
              onClick={downloadFhirJson}
              className="rounded border border-teal-300 bg-teal-50 px-3 py-1.5 text-xs font-semibold text-teal-800 hover:bg-teal-100 shadow-xs"
            >
              Export FHIR R4
            </button>
            <button
              onClick={downloadE2BXml}
              className="rounded border border-ink-300 bg-white px-3 py-1.5 text-xs font-semibold text-ink-700 hover:bg-ink-50 shadow-xs"
            >
              Export ICH E2B(R3)
            </button>
            <button
              onClick={transmitGateway}
              disabled={busy}
              className="rounded bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 shadow-xs"
            >
              Transmit FDA ESG
            </button>
            {report.status === "submitted" && (
              <button disabled={busy} onClick={runPipeline} className="btn-primary text-xs py-1.5">
                {busy ? "Running…" : "Run AI Pipeline"}
              </button>
            )}
          </div>
        }
      />

      <div className="space-y-5">
        {/* Pipeline Execution Animation */}
        {(report.status === "processing" || busy) && (
          <section className="card border-l-4 border-l-amber-500 bg-amber-50/50 p-6 animate-pulse">
            <div className="flex items-center gap-3">
              <svg className="h-5 w-5 animate-spin text-amber-600" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
              </svg>
              <div>
                <h4 className="text-sm font-semibold text-amber-900">AI Safety Intelligence Pipeline Running</h4>
                <p className="text-xs text-amber-700 mt-0.5">
                  De-identifying clinical text, extracting entities, classifying risk, querying Qdrant knowledge base, verifying citations, and calculating causality...
                </p>
              </div>
            </div>
          </section>
        )}

        {/* Phase 2B: Regulatory & ICH E2A Seriousness Compliance Card */}
        <section className="card p-6 border-l-4 border-l-sky-600">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-xs font-bold uppercase tracking-wider text-sky-800">
                ICH E2A Seriousness & Regulatory Reporting Clock
              </h3>
              <p className="text-xs text-ink-500 mt-0.5">
                FDA 21 CFR 314.80 & EMA Good Pharmacovigilance Practices (GVP) SLA
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={handleCheckDuplicates}
                disabled={checkingDuplicates}
                className="rounded border border-sky-300 bg-sky-50 px-2.5 py-1 text-xs font-semibold text-sky-800 hover:bg-sky-100"
              >
                {checkingDuplicates ? "Scanning..." : "Check Duplicates"}
              </button>
              <button
                onClick={downloadFhirJson}
                className="rounded border border-teal-300 bg-teal-50 px-2.5 py-1 text-xs font-semibold text-teal-800 hover:bg-teal-100 shadow-xs"
              >
                FHIR R4
              </button>
              <button
                onClick={downloadE2BXml}
                className="rounded bg-sky-600 px-3 py-1 text-xs font-semibold text-white hover:bg-sky-700 shadow-xs"
              >
                Download E2B(R3)
              </button>
              <button
                onClick={transmitGateway}
                disabled={busy}
                className="rounded bg-indigo-600 px-3 py-1 text-xs font-semibold text-white hover:bg-indigo-700 shadow-xs"
              >
                Transmit FDA
              </button>
            </div>
          </div>

          {report.gatewayTransmission?.status === "acknowledged" && (
            <div className="mt-4 flex items-center justify-between rounded bg-emerald-50 border border-emerald-200 px-3.5 py-2 text-xs text-emerald-800">
              <span className="font-semibold flex items-center gap-2">
                <span className="h-2 w-2 rounded-full bg-emerald-500 animate-ping"></span>
                FDA Electronic Submission Gateway Acknowledged: {report.gatewayTransmission.transmissionId}
              </span>
              <span className="text-[11px] text-emerald-600 font-mono">
                {new Date(report.gatewayTransmission.transmittedAt).toLocaleString()}
              </span>
            </div>
          )}

          <div className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-4 text-xs">
            <div className="rounded bg-ink-50 p-3">
              <span className="text-ink-400 block font-medium">Expedited SLA</span>
              <span className="font-extrabold text-ink-900 text-sm">{clockDays}-Day Clock</span>
            </div>
            <div className="rounded bg-ink-50 p-3">
              <span className="text-ink-400 block font-medium">SLA Deadline</span>
              <span className="font-semibold text-ink-800">
                {dueDate ? dueDate.toLocaleDateString() : "Pending"}
              </span>
            </div>
            <div className="rounded bg-ink-50 p-3">
              <span className="text-ink-400 block font-medium">Clock Status</span>
              <span
                className={`font-bold ${
                  hoursLeft !== null && hoursLeft <= 0
                    ? "text-rose-600"
                    : hoursLeft !== null && hoursLeft <= 48
                    ? "text-amber-600"
                    : "text-emerald-700"
                }`}
              >
                {hoursLeft !== null
                  ? hoursLeft <= 0
                    ? "OVERDUE"
                    : `${hoursLeft}h remaining`
                  : "On Track"}
              </span>
            </div>
            <div className="rounded bg-ink-50 p-3">
              <span className="text-ink-400 block font-medium">Seriousness</span>
              <span
                className={`font-bold ${
                  report.isSerious ? "text-rose-700" : "text-emerald-700"
                }`}
              >
                {report.isSerious ? "Serious ICSR" : "Non-Serious"}
              </span>
            </div>
          </div>

          {report.ichE2ACriteria?.length > 0 && (
            <div className="mt-3">
              <span className="text-xs font-semibold text-ink-600 block">ICH E2A Seriousness Criteria Met:</span>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {report.ichE2ACriteria.map((crit, idx) => (
                  <span
                    key={idx}
                    className="rounded bg-rose-100 px-2 py-0.5 text-xs font-bold text-rose-800"
                  >
                    {crit.replace(/_/g, " ")}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Duplicate Case Detection Results */}
          {duplicateMatches && (
            <div className="mt-4 rounded border border-ink-200 bg-white p-3">
              <h4 className="text-xs font-bold text-ink-900">
                Duplicate ICSR Detection ({duplicateMatches.length} candidate matches found)
              </h4>
              {duplicateMatches.length === 0 ? (
                <p className="mt-1 text-xs text-ink-500">No duplicate cases identified across database.</p>
              ) : (
                <div className="mt-2 divide-y divide-ink-100">
                  {duplicateMatches.map((dup, i) => (
                    <div key={i} className="py-2 flex items-center justify-between text-xs">
                      <div>
                        <span className="font-semibold text-ink-800">
                          Match: {dup.overlappingDrug} &bull; Symptoms: {dup.overlappingSymptoms?.join(", ")}
                        </span>
                        <span className="ml-2 text-ink-400">
                          (Similarity: {Math.round(dup.similarityScore * 100)}%)
                        </span>
                      </div>
                      <Link to={`/reports/${dup.reportId}`} className="text-sky-600 hover:underline">
                        View Report &rarr;
                      </Link>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </section>

        {/* Phase 2B: Algorithmic Causality Assist Card (WHO-UMC & Naranjo) */}
        {causality && (
          <section className="card p-6 border-l-4 border-l-purple-600">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-xs font-bold uppercase tracking-wider text-purple-800">
                  Clinical Causality Assessment (WHO-UMC & Naranjo Algorithm)
                </h3>
                <p className="text-xs text-ink-500 mt-0.5">
                  10-point probability scoring & WHO causality framework
                </p>
              </div>
              <div className="flex items-center gap-2">
                {causality.confirmedByPharmacist ? (
                  <span className="rounded bg-emerald-100 px-2.5 py-1 text-xs font-bold text-emerald-800">
                    &check; Pharmacist Confirmed
                  </span>
                ) : (
                  <button
                    onClick={handleConfirmCausality}
                    disabled={busy}
                    className="rounded bg-purple-600 px-3 py-1 text-xs font-semibold text-white hover:bg-purple-700 shadow-xs"
                  >
                    Confirm Causality
                  </button>
                )}
              </div>
            </div>

            <div className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-3 text-xs">
              <div className="rounded bg-purple-50 p-3">
                <span className="text-purple-600 block font-medium">Naranjo Score</span>
                <p className="text-lg font-extrabold text-purple-950">
                  {causality.naranjoScore} / 10
                  <span className="ml-2 text-xs font-bold text-purple-700">({causality.naranjoCategory})</span>
                </p>
              </div>
              <div className="rounded bg-purple-50 p-3">
                <span className="text-purple-600 block font-medium">WHO-UMC Category</span>
                <p className="text-lg font-extrabold text-purple-950">{causality.whoUmcCategory}</p>
              </div>
              <div className="rounded bg-purple-50 p-3 col-span-2 md:col-span-1">
                <span className="text-purple-600 block font-medium">Pharmacist Sign-off</span>
                <p className="text-xs font-semibold text-purple-900 mt-1">
                  {causality.confirmedByPharmacist
                    ? causality.pharmacistNotes || "Signed and validated"
                    : "Awaiting pharmacist confirmation"}
                </p>
              </div>
            </div>

            {causality.rationale && (
              <p className="mt-3 text-xs text-ink-700 bg-ink-50 p-3 rounded leading-relaxed">
                <strong>Algorithmic Rationale:</strong> {causality.rationale}
              </p>
            )}
          </section>
        )}

        {/* Narrative Summary with Citation Anti-Hallucination Grounding */}
        {summaryText && (
          <section className="card border-l-4 border-l-emerald-500 bg-emerald-50/20 p-6">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <h3 className="text-xs font-bold uppercase tracking-wider text-emerald-800">
                  Explainable Clinical Narrative Summary
                </h3>
                {citationCheck && (
                  <span
                    className={`rounded px-2 py-0.5 text-[10px] font-bold ${
                      !citationCheck.hallucination_detected
                        ? "bg-emerald-100 text-emerald-800"
                        : "bg-rose-100 text-rose-800"
                    }`}
                  >
                    {!citationCheck.hallucination_detected ? "Citation Grounded" : "Claims Unverified"}
                  </span>
                )}
              </div>
              <span className="badge bg-emerald-100 text-emerald-800 text-xs">AI Synthesized</span>
            </div>
            <p className="mt-3 text-sm leading-relaxed text-ink-900 font-medium">
              {citationCheck?.grounded_summary || summaryText}
            </p>

            {citationCheck?.claims?.length > 0 && (
              <details className="mt-3 text-xs">
                <summary className="cursor-pointer text-emerald-800 hover:underline font-semibold">
                  View claim-by-claim citation verification ({citationCheck.verified_claims_count}/{citationCheck.total_claims} verified)
                </summary>
                <div className="mt-2 space-y-2">
                  {citationCheck.claims.map((clm, i) => (
                    <div key={i} className="rounded bg-white p-2.5 border border-emerald-100 text-xs">
                      <div className="flex items-center justify-between">
                        <span className="font-medium text-ink-800">Claim: "{clm.claim}"</span>
                        <span
                          className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                            clm.status === "VERIFIED"
                              ? "bg-emerald-100 text-emerald-800"
                              : clm.status === "PARTIAL"
                              ? "bg-amber-100 text-amber-800"
                              : "bg-rose-100 text-rose-800"
                          }`}
                        >
                          {clm.status} ({Math.round(clm.grounding_score * 100)}%)
                        </span>
                      </div>
                      {clm.matched_source_title && (
                        <p className="mt-1 text-[11px] text-ink-500">
                          Source: [{clm.citation_index}] {clm.matched_source_title}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </details>
            )}
          </section>
        )}

        {/* Medical Terminology Coding Card */}
        {terminology && (
          <section className="card p-6">
            <h3 className="text-xs font-bold uppercase tracking-wider text-ink-500">
              Standardized Medical Terminology Coding (RxNorm & MedDRA)
            </h3>
            <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
              <div className="rounded bg-ink-50 p-3">
                <span className="font-bold text-ink-800 block">RxNorm & WHO-ATC Drug Mapping:</span>
                <div className="mt-1 space-y-1 text-ink-700">
                  <p>Generic Name: <span className="font-semibold text-ink-900">{terminology.drugRxNorm?.display_name || extraction?.drugName}</span></p>
                  <p>RxCUI: <span className="font-mono text-ink-900">{terminology.drugRxNorm?.rxcui || "Pending"}</span></p>
                  <p>WHO-ATC Code: <span className="font-mono text-ink-900">{terminology.drugRxNorm?.atc_code || "Pending"}</span></p>
                  <p>Pharmacologic Class: <span className="text-ink-800">{terminology.drugRxNorm?.class || "Unclassified"}</span></p>
                </div>
              </div>
              <div className="rounded bg-ink-50 p-3">
                <span className="font-bold text-ink-800 block">MedDRA Adverse Event Mapping:</span>
                <div className="mt-1 space-y-1.5">
                  {(terminology.meddraAdverseEvents || []).map((m, idx) => (
                    <div key={idx} className="rounded bg-white p-2 border border-ink-100">
                      <p className="font-semibold text-ink-900">PT: {m.pt} (Code: {m.code})</p>
                      <p className="text-[11px] text-ink-500">LLT: {m.llt} &bull; SOC: {m.soc}</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </section>
        )}

        {/* ML Risk Classification */}
        {classification && (
          <section className="card p-6">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">ML Risk Classification</h3>
            <div className="mt-3 flex flex-wrap items-center gap-4">
              <span className={`badge text-sm ${severityStyles[classification.severity] || "bg-ink-100 text-ink-600 ring-ink-200"}`}>
                {classification.severity?.replace(/_/g, " ")}
              </span>
              <div className="flex items-center gap-2">
                <div className="h-2 w-32 overflow-hidden rounded-full bg-ink-100">
                  <div
                    className="h-full rounded-full bg-brand-500"
                    style={{ width: `${Math.round((classification.confidence || 0) * 100)}%` }}
                  />
                </div>
                <span className="text-sm font-medium text-ink-600">
                  {Math.round((classification.confidence || 0) * 100)}% confidence
                </span>
              </div>
              <span className="text-xs text-ink-400">
                {classification.modelName} v{classification.modelVersion}
              </span>
            </div>
          </section>
        )}

        {/* Structured Data & Inline Editing */}
        {isEditing ? (
          <section className="card p-6 border-brand-300 ring-2 ring-brand-100">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-brand-700">
                Edit Structured Extraction & Severity
              </h3>
              <button
                type="button"
                onClick={() => setIsEditing(false)}
                className="text-xs text-ink-400 hover:text-ink-600"
              >
                Cancel
              </button>
            </div>
            <form onSubmit={saveEdit} className="mt-4 space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-ink-700">Suspect Drug Name</label>
                  <input
                    type="text"
                    value={editForm.drugName}
                    onChange={(e) => setEditForm({ ...editForm, drugName: e.target.value })}
                    className="field mt-1 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-ink-700">Severity Tier</label>
                  <select
                    value={editForm.severity}
                    onChange={(e) => setEditForm({ ...editForm, severity: e.target.value })}
                    className="field mt-1 text-sm"
                  >
                    <option value="mild">Mild</option>
                    <option value="moderate">Moderate</option>
                    <option value="serious">Serious</option>
                    <option value="life_threatening">Life-threatening</option>
                  </select>
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium text-ink-700">Reported Symptoms (comma separated)</label>
                <input
                  type="text"
                  value={editForm.symptoms}
                  onChange={(e) => setEditForm({ ...editForm, symptoms: e.target.value })}
                  className="field mt-1 text-sm"
                />
              </div>
              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className="block text-xs font-medium text-ink-700">Dosage</label>
                  <input
                    type="text"
                    value={editForm.dosage}
                    onChange={(e) => setEditForm({ ...editForm, dosage: e.target.value })}
                    className="field mt-1 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-ink-700">Frequency</label>
                  <input
                    type="text"
                    value={editForm.frequency}
                    onChange={(e) => setEditForm({ ...editForm, frequency: e.target.value })}
                    className="field mt-1 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-ink-700">Route</label>
                  <input
                    type="text"
                    value={editForm.route}
                    onChange={(e) => setEditForm({ ...editForm, route: e.target.value })}
                    className="field mt-1 text-sm"
                  />
                </div>
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button type="button" onClick={() => setIsEditing(false)} className="btn-secondary text-xs">
                  Cancel
                </button>
                <button type="submit" disabled={busy} className="btn-primary text-xs">
                  Save Changes
                </button>
              </div>
            </form>
          </section>
        ) : (
          extraction && (
            <section className="card p-6">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                  Extracted Structured Data
                </h3>
                {["pending_review", "needs_more_info"].includes(report.status) && (
                  <button
                    type="button"
                    onClick={startEditing}
                    className="btn-secondary text-xs py-1 px-2.5"
                  >
                    Edit Data
                  </button>
                )}
              </div>

              <div className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-4 text-sm">
                <div className="rounded-lg bg-ink-50/70 p-3">
                  <span className="text-xs text-ink-400 block font-medium">Suspect Drug</span>
                  <span className="font-semibold text-ink-900">{extraction.drugName || "—"}</span>
                </div>
                <div className="rounded-lg bg-ink-50/70 p-3">
                  <span className="text-xs text-ink-400 block font-medium">Dosage</span>
                  <span className="text-ink-800">{extraction.dosage || "—"}</span>
                </div>
                <div className="rounded-lg bg-ink-50/70 p-3">
                  <span className="text-xs text-ink-400 block font-medium">Frequency</span>
                  <span className="text-ink-800">{extraction.frequency || "—"}</span>
                </div>
                <div className="rounded-lg bg-ink-50/70 p-3">
                  <span className="text-xs text-ink-400 block font-medium">Route</span>
                  <span className="text-ink-800 capitalize">{extraction.route || "—"}</span>
                </div>
              </div>

              {extraction.symptoms?.length > 0 && (
                <div className="mt-3">
                  <span className="text-xs text-ink-400 block font-medium">Reported Symptoms</span>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {extraction.symptoms.map((s, idx) => (
                      <span key={idx} className="badge bg-ink-100 text-ink-700 ring-ink-200">
                        {s}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </section>
          )
        )}

        {/* Supporting Evidence (RAG) */}
        {retrievals?.length > 0 && (
          <section className="card p-6">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">Supporting Evidence (RAG Knowledge Base)</h3>
            <ul className="mt-3 space-y-3">
              {retrievals.map((r) => (
                <li key={r._id} className="rounded-xl border border-ink-100 bg-ink-50/60 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="badge bg-brand-50 text-brand-700 ring-brand-200">{r.sourceCollection}</span>
                    <strong className="text-sm text-ink-900">{r.title}</strong>
                    <span className="text-xs text-ink-400">similarity {r.similarityScore}</span>
                  </div>
                  <p className="mt-1.5 text-sm text-ink-600">{r.snippet}</p>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Human Review Actions */}
        {["pending_review", "needs_more_info"].includes(report.status) && (
          <section className="card p-6">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">Pharmacist Review & Approval Workflow</h3>
            <textarea
              placeholder="Reviewer clinical notes / justification"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              rows={3}
              className="field mt-3"
            />
            <div className="mt-3 flex flex-wrap gap-2">
              <button disabled={busy} onClick={() => review("approve")} className="btn-primary">
                Approve ICSR
              </button>
              <button disabled={busy} onClick={() => review("reject")} className="btn-danger">
                Reject
              </button>
              <button disabled={busy} onClick={() => review("request_more_info")} className="btn-secondary">
                Request more info
              </button>
              <button disabled={busy} onClick={startEditing} className="btn-secondary">
                Edit fields…
              </button>
            </div>
          </section>
        )}

        {/* Review History */}
        {reviews?.length > 0 && (
          <section className="card p-6">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">Review History & Audit Trail</h3>
            <div className="mt-3 divide-y divide-ink-100">
              {reviews.map((rev) => (
                <div key={rev._id} className="py-2.5 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-ink-800 capitalize">
                      {rev.action?.replace(/_/g, " ")} by {rev.reviewer?.name || "Reviewer"} ({rev.reviewer?.role})
                    </span>
                    <span className="text-ink-400">{new Date(rev.createdAt).toLocaleString()}</span>
                  </div>
                  {rev.comment && <p className="mt-1 text-ink-600">{rev.comment}</p>}
                </div>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

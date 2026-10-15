import { useEffect, useState } from "react";
import api from "../api/client";
import PageHeader from "../components/PageHeader";

export default function Analytics() {
  const [activeTab, setActiveTab] = useState("signals"); // "signals" | "demographics" | "graph"
  const [analyticsData, setAnalyticsData] = useState(null);
  const [loading, setLoading] = useState(true);

  // Custom pair query state
  const [searchDrug, setSearchDrug] = useState("");
  const [searchReaction, setSearchReaction] = useState("");
  const [customSignalResult, setCustomSignalResult] = useState(null);
  const [evaluatingSignal, setEvaluatingSignal] = useState(false);

  // Knowledge graph state
  const [selectedGraphDrug, setSelectedGraphDrug] = useState("Amoxicillin");
  const [graphData, setGraphData] = useState(null);
  const [graphLoading, setGraphLoading] = useState(false);

  useEffect(() => {
    api
      .get("/signals/dashboard")
      .then((res) => {
        setAnalyticsData(res.data);
        setLoading(false);
      })
      .catch((err) => {
        console.error("Failed to load signals dashboard", err);
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    if (activeTab === "graph") {
      setGraphLoading(true);
      api
        .get(`/signals/knowledge-graph?drug=${encodeURIComponent(selectedGraphDrug)}`)
        .then((res) => {
          setGraphData(res.data);
          setGraphLoading(false);
        })
        .catch(() => setGraphLoading(false));
    }
  }, [activeTab, selectedGraphDrug]);

  const handleComputeCustomSignal = async (e) => {
    e.preventDefault();
    if (!searchDrug || !searchReaction) return;
    setEvaluatingSignal(true);
    try {
      const res = await api.get(
        `/signals/detect?drug=${encodeURIComponent(searchDrug)}&reaction=${encodeURIComponent(searchReaction)}`
      );
      setCustomSignalResult(res.data);
    } catch (err) {
      console.error(err);
    } finally {
      setEvaluatingSignal(false);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Signal Analytics & FAERS Surveillance"
        subtitle="Post-marketing statistical disproportionality detection (PRR, ROR, EBGM, BCPNN IC) and MedDRA ontologies."
      />

      {/* Tabs */}
      <div className="flex border-b border-ink-200">
        <button
          onClick={() => setActiveTab("signals")}
          className={`border-b-2 px-5 py-3 text-sm font-semibold transition ${
            activeTab === "signals"
              ? "border-sky-600 text-sky-600"
              : "border-transparent text-ink-500 hover:border-ink-300 hover:text-ink-700"
          }`}
        >
          Signal Detection (PRR / ROR)
        </button>
        <button
          onClick={() => setActiveTab("demographics")}
          className={`border-b-2 px-5 py-3 text-sm font-semibold transition ${
            activeTab === "demographics"
              ? "border-sky-600 text-sky-600"
              : "border-transparent text-ink-500 hover:border-ink-300 hover:text-ink-700"
          }`}
        >
          Demographics & Trends
        </button>
        <button
          onClick={() => setActiveTab("graph")}
          className={`border-b-2 px-5 py-3 text-sm font-semibold transition ${
            activeTab === "graph"
              ? "border-sky-600 text-sky-600"
              : "border-transparent text-ink-500 hover:border-ink-300 hover:text-ink-700"
          }`}
        >
          MedDRA Knowledge Graph
        </button>
      </div>

      {loading ? (
        <div className="card h-64 animate-pulse bg-ink-100/50" />
      ) : (
        <>
          {/* TAB 1: SIGNALS */}
          {activeTab === "signals" && (
            <div className="space-y-6">
              {/* Signal Search / Query Box */}
              <div className="card p-5">
                <h3 className="text-base font-bold text-ink-900">Quantitative Signal Query (Evans Criteria)</h3>
                <p className="mt-1 text-xs text-ink-500">
                  Compute 2x2 contingency table metrics against FDA FAERS curated baseline (PRR &ge; 2.0, &chi;&sup2; &ge; 4.0, a &ge; 3).
                </p>
                <form onSubmit={handleComputeCustomSignal} className="mt-4 flex flex-wrap items-end gap-3">
                  <div className="flex-1 min-w-[200px]">
                    <label className="block text-xs font-semibold text-ink-700">Suspect Drug Generic Name</label>
                    <input
                      type="text"
                      value={searchDrug}
                      onChange={(e) => setSearchDrug(e.target.value)}
                      placeholder="e.g. Ciprofloxacin, Lisinopril, Amoxicillin"
                      className="mt-1 w-full rounded border border-ink-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none"
                    />
                  </div>
                  <div className="flex-1 min-w-[200px]">
                    <label className="block text-xs font-semibold text-ink-700">Adverse Reaction Term</label>
                    <input
                      type="text"
                      value={searchReaction}
                      onChange={(e) => setSearchReaction(e.target.value)}
                      placeholder="e.g. Tendon Rupture, Angioedema, Anaphylaxis"
                      className="mt-1 w-full rounded border border-ink-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none"
                    />
                  </div>
                  <button
                    type="submit"
                    disabled={evaluatingSignal || !searchDrug || !searchReaction}
                    className="rounded bg-sky-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-sky-700 disabled:opacity-50"
                  >
                    {evaluatingSignal ? "Evaluating..." : "Detect Signal"}
                  </button>
                </form>

                {customSignalResult && (
                  <div className="mt-4 rounded-lg border border-sky-200 bg-sky-50 p-4">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-sky-950">
                          {customSignalResult.drug} &times; {customSignalResult.reaction}
                        </span>
                        <span
                          className={`rounded px-2 py-0.5 text-xs font-bold ${
                            customSignalResult.signal_status === "STRONG_SIGNAL"
                              ? "bg-rose-100 text-rose-800"
                              : customSignalResult.signal_status === "POTENTIAL_SIGNAL"
                              ? "bg-amber-100 text-amber-800"
                              : customSignalResult.signal_status === "INSUFFICIENT_DATA"
                              ? "bg-ink-100 text-ink-700"
                              : "bg-emerald-100 text-emerald-800"
                          }`}
                        >
                          {customSignalResult.signal_status?.replace("_", " ")}
                        </span>
                        {customSignalResult.provenance && (
                          <span className="text-[10px] text-ink-400 font-medium">({customSignalResult.provenance})</span>
                        )}
                      </div>
                    </div>
                    <div className="mt-3 grid grid-cols-2 gap-4 sm:grid-cols-4 text-xs">
                      <div className="rounded bg-white p-2.5 shadow-xs">
                        <p className="text-ink-500">PRR [95% CI]</p>
                        <p className="text-base font-extrabold text-ink-900">
                          {customSignalResult.prr?.value}
                          <span className="ml-1 text-[11px] font-normal text-ink-500">
                            [{customSignalResult.prr?.ci_95?.[0]} - {customSignalResult.prr?.ci_95?.[1]}]
                          </span>
                        </p>
                      </div>
                      <div className="rounded bg-white p-2.5 shadow-xs">
                        <p className="text-ink-500">ROR [95% CI]</p>
                        <p className="text-base font-extrabold text-ink-900">
                          {customSignalResult.ror?.value}
                          <span className="ml-1 text-[11px] font-normal text-ink-500">
                            [{customSignalResult.ror?.ci_95?.[0]} - {customSignalResult.ror?.ci_95?.[1]}]
                          </span>
                        </p>
                      </div>
                      <div className="rounded bg-white p-2.5 shadow-xs">
                        <p className="text-ink-500">&chi;&sup2; Yates (Evans &ge; 4.0)</p>
                        <p className="text-base font-extrabold text-ink-900">{customSignalResult.prr?.chi2_yates || 0}</p>
                      </div>
                      <div className="rounded bg-white p-2.5 shadow-xs">
                        <p className="text-ink-500">BCPNN IC [IC025]</p>
                        <p className="text-base font-extrabold text-ink-900">
                          {customSignalResult.bcpnn?.ic}
                          <span className="ml-1 text-[11px] font-normal text-ink-500">[{customSignalResult.bcpnn?.ic025}]</span>
                        </p>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* Flagged Signals Table */}
              <div className="card overflow-hidden">
                <div className="border-b border-ink-100 bg-ink-50/50 px-5 py-3 flex items-center justify-between">
                  <h3 className="text-sm font-bold text-ink-900">Active High-Priority Safety Signals (FAERS Surveillance)</h3>
                  <span className="text-xs text-ink-500">Source: FAERS 2024-Q4 Curated Cohort</span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="border-b border-ink-200 bg-ink-50 text-[11px] font-bold uppercase text-ink-600">
                      <tr>
                        <th className="px-4 py-3">Suspect Drug</th>
                        <th className="px-4 py-3">Adverse Reaction</th>
                        <th className="px-4 py-3 text-right">FAERS Cases (a)</th>
                        <th className="px-4 py-3 text-right">PRR [95% CI]</th>
                        <th className="px-4 py-3 text-right">&chi;&sup2; (Yates)</th>
                        <th className="px-4 py-3 text-right">ROR [95% CI]</th>
                        <th className="px-4 py-3 text-right">IC [IC025]</th>
                        <th className="px-4 py-3 text-center">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-ink-100">
                      {(analyticsData?.signals || []).map((sig, idx) => (
                        <tr key={idx} className="hover:bg-ink-50/70 transition">
                          <td className="px-4 py-3 font-bold text-ink-900">{sig.drug}</td>
                          <td className="px-4 py-3 text-ink-800">{sig.reaction}</td>
                          <td className="px-4 py-3 text-right tabular-nums font-semibold text-ink-700">
                            {sig.a.toLocaleString()}
                          </td>
                          <td className="px-4 py-3 text-right tabular-nums font-bold text-sky-700">
                            {sig.prr}
                            <span className="ml-1 text-[10px] text-ink-400">
                              [{sig.prr_ci_95?.[0]}-{sig.prr_ci_95?.[1]}]
                            </span>
                          </td>
                          <td className="px-4 py-3 text-right tabular-nums font-semibold text-ink-700">
                            {sig.chi2.toLocaleString()}
                          </td>
                          <td className="px-4 py-3 text-right tabular-nums text-ink-800 font-semibold">
                            {sig.ror}
                            <span className="ml-1 text-[10px] text-ink-400">
                              [{sig.ror_ci_95?.[0]}-{sig.ror_ci_95?.[1]}]
                            </span>
                          </td>
                          <td className="px-4 py-3 text-right tabular-nums text-ink-700">
                            +{sig.ic} <span className="text-[10px] text-ink-400">[{sig.ic025}]</span>
                          </td>
                          <td className="px-4 py-3 text-center">
                            <span
                              className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-bold ${
                                sig.signal_status === "STRONG_SIGNAL"
                                  ? "bg-rose-100 text-rose-800"
                                  : "bg-amber-100 text-amber-800"
                              }`}
                            >
                              {sig.signal_status?.replace("_", " ")}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* TAB 2: DEMOGRAPHICS */}
          {activeTab === "demographics" && analyticsData && (
            <div className="grid gap-6 md:grid-cols-2">
              <div className="card p-5">
                <h3 className="text-sm font-bold text-ink-900">Top Suspect Drugs by Adverse Event Volume</h3>
                <div className="mt-4 space-y-3">
                  {analyticsData.top_drugs?.map((d, idx) => (
                    <div key={idx} className="space-y-1">
                      <div className="flex justify-between text-xs font-semibold">
                        <span className="text-ink-800">{d.name}</span>
                        <span className="text-ink-500">
                          {d.totalReports.toLocaleString()} reports ({d.seriousPercent}% serious)
                        </span>
                      </div>
                      <div className="h-2 w-full overflow-hidden rounded-full bg-ink-100">
                        <div
                          className="h-full rounded-full bg-gradient-to-r from-sky-500 to-indigo-600"
                          style={{ width: `${Math.min(100, (d.totalReports / 55000) * 100)}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="card p-5 space-y-5">
                <div>
                  <h3 className="text-sm font-bold text-ink-900">Patient Gender Distribution</h3>
                  <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
                    {analyticsData.demographics?.gender?.map((g, idx) => (
                      <div key={idx} className="rounded border border-ink-100 bg-ink-50 p-3">
                        <p className="text-lg font-bold text-ink-900">{g.percentage}%</p>
                        <p className="text-[11px] font-semibold text-ink-600">{g.label}</p>
                      </div>
                    ))}
                  </div>
                </div>

                <div>
                  <h3 className="text-sm font-bold text-ink-900">Patient Age Stratification</h3>
                  <div className="mt-3 space-y-2">
                    {analyticsData.demographics?.age_distribution?.map((a, idx) => (
                      <div key={idx} className="space-y-1">
                        <div className="flex justify-between text-xs">
                          <span className="font-semibold text-ink-700">{a.group}</span>
                          <span className="text-ink-500">{a.percentage}%</span>
                        </div>
                        <div className="h-1.5 w-full rounded-full bg-ink-100">
                          <div
                            className="h-full rounded-full bg-sky-500"
                            style={{ width: `${a.percentage}%` }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* TAB 3: KNOWLEDGE GRAPH */}
          {activeTab === "graph" && (
            <div className="card p-5 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="text-sm font-bold text-ink-900">MedDRA Terminology & Adverse Reaction Graph</h3>
                  <p className="text-xs text-ink-500">
                    Traverse hierarchical relationships connecting Drugs &rarr; Preferred Terms (PT) &rarr; System Organ Classes (SOC).
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-ink-700">Suspect Drug:</span>
                  <select
                    value={selectedGraphDrug}
                    onChange={(e) => setSelectedGraphDrug(e.target.value)}
                    className="rounded border border-ink-300 px-3 py-1.5 text-xs font-semibold focus:border-sky-500 focus:outline-none"
                  >
                    <option value="Amoxicillin">Amoxicillin</option>
                    <option value="Ciprofloxacin">Ciprofloxacin</option>
                    <option value="Lisinopril">Lisinopril</option>
                    <option value="Metformin">Metformin</option>
                    <option value="Atorvastatin">Atorvastatin</option>
                    <option value="Warfarin">Warfarin</option>
                  </select>
                </div>
              </div>

              {graphLoading ? (
                <div className="h-80 animate-pulse rounded border border-ink-200 bg-ink-50" />
              ) : graphData ? (
                <div className="rounded-lg border border-ink-200 bg-ink-900 p-6 text-white min-h-[350px]">
                  <div className="flex flex-wrap items-center justify-center gap-4 text-center">
                    {/* Central Drug Node */}
                    <div className="rounded-2xl border-2 border-indigo-400 bg-indigo-950/80 px-6 py-4 shadow-lg shadow-indigo-950/50">
                      <p className="text-[10px] font-bold uppercase tracking-wider text-indigo-300">Target Drug</p>
                      <p className="text-lg font-black text-white">{graphData.drug || selectedGraphDrug}</p>
                    </div>
                  </div>

                  {/* Connected Adverse Event Nodes */}
                  <div className="mt-8">
                    <p className="text-xs font-bold text-ink-400 uppercase tracking-wider mb-3">Linked MedDRA Preferred Terms & System Organ Classes</p>
                    <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-3">
                      {(graphData.nodes || []).map((node, i) => (
                        <div key={i} className="rounded-lg border border-ink-700 bg-ink-800/80 p-3 hover:border-indigo-400 transition">
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-bold text-white">{node.label || node.name || node.id}</span>
                            <span className={`text-[9px] rounded px-1.5 py-0.5 font-bold uppercase tracking-wider ${
                              node.type === "adverse_event"
                                ? "bg-rose-500/20 text-rose-300 border border-rose-500/30"
                                : node.type === "organ_system"
                                ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                                : node.type === "drug_class"
                                ? "bg-sky-500/20 text-sky-300 border border-sky-500/30"
                                : node.type === "risk_factor"
                                ? "bg-amber-500/20 text-amber-300 border border-amber-500/30"
                                : "bg-indigo-500/20 text-indigo-300 border border-indigo-500/30"
                            }`}>
                              {node.type?.replace("_", " ") || "MedDRA PT"}
                            </span>
                          </div>
                          {node.meddra_pt && (
                            <p className="mt-1.5 text-[11px] text-ink-300">PT: <span className="text-white font-medium">{node.meddra_pt}</span></p>
                          )}
                          {node.category && (
                            <p className="mt-1 text-[11px] text-ink-400">Class: {node.category}</p>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="py-12 text-center text-xs text-ink-400">Select a drug to view ontology graph.</div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}


import { useEffect, useState } from "react";
import api from "../api/client";
import PageHeader from "../components/PageHeader";
import { StatusBadge } from "../components/Badge";

const STATUS_ORDER = ["submitted", "pending_review", "approved", "rejected", "needs_more_info"];

const STAT_ACCENTS = {
  submitted: "from-sky-400 to-sky-600",
  pending_review: "from-amber-400 to-amber-600",
  approved: "from-emerald-400 to-emerald-600",
  rejected: "from-rose-400 to-rose-600",
  needs_more_info: "from-violet-400 to-violet-600",
};

export default function Dashboard() {
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState("signals"); // "signals" | "demographics" | "graph"

  // Signal & Analytics state
  const [analyticsData, setAnalyticsData] = useState(null);
  const [searchDrug, setSearchDrug] = useState("");
  const [searchReaction, setSearchReaction] = useState("");
  const [customSignalResult, setCustomSignalResult] = useState(null);
  const [evaluatingSignal, setEvaluatingSignal] = useState(false);

  // Knowledge graph state
  const [selectedGraphDrug, setSelectedGraphDrug] = useState("Amoxicillin");
  const [graphData, setGraphData] = useState(null);
  const [graphLoading, setGraphLoading] = useState(false);

  useEffect(() => {
    Promise.all([
      api.get("/reports").catch(() => ({ data: { reports: [] } })),
      api.get("/signals/dashboard").catch(() => ({ data: null })),
    ]).then(([repRes, sigRes]) => {
      setReports(repRes.data.reports || []);
      setAnalyticsData(sigRes.data);
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

  const counts = reports.reduce((acc, r) => {
    acc[r.status] = (acc[r.status] || 0) + 1;
    return acc;
  }, {});

  const statuses = [...new Set([...STATUS_ORDER, ...Object.keys(counts)])].filter(
    (s) => counts[s] !== undefined || STATUS_ORDER.includes(s)
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Drug Safety Intelligence & Signal Dashboard"
        subtitle={`${reports.length} total report${reports.length === 1 ? "" : "s"} in local system | FAERS Pharmacovigilance Database (12.5M records)`}
      />

      {/* Operational Triage Summary Cards */}
      {loading ? (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-5">
          {STATUS_ORDER.map((s) => (
            <div key={s} className="card h-28 animate-pulse bg-ink-50" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-5">
          {statuses.map((status) => (
            <div key={status} className="card group relative overflow-hidden p-5 shadow-sm transition hover:shadow">
              <div
                className={`absolute -right-4 -top-4 h-16 w-16 rounded-full bg-gradient-to-br ${
                  STAT_ACCENTS[status] || "from-ink-300 to-ink-500"
                } opacity-20 transition-opacity group-hover:opacity-30`}
              />
              <p className="text-3xl font-extrabold tabular-nums text-ink-900">{counts[status] || 0}</p>
              <div className="mt-3">
                <StatusBadge status={status} />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Tab Navigation */}
      <div className="border-b border-ink-200">
        <nav className="-mb-px flex gap-6 text-sm font-semibold">
          <button
            onClick={() => setActiveTab("signals")}
            className={`border-b-2 pb-3 transition ${
              activeTab === "signals"
                ? "border-sky-600 text-sky-600"
                : "border-transparent text-ink-500 hover:border-ink-300 hover:text-ink-700"
            }`}
          >
            FAERS Disproportionality Signals
          </button>
          <button
            onClick={() => setActiveTab("demographics")}
            className={`border-b-2 pb-3 transition ${
              activeTab === "demographics"
                ? "border-sky-600 text-sky-600"
                : "border-transparent text-ink-500 hover:border-ink-300 hover:text-ink-700"
            }`}
          >
            Demographics & Epidemiology
          </button>
          <button
            onClick={() => setActiveTab("graph")}
            className={`border-b-2 pb-3 transition ${
              activeTab === "graph"
                ? "border-sky-600 text-sky-600"
                : "border-transparent text-ink-500 hover:border-ink-300 hover:text-ink-700"
            }`}
          >
            Drug-Event Knowledge Graph
          </button>
        </nav>
      </div>

      {/* Tab 1: FAERS Signal Detection */}
      {activeTab === "signals" && (
        <div className="space-y-6">
          {/* Signal Search / Query Box */}
          <div className="card p-5">
            <h3 className="text-base font-bold text-ink-900">Quantitative Signal Query (PRR / ROR / BCPNN IC)</h3>
            <p className="mt-1 text-xs text-ink-500">
              Compute Evans criteria disproportionality metrics against FDA FAERS post-marketing safety data.
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
                          : "bg-emerald-100 text-emerald-800"
                      }`}
                    >
                      {customSignalResult.signal_status?.replace("_", " ")}
                    </span>
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
            <div className="border-b border-ink-100 bg-ink-50/50 px-5 py-3">
              <h3 className="text-sm font-bold text-ink-900">Active High-Priority Safety Signals (FAERS Surveillance)</h3>
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

      {/* Tab 2: Demographics & Epidemiology */}
      {activeTab === "demographics" && analyticsData && (
        <div className="grid gap-6 md:grid-cols-2">
          {/* Top Suspect Drugs Card */}
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

          {/* Demographic Breakdown Card */}
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
                {analyticsData.demographics?.ageGroups?.map((a, idx) => (
                  <div key={idx} className="space-y-1 text-xs">
                    <div className="flex justify-between font-semibold">
                      <span className="text-ink-700">{a.range}</span>
                      <span className="text-ink-900">{a.percentage}%</span>
                    </div>
                    <div className="h-2 w-full overflow-hidden rounded-full bg-ink-100">
                      <div
                        className="h-full rounded-full bg-amber-500"
                        style={{ width: `${a.percentage * 2}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Longitudinal Reporting Trends */}
          <div className="card md:col-span-2 p-5">
            <h3 className="text-sm font-bold text-ink-900">Longitudinal Adverse Event Submissions (Quarterly)</h3>
            <div className="mt-4 grid grid-cols-6 gap-2 text-center text-xs">
              {analyticsData.trends?.map((t, idx) => (
                <div key={idx} className="flex flex-col items-center justify-end rounded border border-ink-100 bg-ink-50 p-3 h-40">
                  <div
                    className="w-8 rounded-t bg-sky-600"
                    style={{ height: `${(t.totalReports / 420000) * 100}px` }}
                  />
                  <p className="mt-2 text-[11px] font-bold text-ink-900">{t.period}</p>
                  <p className="text-[10px] text-ink-500">{(t.totalReports / 1000).toFixed(0)}k total</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Tab 3: Drug-Event Knowledge Graph */}
      {activeTab === "graph" && (
        <div className="card p-5 space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-ink-100 pb-4">
            <div>
              <h3 className="text-base font-bold text-ink-900">Drug-Event Clinical Knowledge Graph</h3>
              <p className="text-xs text-ink-500">
                Explore ontological relationships: Drug &rarr; Class &rarr; Adverse Event &rarr; Target Organ &rarr; Risk Factor
              </p>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-ink-600">Center Graph On:</span>
              <select
                value={selectedGraphDrug}
                onChange={(e) => setSelectedGraphDrug(e.target.value)}
                className="rounded border border-ink-300 bg-white px-3 py-1.5 text-xs font-semibold text-ink-800 focus:outline-none"
              >
                <option value="Amoxicillin">Amoxicillin</option>
                <option value="Ciprofloxacin">Ciprofloxacin</option>
                <option value="Ibuprofen">Ibuprofen</option>
                <option value="Lisinopril">Lisinopril</option>
                <option value="Metformin">Metformin</option>
                <option value="Atorvastatin">Atorvastatin</option>
                <option value="Warfarin">Warfarin</option>
              </select>
            </div>
          </div>

          {graphLoading ? (
            <div className="flex h-64 items-center justify-center text-sm text-ink-400">Loading graph topology...</div>
          ) : graphData ? (
            <div className="space-y-4">
              <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 p-4">
                <span className="text-xs font-bold text-indigo-900">Drug Class: </span>
                <span className="text-xs font-medium text-indigo-800">{graphData.class_name}</span>
                {graphData.sibling_drugs?.length > 0 && (
                  <span className="ml-3 text-xs text-indigo-700">
                    &bull; Sibling agents: {graphData.sibling_drugs.join(", ")}
                  </span>
                )}
              </div>

              {/* Graph Nodes Grouped by Clinical Entity Type */}
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                {/* Adverse Events */}
                <div className="rounded border border-rose-200 bg-rose-50/30 p-3">
                  <h4 className="text-xs font-bold uppercase tracking-wider text-rose-800">Induced Reactions</h4>
                  <div className="mt-2 space-y-1.5">
                    {graphData.nodes
                      ?.filter((n) => n.type === "adverse_event")
                      .map((node) => (
                        <div key={node.id} className="rounded bg-white p-2 text-xs font-semibold text-rose-950 shadow-xs">
                          {node.label}
                          {node.meddra_pt && (
                            <span className="block text-[10px] font-normal text-rose-600">MedDRA: {node.meddra_pt}</span>
                          )}
                        </div>
                      ))}
                  </div>
                </div>

                {/* Target Organ Systems */}
                <div className="rounded border border-sky-200 bg-sky-50/30 p-3">
                  <h4 className="text-xs font-bold uppercase tracking-wider text-sky-800">Target Organ Systems</h4>
                  <div className="mt-2 space-y-1.5">
                    {graphData.nodes
                      ?.filter((n) => n.type === "organ_system")
                      .map((node) => (
                        <div key={node.id} className="rounded bg-white p-2 text-xs font-semibold text-sky-950 shadow-xs">
                          {node.label}
                        </div>
                      ))}
                  </div>
                </div>

                {/* Patient Risk Factors */}
                <div className="rounded border border-amber-200 bg-amber-50/30 p-3">
                  <h4 className="text-xs font-bold uppercase tracking-wider text-amber-800">Risk Modifiers / Preconditions</h4>
                  <div className="mt-2 space-y-1.5">
                    {graphData.nodes
                      ?.filter((n) => n.type === "risk_factor")
                      .map((node) => (
                        <div key={node.id} className="rounded bg-white p-2 text-xs font-semibold text-amber-950 shadow-xs">
                          {node.label}
                        </div>
                      ))}
                  </div>
                </div>

                {/* Drug Class & Siblings */}
                <div className="rounded border border-purple-200 bg-purple-50/30 p-3">
                  <h4 className="text-xs font-bold uppercase tracking-wider text-purple-800">Class & Analogues</h4>
                  <div className="mt-2 space-y-1.5">
                    <div className="rounded bg-white p-2 text-xs font-semibold text-purple-950 shadow-xs">
                      {graphData.class_name}
                    </div>
                    {graphData.sibling_drugs?.map((sib, i) => (
                      <div key={i} className="rounded bg-white/70 p-2 text-xs text-purple-900 shadow-xs">
                        {sib} (shared class risk)
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

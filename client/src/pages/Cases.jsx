import { useEffect, useState, useMemo } from "react";
import { Link } from "react-router-dom";
import api from "../api/client";
import PageHeader from "../components/PageHeader";
import { StatusBadge } from "../components/Badge";

const SEVERITY_STYLES = {
  mild: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  moderate: "bg-amber-50 text-amber-700 ring-amber-200",
  serious: "bg-orange-50 text-orange-700 ring-orange-200",
  life_threatening: "bg-rose-50 text-rose-700 ring-rose-200 font-semibold",
};

export default function Cases() {
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [severityFilter, setSeverityFilter] = useState("all");
  const [seriousOnly, setSeriousOnly] = useState(false);

  useEffect(() => {
    api
      .get("/reports")
      .then((res) => {
        setReports(res.data.reports || []);
        setLoading(false);
      })
      .catch((err) => {
        console.error("Failed to load cases", err);
        setLoading(false);
      });
  }, []);

  const filteredReports = useMemo(() => {
    return reports.filter((r) => {
      // Status filter
      if (statusFilter !== "all" && r.status !== statusFilter) return false;

      // Severity filter
      const sev = r.classification?.severity;
      if (severityFilter !== "all" && sev !== severityFilter) return false;

      // Serious only filter
      if (seriousOnly && !r.isSerious) return false;

      // Search term
      if (searchTerm.trim()) {
        const query = searchTerm.toLowerCase();
        const drug = (r.extraction?.drugName || "").toLowerCase();
        const symptoms = (r.extraction?.symptoms || []).join(" ").toLowerCase();
        const repId = (r._id || "").toLowerCase();
        const reporter = (r.submittedBy?.name || "").toLowerCase();
        const text = (r.rawText || r.deidentifiedText || "").toLowerCase();

        return (
          drug.includes(query) ||
          symptoms.includes(query) ||
          repId.includes(query) ||
          reporter.includes(query) ||
          text.includes(query)
        );
      }

      return true;
    });
  }, [reports, statusFilter, severityFilter, seriousOnly, searchTerm]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Adverse Event Case Management"
        subtitle="Search, triage, and track all pharmacovigilance cases against regulatory submission clocks."
      />

      {/* Filter and Search Controls */}
      <div className="card p-4 space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex-1 min-w-[240px]">
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Search by drug, symptom, case ID, reporter..."
              className="w-full rounded-lg border border-ink-200 bg-white px-3.5 py-2 text-sm text-ink-900 placeholder:text-ink-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="rounded-lg border border-ink-200 bg-white px-3 py-2 text-xs font-semibold text-ink-700 focus:border-brand-500 focus:outline-none"
            >
              <option value="all">All Statuses</option>
              <option value="submitted">Submitted</option>
              <option value="pending_review">Pending Review</option>
              <option value="needs_more_info">Needs Info</option>
              <option value="approved">Approved</option>
              <option value="rejected">Rejected</option>
            </select>

            <select
              value={severityFilter}
              onChange={(e) => setSeverityFilter(e.target.value)}
              className="rounded-lg border border-ink-200 bg-white px-3 py-2 text-xs font-semibold text-ink-700 focus:border-brand-500 focus:outline-none"
            >
              <option value="all">All Severities</option>
              <option value="life_threatening">Life-Threatening</option>
              <option value="serious">Serious</option>
              <option value="moderate">Moderate</option>
              <option value="mild">Mild</option>
            </select>

            <label className="flex items-center gap-1.5 rounded-lg border border-ink-200 bg-white px-3 py-2 text-xs font-semibold text-ink-700 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={seriousOnly}
                onChange={(e) => setSeriousOnly(e.target.checked)}
                className="rounded border-ink-300 text-brand-600 focus:ring-brand-500"
              />
              Serious Cases Only
            </label>
          </div>
        </div>

        <div className="flex items-center justify-between text-xs text-ink-500 pt-1 border-t border-ink-100">
          <span>
            Showing <strong className="text-ink-800">{filteredReports.length}</strong> of{" "}
            <strong className="text-ink-800">{reports.length}</strong> cases
          </span>
          {(searchTerm || statusFilter !== "all" || severityFilter !== "all" || seriousOnly) && (
            <button
              onClick={() => {
                setSearchTerm("");
                setStatusFilter("all");
                setSeverityFilter("all");
                setSeriousOnly(false);
              }}
              className="text-brand-600 hover:text-brand-700 font-semibold"
            >
              Clear filters
            </button>
          )}
        </div>
      </div>

      {/* Cases Table */}
      <div className="table-shell overflow-hidden">
        <table>
          <thead>
            <tr>
              <th>Case ID / Drug</th>
              <th>Adverse Reactions</th>
              <th>Severity / Criteria</th>
              <th>Regulatory Clock</th>
              <th>Status</th>
              <th>Reporter / Date</th>
              <th className="text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={7} className="py-12 text-center text-ink-400">
                  Loading cases...
                </td>
              </tr>
            )}
            {!loading && filteredReports.length === 0 && (
              <tr>
                <td colSpan={7} className="py-12 text-center text-ink-400">
                  No matching cases found.
                </td>
              </tr>
            )}
            {filteredReports.map((r) => {
              const sev = r.classification?.severity;
              const clockDays = r.regulatoryClockDays || 15;
              const hours = r.hoursRemaining;
              const isOverdue = r.clockStatus === "OVERDUE";
              const isCritical = r.clockStatus === "EXPEDITED_CRITICAL";
              const drugName = r.extraction?.drugName || "Unspecified drug";
              const symptoms = r.extraction?.symptoms || [];

              return (
                <tr key={r._id} className={sev === "life_threatening" ? "bg-rose-50/20" : ""}>
                  <td>
                    <Link
                      to={`/reports/${r._id}`}
                      className="font-mono text-xs font-bold text-brand-600 hover:underline"
                    >
                      #{r._id.slice(-6).toUpperCase()}
                    </Link>
                    <p className="font-semibold text-ink-900 text-sm mt-0.5">{drugName}</p>
                    {r.extraction?.dosage && (
                      <p className="text-[11px] text-ink-500">{r.extraction.dosage} {r.extraction.route ? `(${r.extraction.route})` : ""}</p>
                    )}
                  </td>
                  <td>
                    {symptoms.length > 0 ? (
                      <div className="flex flex-wrap gap-1 max-w-[220px]">
                        {symptoms.slice(0, 3).map((sym, idx) => (
                          <span
                            key={idx}
                            className="rounded bg-ink-100 px-2 py-0.5 text-[11px] font-medium text-ink-700"
                          >
                            {sym}
                          </span>
                        ))}
                        {symptoms.length > 3 && (
                          <span className="text-[10px] text-ink-400">+{symptoms.length - 3} more</span>
                        )}
                      </div>
                    ) : (
                      <span className="text-xs text-ink-400 italic">None recorded</span>
                    )}
                  </td>
                  <td>
                    {sev ? (
                      <span className={`badge text-xs ${SEVERITY_STYLES[sev] || "bg-ink-100 text-ink-600"}`}>
                        {sev.replace(/_/g, " ")}
                      </span>
                    ) : (
                      <span className="text-xs text-ink-400 italic">Unprocessed</span>
                    )}
                    {r.ichE2ACriteria?.length > 0 && (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {r.ichE2ACriteria.map((crit, idx) => (
                          <span
                            key={idx}
                            className="rounded bg-rose-100/80 px-1.5 py-0.2 text-[9px] font-bold text-rose-800"
                          >
                            {crit.replace(/_/g, " ")}
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td>
                    {isOverdue ? (
                      <span className="inline-flex items-center gap-1 rounded bg-rose-100 px-2 py-0.5 text-xs font-bold text-rose-700 animate-pulse">
                        &bull; OVERDUE
                      </span>
                    ) : isCritical ? (
                      <span className="inline-flex items-center gap-1 rounded bg-amber-100 px-2 py-0.5 text-xs font-bold text-amber-800">
                        &bull; {hours}h left ({clockDays}d SLA)
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-700">
                        {clockDays}d SLA
                      </span>
                    )}
                  </td>
                  <td>
                    <StatusBadge status={r.status} />
                  </td>
                  <td>
                    <p className="text-xs text-ink-700 font-medium">{r.submittedBy?.name || "System"}</p>
                    <p className="text-[11px] text-ink-400">
                      {new Date(r.createdAt).toLocaleDateString()}
                    </p>
                  </td>
                  <td className="text-right">
                    <Link
                      to={`/reports/${r._id}`}
                      className="inline-flex items-center rounded-lg bg-ink-100 px-3 py-1.5 text-xs font-semibold text-ink-800 hover:bg-brand-600 hover:text-white transition"
                    >
                      Review &rarr;
                    </Link>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}


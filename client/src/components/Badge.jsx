const STATUS_STYLES = {
  submitted: "bg-sky-50 text-sky-700 ring-sky-200",
  pending_review: "bg-amber-50 text-amber-700 ring-amber-200",
  approved: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  rejected: "bg-rose-50 text-rose-700 ring-rose-200",
  request_more_info: "bg-violet-50 text-violet-700 ring-violet-200",
};

const ROLE_STYLES = {
  admin: "bg-ink-800 text-white ring-ink-800",
  pharmacist: "bg-brand-50 text-brand-700 ring-brand-200",
  doctor: "bg-sky-50 text-sky-700 ring-sky-200",
  researcher: "bg-violet-50 text-violet-700 ring-violet-200",
};

function formatLabel(value) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function StatusBadge({ status }) {
  const style = STATUS_STYLES[status] || "bg-ink-100 text-ink-600 ring-ink-200";
  return <span className={`badge ${style}`}>{formatLabel(status || "unknown")}</span>;
}

export function RoleBadge({ role }) {
  const style = ROLE_STYLES[role] || "bg-ink-100 text-ink-600 ring-ink-200";
  return <span className={`badge ${style}`}>{role}</span>;
}

export function ActiveBadge({ active }) {
  return active ? (
    <span className="badge bg-emerald-50 text-emerald-700 ring-emerald-200">
      <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> Active
    </span>
  ) : (
    <span className="badge bg-ink-100 text-ink-500 ring-ink-200">
      <span className="h-1.5 w-1.5 rounded-full bg-ink-400" /> Inactive
    </span>
  );
}

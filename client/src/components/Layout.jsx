import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { RoleBadge } from "./Badge";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", icon: DashboardIcon, roles: null },
  { to: "/intake", label: "Submit Report", icon: PlusIcon, roles: ["doctor", "admin"] },
  { to: "/queue", label: "Review Queue", icon: QueueIcon, roles: ["pharmacist", "admin", "researcher"] },
  { to: "/audit-logs", label: "Audit Log", icon: LogIcon, roles: ["admin", "pharmacist"] },
  { to: "/users", label: "Users", icon: UsersIcon, roles: ["admin"] },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const visibleItems = NAV_ITEMS.filter((item) => !item.roles || item.roles.includes(user?.role));

  return (
    <div className="flex min-h-screen bg-ink-50">
      <aside className="flex w-64 shrink-0 flex-col border-r border-ink-100 bg-ink-950 text-ink-100">
        <div className="flex items-center gap-2.5 px-6 py-6">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-brand-400 to-brand-600 shadow-glow">
            <ShieldIcon />
          </div>
          <div>
            <p className="text-base font-bold leading-tight text-white">PharmaGuard</p>
            <p className="text-[11px] font-medium uppercase tracking-wider text-ink-400">Drug Safety Intel</p>
          </div>
        </div>

        <nav className="flex-1 space-y-1 px-3 py-2">
          {visibleItems.map((item) => {
            const active = item.to === "/" ? location.pathname === "/" : location.pathname.startsWith(item.to);
            const Icon = item.icon;
            return (
              <Link
                key={item.to}
                to={item.to}
                className={`group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors ${
                  active
                    ? "bg-brand-500/15 text-white shadow-[inset_2px_0_0_0_theme(colors.brand.400)]"
                    : "text-ink-300 hover:bg-white/5 hover:text-white"
                }`}
              >
                <Icon className={active ? "text-brand-400" : "text-ink-500 group-hover:text-ink-300"} />
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="border-t border-white/10 px-3 py-4">
          <button
            onClick={() => {
              logout();
              navigate("/login");
            }}
            className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-ink-300 transition-colors hover:bg-white/5 hover:text-white"
          >
            <LogoutIcon />
            Log out
          </button>
        </div>
      </aside>

      <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-ink-100 bg-white/80 px-8 py-4 backdrop-blur">
          <div>
            <p className="text-sm text-ink-400">Welcome back</p>
            <p className="text-lg font-semibold text-ink-900">{user?.name}</p>
          </div>
          <div className="flex items-center gap-3">
            <RoleBadge role={user?.role} />
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br from-brand-400 to-brand-600 text-sm font-bold text-white shadow-soft">
              {user?.name?.slice(0, 1)?.toUpperCase() || "?"}
            </div>
          </div>
        </header>

        <main className="flex-1 px-8 py-8">
          <div className="mx-auto max-w-6xl animate-fade-in">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}

function ShieldIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2 4 6v6c0 5 3.4 8.4 8 10 4.6-1.6 8-5 8-10V6l-8-4Z" />
      <path d="m9 12 2 2 4-4" />
    </svg>
  );
}

function iconProps(className) {
  return { width: 18, height: 18, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round", className };
}

function DashboardIcon({ className }) {
  return (
    <svg {...iconProps(className)}>
      <rect x="3" y="3" width="7" height="9" rx="1.5" />
      <rect x="14" y="3" width="7" height="5" rx="1.5" />
      <rect x="14" y="12" width="7" height="9" rx="1.5" />
      <rect x="3" y="16" width="7" height="5" rx="1.5" />
    </svg>
  );
}

function PlusIcon({ className }) {
  return (
    <svg {...iconProps(className)}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v8M8 12h8" />
    </svg>
  );
}

function QueueIcon({ className }) {
  return (
    <svg {...iconProps(className)}>
      <path d="M8 6h13M8 12h13M8 18h13" />
      <path d="M3 6h.01M3 12h.01M3 18h.01" />
    </svg>
  );
}

function LogIcon({ className }) {
  return (
    <svg {...iconProps(className)}>
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V5a2 2 0 0 0-2-2H6.5A2.5 2.5 0 0 0 4 5.5v14Z" />
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 22H20" />
    </svg>
  );
}

function UsersIcon({ className }) {
  return (
    <svg {...iconProps(className)}>
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  );
}

function LogoutIcon() {
  return (
    <svg {...iconProps()}>
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <path d="M16 17l5-5-5-5M21 12H9" />
    </svg>
  );
}

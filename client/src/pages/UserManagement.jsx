import { useEffect, useState } from "react";
import api from "../api/client";
import PageHeader from "../components/PageHeader";
import { RoleBadge, ActiveBadge } from "../components/Badge";

const ROLES = ["admin", "pharmacist", "doctor", "researcher"];

// Module 1 — Admin-only.
export default function UserManagement() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "doctor" });
  const [creating, setCreating] = useState(false);

  function load() {
    api.get("/users").then((res) => {
      setUsers(res.data.users);
      setLoading(false);
    });
  }

  useEffect(load, []);

  async function handleCreate(e) {
    e.preventDefault();
    setCreating(true);
    try {
      await api.post("/users", form);
      setForm({ name: "", email: "", password: "", role: "doctor" });
      load();
    } finally {
      setCreating(false);
    }
  }

  async function toggleActive(u) {
    await api.patch(`/users/${u.id}/active`, { active: !u.active });
    load();
  }

  return (
    <div>
      <PageHeader
        title="User Management"
        subtitle={`${users.length} account${users.length === 1 ? "" : "s"} · admin-only`}
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[360px_1fr]">
        <div className="card h-fit p-6">
          <h3 className="text-sm font-semibold text-ink-900">Create user</h3>
          <p className="mt-1 text-xs text-ink-500">Provision access for a new team member.</p>

          <form onSubmit={handleCreate} className="mt-5 space-y-4">
            <div>
              <label className="field-label">Name</label>
              <input
                className="field"
                placeholder="Jane Doe"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
              />
            </div>
            <div>
              <label className="field-label">Email</label>
              <input
                className="field"
                placeholder="jane@hospital.org"
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                required
              />
            </div>
            <div>
              <label className="field-label">Password</label>
              <input
                className="field"
                placeholder="••••••••"
                type="password"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                required
              />
            </div>
            <div>
              <label className="field-label">Role</label>
              <select
                className="field"
                value={form.role}
                onChange={(e) => setForm({ ...form, role: e.target.value })}
              >
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </div>
            <button type="submit" disabled={creating} className="btn-primary w-full">
              {creating ? "Creating…" : "Create user"}
            </button>
          </form>
        </div>

        <div className="table-shell h-fit">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Role</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={5} className="py-8 text-center text-ink-400">
                    Loading users…
                  </td>
                </tr>
              )}
              {!loading && users.length === 0 && (
                <tr>
                  <td colSpan={5} className="py-8 text-center text-ink-400">
                    No users yet.
                  </td>
                </tr>
              )}
              {users.map((u) => (
                <tr key={u.id}>
                  <td className="font-medium text-ink-900">
                    <div className="flex items-center gap-2.5">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand-400 to-brand-600 text-xs font-bold text-white">
                        {u.name?.slice(0, 1)?.toUpperCase() || "?"}
                      </div>
                      {u.name}
                    </div>
                  </td>
                  <td className="text-ink-500">{u.email}</td>
                  <td>
                    <RoleBadge role={u.role} />
                  </td>
                  <td>
                    <ActiveBadge active={u.active} />
                  </td>
                  <td className="text-right">
                    <button
                      onClick={() => toggleActive(u)}
                      className={u.active ? "btn-danger" : "btn-secondary"}
                    >
                      {u.active ? "Deactivate" : "Activate"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

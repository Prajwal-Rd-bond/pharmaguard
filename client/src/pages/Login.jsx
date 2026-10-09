import { useState, useEffect } from "react";
import { useNavigate, Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function Login() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (user) {
      navigate("/dashboard", { replace: true });
    }
  }, [user, navigate]);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email, password);
      navigate("/dashboard");
    } catch (err) {
      setError(err.response?.data?.error || "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen grid-cols-1 lg:grid-cols-2">
      <div className="relative hidden flex-col justify-between overflow-hidden bg-ink-950 px-12 py-12 text-white lg:flex">
        <div className="pointer-events-none absolute inset-0 bg-grid-faint bg-[length:32px_32px]" />
        <div
          className="pointer-events-none absolute -left-24 -top-24 h-96 w-96 rounded-full bg-brand-500/30 blur-3xl"
          aria-hidden
        />
        <div
          className="pointer-events-none absolute -bottom-32 right-0 h-96 w-96 rounded-full bg-brand-400/20 blur-3xl"
          aria-hidden
        />

        <div className="relative flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-brand-400 to-brand-600 shadow-glow">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2 4 6v6c0 5 3.4 8.4 8 10 4.6-1.6 8-5 8-10V6l-8-4Z" />
              <path d="m9 12 2 2 4-4" />
            </svg>
          </div>
          <span className="text-lg font-bold">PharmaGuard</span>
        </div>

        <div className="relative max-w-md animate-slide-up">
          <h1 className="text-4xl font-extrabold leading-tight">
            Pharmacovigilance,<br />augmented by AI.
          </h1>
          <p className="mt-4 text-ink-300">
            De-identification, LLM extraction, ML risk classification, and explainable evidence retrieval —
            unified in one review workflow for safer drug oversight.
          </p>

          <dl className="mt-10 grid grid-cols-3 gap-6 border-t border-white/10 pt-6 text-sm">
            <div>
              <dt className="text-ink-400">Roles</dt>
              <dd className="mt-1 text-xl font-bold">4</dd>
            </div>
            <div>
              <dt className="text-ink-400">Pipeline</dt>
              <dd className="mt-1 text-xl font-bold">AI + RAG</dd>
            </div>
            <div>
              <dt className="text-ink-400">Audit</dt>
              <dd className="mt-1 text-xl font-bold">Full trail</dd>
            </div>
          </dl>
        </div>

        <p className="relative text-xs text-ink-500">© {new Date().getFullYear()} PharmaGuard. All reports are logged and access-controlled.</p>
      </div>

      <div className="flex items-center justify-center bg-ink-50 px-6 py-12">
        <div className="w-full max-w-sm animate-fade-in">
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-brand-400 to-brand-600 shadow-glow">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2 4 6v6c0 5 3.4 8.4 8 10 4.6-1.6 8-5 8-10V6l-8-4Z" />
                <path d="m9 12 2 2 4-4" />
              </svg>
            </div>
            <span className="text-lg font-bold text-ink-900">PharmaGuard</span>
          </div>

          <h2 className="text-2xl font-bold text-ink-900">Welcome back</h2>
          <p className="mt-1 text-sm text-ink-500">Sign in to access the safety intelligence platform.</p>

          <form onSubmit={handleSubmit} className="mt-8 space-y-4">
            <div>
              <label className="field-label">Email</label>
              <input
                className="field"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                type="email"
                placeholder="you@hospital.org"
                required
              />
            </div>
            <div>
              <label className="field-label">Password</label>
              <input
                className="field"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                type="password"
                placeholder="••••••••"
                required
              />
            </div>

            {error && (
              <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-medium text-rose-700">
                {error}
              </div>
            )}

            <button type="submit" disabled={busy} className="btn-primary mt-2 w-full py-2.5">
              {busy ? "Signing in…" : "Log in"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { LoaderCircle, LockKeyhole, ShieldCheck } from "lucide-react";

import { signInWithPassword } from "@/features/security/supabase-auth";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    const result = await signInWithPassword(email, password);
    if (!result.ok) {
      setError(result.message);
      setSubmitting(false);
      return;
    }
    router.replace("/");
    router.refresh();
  }

  return (
    <main className="grid min-h-screen place-items-center bg-[#06142a] p-4 text-slate-100">
      <section className="w-full max-w-md rounded-3xl border border-cyan-400/15 bg-[#091a31]/95 p-6 shadow-2xl shadow-black/30">
        <div className="flex items-center gap-3">
          <div className="grid h-12 w-12 place-items-center rounded-2xl border border-cyan-300/20 bg-cyan-400/10">
            <ShieldCheck className="h-6 w-6 text-cyan-300" />
          </div>
          <div>
            <p className="text-xs tracking-[0.24em] text-cyan-300 uppercase">NEXOLAB Security</p>
            <h1 className="mt-1 text-xl font-semibold text-white">Вхід оператора</h1>
          </div>
        </div>

        <p className="mt-5 text-sm leading-6 text-slate-400">
          Увійдіть через обліковий запис лабораторії. Доступ до організацій і операцій
          визначається серверними ролями RBAC.
        </p>

        <form className="mt-6 space-y-4" onSubmit={submit}>
          <label className="block">
            <span className="mb-2 block text-xs text-slate-400">Email</span>
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="w-full rounded-xl border border-white/10 bg-[#06142a] px-3 py-2.5 text-sm text-white outline-none focus:border-cyan-300/40"
            />
          </label>

          <label className="block">
            <span className="mb-2 block text-xs text-slate-400">Пароль</span>
            <input
              type="password"
              autoComplete="current-password"
              required
              minLength={8}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="w-full rounded-xl border border-white/10 bg-[#06142a] px-3 py-2.5 text-sm text-white outline-none focus:border-cyan-300/40"
            />
          </label>

          {error ? (
            <div className="rounded-xl border border-rose-400/20 bg-rose-500/10 px-3 py-2 text-xs text-rose-200" role="alert">
              {error}
            </div>
          ) : null}

          <button
            type="submit"
            disabled={submitting}
            className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-blue-500 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-blue-400 disabled:cursor-wait disabled:opacity-60"
          >
            {submitting ? (
              <LoaderCircle className="h-4 w-4 animate-spin" />
            ) : (
              <LockKeyhole className="h-4 w-4" />
            )}
            {submitting ? "Перевірка…" : "Увійти"}
          </button>
        </form>

        <p className="mt-5 text-[11px] leading-5 text-slate-600">
          Токен сесії отримується від Supabase Auth і перевіряється backend через issuer,
          audience та JWKS. Роль не приймається з браузера.
        </p>
      </section>
    </main>
  );
}

"use client";

import { DISCLAIMER } from "@/lib/api";

export function Loading({ what = "data" }: { what?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 p-4 text-sm text-[var(--muted)]">
      <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-[var(--accent)] border-t-transparent" />
      Loading {what}…
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200">
      <div className="font-medium">Could not load data</div>
      <div className="mt-1 break-words opacity-90">{error}</div>
      {onRetry && (
        <button onClick={onRetry} className="mt-2 rounded border border-current px-2 py-0.5 text-xs">
          Retry
        </button>
      )}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="rounded-lg border border-dashed border-[var(--border)] p-4 text-sm text-[var(--muted)]">{children}</div>;
}

export function Card({ title, children, right }: { title?: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-sm">
      {(title || right) && (
        <div className="mb-3 flex items-center justify-between gap-2">
          {title && <h2 className="text-sm font-semibold tracking-wide text-[var(--muted)] uppercase">{title}</h2>}
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function Disclaimer({ compact = false }: { compact?: boolean }) {
  return (
    <div className={compact ? "text-xs text-[var(--muted)]" : "rounded-md bg-amber-100 px-3 py-1.5 text-xs font-medium text-amber-900 dark:bg-amber-900/40 dark:text-amber-100"}>
      {DISCLAIMER}
    </div>
  );
}

export function Pill({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "warn" | "ok" | "bad" }) {
  const cls = {
    neutral: "bg-[var(--chip)] text-[var(--text)]",
    warn: "bg-amber-100 text-amber-900 dark:bg-amber-900/50 dark:text-amber-100",
    ok: "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/50 dark:text-emerald-100",
    bad: "bg-rose-100 text-rose-900 dark:bg-rose-900/50 dark:text-rose-100",
  }[tone];
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>{children}</span>;
}

export function fmt(v: number | null | undefined, d = 1): string {
  return v === null || v === undefined || Number.isNaN(v) ? "–" : v.toFixed(d);
}

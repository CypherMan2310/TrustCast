"use client";

import { DISCLAIMER } from "@/lib/api";

/* ------------------------------------------------------------------ icons (inline, no dependency) */
const PATHS: Record<string, string> = {
  map: "M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2Zm0 0v14m6-12v14",
  trust: "M12 3 4 6v6c0 4.5 3.4 8.3 8 9 4.6-.7 8-4.5 8-9V6l-8-3Zm-3 9 2 2 4-4",
  replay: "M3 12a9 9 0 1 0 3-6.7M3 4v5h5",
  check: "M4 12.5 9 17 20 6",
  chart: "M4 20V10m6 10V4m6 16v-7m4 7H2",
  server: "M4 5h16v6H4zM4 13h16v6H4zM8 8h.01M8 16h.01",
  sun: "M12 4V2m0 20v-2m8-8h2M2 12h2m13.7-5.7 1.4-1.4M4.9 19.1l1.4-1.4m11.4 0 1.4 1.4M4.9 4.9l1.4 1.4M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10Z",
  moon: "M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5Z",
  menu: "M4 7h16M4 12h16M4 17h16",
  close: "M6 6l12 12M18 6 6 18",
  alert: "M12 9v4m0 4h.01M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z",
  drop: "M12 3s6 6.6 6 11a6 6 0 0 1-12 0c0-4.4 6-11 6-11Z",
  thermo: "M14 14.8V5a2 2 0 1 0-4 0v9.8a4 4 0 1 0 4 0Z",
  arrowLeft: "M15 6l-6 6 6 6",
  external: "M14 4h6v6m0-6-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
  info: "M12 8h.01M11 12h1v5h1M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z",
  layers: "m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5",
  clock: "M12 7v5l3 2M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z",
  spark: "M12 3v4m0 10v4M3 12h4m10 0h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6",
  doc: "M7 3h7l5 5v13H7V3Zm7 0v5h5M10 13h6M10 17h6",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 9a7 7 0 0 1 14 0",
};

export function Icon({ name, className = "h-4 w-4" }: { name: keyof typeof PATHS | string; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
      <path d={PATHS[name] ?? PATHS.info} />
    </svg>
  );
}

/* ------------------------------------------------------------------ layout */
export function PageHeader({ title, subtitle, icon, actions }: { title: string; subtitle?: React.ReactNode; icon?: string; actions?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="flex items-center gap-3">
        {icon && (
          <span className="brand-gradient grid h-10 w-10 shrink-0 place-items-center rounded-xl text-white shadow-md">
            <Icon name={icon} className="h-5 w-5" />
          </span>
        )}
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {subtitle && <p className="mt-0.5 text-sm text-[var(--muted)]">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Card({
  title,
  subtitle,
  children,
  right,
  className = "",
  pad = true,
}: {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  children: React.ReactNode;
  right?: React.ReactNode;
  className?: string;
  pad?: boolean;
}) {
  return (
    <section className={`rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow)] ${pad ? "p-5" : ""} ${className}`}>
      {(title || right) && (
        <div className={`flex items-start justify-between gap-3 ${pad ? "mb-4" : "px-5 pt-5 pb-3"}`}>
          <div className="min-w-0">
            {title && <h2 className="text-[15px] font-semibold tracking-tight">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-[var(--muted)]">{subtitle}</p>}
          </div>
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, unit, hint, tone = "neutral", icon }: { label: string; value: React.ReactNode; unit?: string; hint?: React.ReactNode; tone?: "neutral" | "accent" | "warn" | "bad" | "ok"; icon?: string }) {
  const toneCls = { neutral: "text-[var(--text)]", accent: "text-[var(--accent)]", warn: "text-[var(--warn)]", bad: "text-[var(--bad)]", ok: "text-[var(--ok)]" }[tone];
  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-[var(--shadow)]">
      <div className="flex items-center justify-between text-xs font-medium text-[var(--muted)]">
        <span>{label}</span>
        {icon && <Icon name={icon} className="h-4 w-4 text-[var(--faint)]" />}
      </div>
      <div className={`tabular mt-2 text-2xl font-semibold tracking-tight ${toneCls}`}>
        {value}
        {unit && <span className="ml-1 text-sm font-normal text-[var(--muted)]">{unit}</span>}
      </div>
      {hint && <div className="mt-1 text-xs text-[var(--muted)]">{hint}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ controls */
export function Segmented<T extends string | number>({
  value,
  onChange,
  options,
  size = "md",
  ariaLabel,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: React.ReactNode; hint?: string }[];
  size?: "sm" | "md";
  ariaLabel?: string;
}) {
  return (
    <div role="radiogroup" aria-label={ariaLabel} className="inline-flex max-w-full overflow-x-auto rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-1">
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={String(o.value)}
            role="radio"
            aria-checked={on}
            title={o.hint}
            onClick={() => onChange(o.value)}
            className={`whitespace-nowrap rounded-lg font-medium transition ${size === "sm" ? "px-2.5 py-1 text-xs" : "px-3 py-1.5 text-sm"} ${
              on ? "bg-[var(--surface)] text-[var(--text)] shadow-sm ring-1 ring-[var(--border)]" : "text-[var(--muted)] hover:text-[var(--text)]"
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function Select({ label, value, onChange, children, className = "" }: { label?: string; value: string; onChange: (v: string) => void; children: React.ReactNode; className?: string }) {
  return (
    <label className={`flex flex-col gap-1 ${className}`}>
      {label && <span className="text-xs font-medium text-[var(--muted)]">{label}</span>}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 text-sm shadow-sm outline-none transition hover:border-[var(--faint)] focus:ring-2 focus:ring-[var(--ring)]"
      >
        {children}
      </select>
    </label>
  );
}

export const inputCls =
  "h-9 w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 text-sm shadow-sm outline-none transition placeholder:text-[var(--faint)] hover:border-[var(--faint)] focus:ring-2 focus:ring-[var(--ring)]";

export function Button({
  children,
  variant = "primary",
  className = "",
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "outline" }) {
  const v = {
    primary: "brand-gradient text-white shadow-md hover:opacity-95",
    outline: "border border-[var(--border)] bg-[var(--surface)] hover:bg-[var(--chip)]",
    ghost: "hover:bg-[var(--chip)]",
  }[variant];
  return (
    <button {...rest} className={`inline-flex h-9 items-center justify-center gap-2 rounded-xl px-4 text-sm font-medium transition disabled:opacity-50 ${v} ${className}`}>
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------ states */
export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return <div className={`skeleton ${className}`} />;
}

export function Loading({ what = "data", rows = 3 }: { what?: string; rows?: number }) {
  return (
    <div role="status" aria-label={`Loading ${what}`} className="space-y-2 p-1">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className={`h-4 ${i === rows - 1 ? "w-2/3" : "w-full"}`} />
      ))}
      <span className="sr-only">Loading {what}…</span>
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-xl border border-rose-300/60 bg-rose-50 p-3 text-sm text-rose-900 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-200">
      <Icon name="alert" className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="font-medium">Could not load data</div>
        <div className="mt-0.5 break-words opacity-90">{error}</div>
      </div>
      {onRetry && (
        <button onClick={onRetry} className="rounded-lg border border-current px-2 py-0.5 text-xs font-medium">
          Retry
        </button>
      )}
    </div>
  );
}

export function Empty({ children, icon = "info" }: { children: React.ReactNode; icon?: string }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-dashed border-[var(--border)] bg-[var(--surface-2)] p-4 text-sm text-[var(--muted)]">
      <Icon name={icon} className="h-5 w-5 shrink-0 text-[var(--faint)]" />
      <div>{children}</div>
    </div>
  );
}

export function Disclaimer({ compact = false }: { compact?: boolean }) {
  if (compact) return <span className="text-xs text-[var(--muted)]">{DISCLAIMER}</span>;
  return (
    <div className="flex items-center gap-2 rounded-xl border border-amber-300/60 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
      <Icon name="alert" className="h-4 w-4 shrink-0" />
      {DISCLAIMER}
    </div>
  );
}

export function Pill({ children, tone = "neutral", dot = false }: { children: React.ReactNode; tone?: "neutral" | "warn" | "ok" | "bad" | "accent"; dot?: boolean }) {
  const cls = {
    neutral: "bg-[var(--chip)] text-[var(--text)]",
    accent: "bg-[var(--accent-soft)] text-[var(--accent)]",
    warn: "bg-amber-100 text-amber-900 dark:bg-amber-500/15 dark:text-amber-200",
    ok: "bg-emerald-100 text-emerald-900 dark:bg-emerald-500/15 dark:text-emerald-200",
    bad: "bg-rose-100 text-rose-900 dark:bg-rose-500/15 dark:text-rose-200",
  }[tone];
  const dotCls = { neutral: "bg-[var(--faint)]", accent: "bg-[var(--accent)]", warn: "bg-amber-500", ok: "bg-emerald-500", bad: "bg-rose-500" }[tone];
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ${cls}`}>
      {dot && <span className={`h-1.5 w-1.5 rounded-full ${dotCls}`} />}
      {children}
    </span>
  );
}

export function fmt(v: number | null | undefined, d = 1): string {
  return v === null || v === undefined || Number.isNaN(v) ? "–" : v.toFixed(d);
}

export function fmtDate(iso: string | null | undefined, opts: Intl.DateTimeFormatOptions = { day: "numeric", month: "short", year: "numeric" }): string {
  if (!iso) return "–";
  const d = new Date(iso.length === 8 ? `${iso.slice(0, 4)}-${iso.slice(4, 6)}-${iso.slice(6)}` : iso.slice(0, 10));
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-IN", { ...opts, timeZone: "UTC" });
}

/** Shared Recharts tooltip style (theme-aware). */
export const tooltipStyle = {
  contentStyle: {
    background: "var(--surface)",
    border: "1px solid var(--border)",
    borderRadius: 12,
    boxShadow: "var(--shadow)",
    fontSize: 12,
    color: "var(--text)",
  },
  labelStyle: { color: "var(--muted)", fontWeight: 600, marginBottom: 4 },
  itemStyle: { padding: 0 },
  cursor: { fill: "var(--chip)", opacity: 0.6 },
};

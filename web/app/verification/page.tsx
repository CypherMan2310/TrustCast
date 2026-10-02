"use client";

import { Card, Empty, ErrorBox, Icon, Loading, PageHeader, Pill } from "@/components/ui";
import { API_BASE, label, useApi } from "@/lib/api";
import { SOURCE_COLORS } from "@/lib/colors";

interface Summary {
  phases: Record<string, { files?: string[]; models?: Record<string, Record<string, unknown>>; protocol?: Record<string, unknown> } & Record<string, unknown>>;
  scoreboard_generated: string | null;
  notes: string[];
}

const PHASES: { id: string; title: string; text: string }[] = [
  { id: "phase2", title: "Baselines scoreboard", text: "Every model and simple baselines, by lead day and season" },
  { id: "phase3", title: "Bias correction + adaptive blend", text: "Layer 1 and Blender A against the equal-weight mean" },
  { id: "phase4", title: "Gated blender", text: "LightGBM gate against the previous shipped layer" },
  { id: "phase5", title: "Extremes, uncertainty, ablations", text: "Event skill, Brier, 90 % interval coverage, layer removal" },
  { id: "phase8", title: "Frozen 2026 test", text: "Held-out Jan–Sep 2026, evaluated exactly once" },
];

const GATES: { key: string; label: string; what: string }[] = [
  { key: "L1", label: "Bias correction", what: "RMSE" },
  { key: "A", label: "Adaptive weights", what: "RMSE" },
  { key: "B", label: "Gated blend", what: "RMSE" },
  { key: "L5a_tail_map", label: "Extreme tail map", what: "heavy-event ETS" },
  { key: "L5b_classifiers", label: "Event classifiers", what: "Brier" },
];

const KEY_LABEL: Record<string, string> = {
  rain_pilot_precip: "Kerala coast · rain",
  rain_pilot_tmax: "Kerala coast · max temp",
  heat_pilot_precip: "Vidarbha · rain",
  heat_pilot_tmax: "Vidarbha · max temp",
};

function Gate({ v }: { v: boolean | undefined }) {
  if (v === undefined) return <span className="text-xs text-[var(--faint)]">–</span>;
  return v ? (
    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300">
      <Icon name="check" className="h-3 w-3" /> ships
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 rounded-full bg-[var(--chip)] px-2 py-0.5 text-xs font-medium text-[var(--muted)]">
      <Icon name="close" className="h-3 w-3" /> off
    </span>
  );
}

export default function VerificationPage() {
  const s = useApi<Summary>("/v1/verification/summary");
  const sel = s.data?.phases.model_selection as { models?: Record<string, Record<string, unknown>>; protocol?: Record<string, string[]>; generated?: string } | undefined;
  const models = sel?.models ?? {};
  const sources = Array.from(new Set(Object.values(models).flatMap((m) => (m.sources as string[] | undefined) ?? [])));
  const nShip = Object.values(models).reduce((n, m) => n + Object.values((m.verdicts ?? {}) as Record<string, boolean>).filter(Boolean).length, 0);
  const nGates = Object.values(models).reduce((n, m) => n + Object.keys((m.verdicts ?? {}) as Record<string, boolean>).length, 0);

  return (
    <div className="space-y-6">
      <PageHeader title="Verification" icon="chart" subtitle="Every layer has to beat the previous one on held-out data before it ships. Failures are reported, not hidden." />

      <div className="grid gap-4 md:grid-cols-3">
        {[
          { icon: "check", title: "Truth", text: "IMD gridded rainfall (0.25°) and Tmax; IMERG satellite rain only where IMD is missing, flagged provisional." },
          { icon: "clock", title: "Split", text: "Tune on Apr–Dec 2024, gate on 2025. Test Jan–Sep 2026 is frozen and run once." },
          { icon: "chart", title: "Gate rule", text: "Significantly better (paired block bootstrap, 95 %) at ≥ 3 of 5 lead days and worse at none." },
        ].map((x) => (
          <div key={x.title} className="flex gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-[var(--shadow)]">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-[var(--accent-soft)] text-[var(--accent)]">
              <Icon name={x.icon} />
            </span>
            <div>
              <div className="text-sm font-semibold">{x.title}</div>
              <p className="mt-0.5 text-xs leading-relaxed text-[var(--muted)]">{x.text}</p>
            </div>
          </div>
        ))}
      </div>

      <Card
        title="Layer decisions"
        subtitle={sel?.protocol ? `Tuned on ${sel.protocol.tune?.join(" → ")}, gated on ${sel.protocol.holdout?.join(" → ")}` : "config/model_selection.yaml"}
        right={nGates > 0 && <Pill tone="accent">{nShip} of {nGates} layers ship</Pill>}
      >
        {s.loading && <Loading rows={5} />}
        {s.error && <ErrorBox error={s.error} onRetry={s.reload} />}
        {s.data && !sel?.models && <Empty>Experiments have not been run yet.</Empty>}
        {sel?.models && (
          <div data-tour="gate-matrix" className="overflow-x-auto rounded-xl border border-[var(--border)]">
            <table className="w-full text-sm">
              <thead className="bg-[var(--surface-2)] text-left text-xs text-[var(--muted)]">
                <tr>
                  <th className="px-3 py-2.5 font-medium">Region · variable</th>
                  {GATES.map((g) => (
                    <th key={g.key} className="px-3 py-2.5 font-medium">
                      {g.label}
                      <span className="block text-[10px] font-normal text-[var(--faint)]">judged on {g.what}</span>
                    </th>
                  ))}
                  <th className="px-3 py-2.5 font-medium">Settings</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(models).map(([k, m]) => {
                  const v = (m.verdicts ?? {}) as Record<string, boolean>;
                  return (
                    <tr key={k} className="border-t border-[var(--border)]">
                      <td className="px-3 py-3 font-medium whitespace-nowrap">{KEY_LABEL[k] ?? k}</td>
                      {GATES.map((g) => (
                        <td key={g.key} className="px-3 py-3">
                          <Gate v={v[g.key]} />
                        </td>
                      ))}
                      <td className="px-3 py-3 text-xs text-[var(--muted)]">
                        {m.cell_bias ? "per-cell bias · " : m.qm ? "quantile map · " : ""}
                        {Number(m.p) === 0 ? "equal weights" : `half-life ${String(m.half_life)} d, p ${String(m.p)}`}
                        {m.extremes === false && " · ensemble probabilities"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {sources.length > 0 && (
          <div data-tour="frozen-sources" className="mt-4 flex flex-wrap items-center gap-2 text-xs">
            <span className="text-[var(--muted)]">Frozen source set:</span>
            {sources.map((x) => (
              <span key={x} className="inline-flex items-center gap-1.5 rounded-full border border-[var(--border)] px-2.5 py-0.5">
                <span className="h-2 w-2 rounded-full" style={{ background: SOURCE_COLORS[x] ?? "#94a3b8" }} />
                {label(x)}
              </span>
            ))}
          </div>
        )}
        {s.data && s.data.notes.length > 0 && (
          <ul className="mt-4 list-disc space-y-1 pl-5 text-xs text-[var(--muted)]">
            {s.data.notes.map((n) => <li key={n}>{n}</li>)}
          </ul>
        )}
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        {PHASES.map((ph) => {
          const files = ((s.data?.phases[ph.id]?.files ?? []) as string[]).filter(Boolean);
          const figs = files.filter((f) => f.endsWith(".png"));
          const md = files.find((f) => f.endsWith(".md"));
          return (
            <Card
              key={ph.id}
              title={ph.title}
              subtitle={ph.text}
              className={figs.length > 2 ? "lg:col-span-2" : ""}
              right={
                md ? (
                  <a className="inline-flex h-8 items-center gap-1 rounded-lg border border-[var(--border)] px-2.5 text-xs font-medium whitespace-nowrap hover:bg-[var(--chip)]" href={`${API_BASE}/reports/${ph.id}/${md}`} target="_blank" rel="noreferrer">
                    <Icon name="doc" className="h-3.5 w-3.5" /> Full report
                  </a>
                ) : files.length === 0 ? (
                  <Pill>pending</Pill>
                ) : undefined
              }
            >
              {s.loading ? (
                <Loading rows={2} />
              ) : files.length === 0 ? (
                <Empty icon="clock">Not generated yet.</Empty>
              ) : figs.length === 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {files.map((f) => (
                    <a key={f} href={`${API_BASE}/reports/${ph.id}/${f}`} target="_blank" rel="noreferrer" className="rounded-lg bg-[var(--chip)] px-2 py-1 font-mono text-[11px] text-[var(--muted)] hover:text-[var(--text)]">
                      {f}
                    </a>
                  ))}
                </div>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                  {figs.map((f) => (
                    <a key={f} href={`${API_BASE}/reports/${ph.id}/${f}`} target="_blank" rel="noreferrer" className="group overflow-hidden rounded-xl border border-[var(--border)] bg-white">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={`${API_BASE}/reports/${ph.id}/${f}`} alt={f.replace(".png", "").replaceAll("_", " ")} className="w-full transition group-hover:scale-[1.02]" loading="lazy" />
                    </a>
                  ))}
                </div>
              )}
            </Card>
          );
        })}
      </div>
    </div>
  );
}

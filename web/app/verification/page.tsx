"use client";

import { Card, Empty, ErrorBox, Loading, Pill } from "@/components/ui";
import { API_BASE, useApi } from "@/lib/api";

interface Summary {
  phases: Record<string, { files?: string[]; models?: Record<string, Record<string, unknown>>; protocol?: Record<string, unknown> } & Record<string, unknown>>;
  scoreboard_generated: string | null;
  notes: string[];
}

const PHASE_TITLES: Record<string, string> = {
  phase2: "Phase 2: baselines scoreboard",
  phase3: "Phase 3: bias correction + blender A",
  phase4: "Phase 4: gated blender B",
  phase5: "Phase 5: extremes, uncertainty, ablations",
  phase8: "Phase 8: frozen 2026 test",
};

export default function VerificationPage() {
  const s = useApi<Summary>("/v1/verification/summary");
  if (s.loading) return <Loading what="verification summary" />;
  if (s.error) return <ErrorBox error={s.error} onRetry={s.reload} />;
  if (!s.data) return null;
  const sel = s.data.phases.model_selection as { models?: Record<string, Record<string, unknown>>; protocol?: Record<string, string[]> } | undefined;
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Verification</h1>
      <Card title="How results are produced">
        <ul className="list-disc space-y-1 pl-5 text-sm">
          <li>Truth: IMD gridded rainfall (0.25°) and Tmax (1°); IMERG satellite rain only where IMD is not yet available (flagged provisional).</li>
          <li>Development split 2024–2025: tuning on 2024, every layer gated on 2025 with paired block-bootstrap 95 % intervals (5-day blocks).</li>
          <li>A layer ships only if its RMSE is significantly lower at ≥ 3 of 5 lead days and significantly higher at none.</li>
          <li>Held-out test Jan–Sep 2026 is frozen and evaluated once (Phase 8).</li>
          {s.data.notes.map((n) => <li key={n}>{n}</li>)}
        </ul>
        {s.data.scoreboard_generated && <p className="mt-2 text-xs text-[var(--muted)]">{s.data.scoreboard_generated}</p>}
      </Card>
      <Card title="Layer decisions (config/model_selection.yaml)">
        {!sel?.models ? <Empty>Experiments have not been run yet.</Empty> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-[var(--muted)]"><tr><th className="py-1">Region · variable</th><th>Bias correction</th><th>Blender A</th><th>Gate B</th><th>Half-life</th><th>p</th><th>Scope</th></tr></thead>
              <tbody>
                {Object.entries(sel.models).map(([k, m]) => {
                  const v = (m.verdicts ?? {}) as Record<string, boolean>;
                  const pill = (b: boolean | undefined) => <Pill tone={b ? "ok" : "bad"}>{b ? "ships" : "disabled"}</Pill>;
                  return (
                    <tr key={k} className="border-t border-[var(--border)]">
                      <td className="py-1">{k.replace("_", " · ")}</td><td>{pill(v.L1)}</td><td>{pill(v.A)}</td><td>{pill(v.B)}</td>
                      <td>{String(m.half_life)}</td><td>{String(m.p)}</td><td>{String(m.scope)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {Object.entries(PHASE_TITLES).map(([ph, title]) => {
        const files = (s.data!.phases[ph]?.files ?? []) as string[];
        const figs = files.filter((f) => f.endsWith(".png"));
        const md = files.find((f) => f.endsWith(".md"));
        return (
          <Card key={ph} title={title} right={md && <a className="text-xs text-[var(--accent)] underline" href={`${API_BASE}/reports/${ph}/${md}`} target="_blank" rel="noreferrer">full report</a>}>
            {files.length === 0 ? <Empty>Not generated yet.</Empty> : figs.length === 0 ? <p className="text-sm">Tables: {files.join(", ")}</p> : (
              <div className="grid gap-3 md:grid-cols-2">
                {figs.map((f) => (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img key={f} src={`${API_BASE}/reports/${ph}/${f}`} alt={f} className="w-full rounded-lg border border-[var(--border)] bg-white" loading="lazy" />
                ))}
              </div>
            )}
          </Card>
        );
      })}
    </div>
  );
}

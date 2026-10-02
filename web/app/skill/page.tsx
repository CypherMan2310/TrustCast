"use client";

import { useMemo, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import MapView from "@/components/MapView";
import { Card, Empty, ErrorBox, Loading, PageHeader, Pill, Segmented, Skeleton, fmt, fmtDate, tooltipStyle } from "@/components/ui";
import { LeaderboardRow, Region, SkillMap, Variable, label, useApi } from "@/lib/api";
import { SOURCE_COLORS } from "@/lib/colors";
import { useTrainingReporter } from "@/components/training/TrainingProvider";

const BASELINES = ["equal_mean", "superensemble", "persistence", "climatology"];

/** Forest plot: RMSE point estimate with its 95 % interval, sorted best first. */
function Forest({ rows, unit }: { rows: LeaderboardRow[]; unit: string }) {
  const ok = rows.filter((r) => r.rmse !== null).sort((a, b) => (a.rmse as number) - (b.rmse as number));
  if (!ok.length) return <Empty>No scores for this lead day.</Empty>;
  const lo = Math.min(...ok.map((r) => r.rmse_lo ?? (r.rmse as number)));
  const hi = Math.max(...ok.map((r) => r.rmse_hi ?? (r.rmse as number)));
  const pad = (hi - lo) * 0.08 || 1;
  const x = (v: number) => `${(100 * (v - (lo - pad))) / (hi - lo + 2 * pad)}%`;
  return (
    <div className="space-y-2.5">
      {ok.map((r, i) => {
        const base = BASELINES.includes(r.source);
        const c = SOURCE_COLORS[r.source] ?? "#94a3b8";
        return (
          <div key={r.source} className="grid grid-cols-[150px_1fr_64px] items-center gap-3 text-sm">
            <span className={`flex items-center gap-2 truncate ${base ? "text-[var(--muted)]" : ""}`}>
              <span className="tabular w-4 text-right text-xs text-[var(--faint)]">{i + 1}</span>
              <span className="truncate">{label(r.source)}</span>
            </span>
            <span className="relative h-6">
              <span className="absolute inset-x-0 top-1/2 h-px bg-[var(--border)]" />
              {r.rmse_lo !== null && r.rmse_hi !== null && (
                <span className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full opacity-35" style={{ left: x(r.rmse_lo), width: `calc(${x(r.rmse_hi)} - ${x(r.rmse_lo)})`, background: c }} />
              )}
              <span
                className={`absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-[var(--surface)] ${base ? "border-2 bg-[var(--surface)]" : ""}`}
                style={{ left: x(r.rmse as number), background: base ? undefined : c, borderColor: c }}
                title={`${label(r.source)}: ${fmt(r.rmse, 2)} [${fmt(r.rmse_lo, 2)}, ${fmt(r.rmse_hi, 2)}]`}
              />
            </span>
            <span className="tabular text-right text-xs font-medium">{fmt(r.rmse, 2)}</span>
          </div>
        );
      })}
      <div className="grid grid-cols-[150px_1fr_64px] gap-3 text-[11px] text-[var(--faint)]">
        <span />
        <span className="flex justify-between">
          <span>lower error is better</span>
          <span>RMSE ({unit}), bars = 95 % interval</span>
        </span>
        <span />
      </div>
    </div>
  );
}

export default function SkillPage() {
  const [region, setRegion] = useState<Region>("rain_pilot");
  const [variable, setVariable] = useState<Variable>("precip");
  const [lead, setLeadState] = useState(1);
  const report = useTrainingReporter();
  const setLead = (l: number) => {
    setLeadState(l);
    report({ type: "skill-lead", lead: l });
  };
  const sm = useApi<SkillMap>(`/v1/skill/map?region=${region}&variable=${variable}&lead_day=${lead}`);
  const lb = useApi<{ rows: LeaderboardRow[]; period: string }>(`/v1/skill/leaderboard?region=${region}&variable=${variable}`);
  const unit = variable === "precip" ? "mm" : "°C";

  const cells = useMemo(() => (sm.data?.cells ?? []).map((c) => ({ lat: c.lat, lon: c.lon, v: null, cat: c.best_source })), [sm.data]);
  const share = useMemo(() => {
    const n: Record<string, number> = {};
    for (const c of cells) if (c.cat) n[c.cat] = (n[c.cat] ?? 0) + 1;
    const tot = Object.values(n).reduce((a, b) => a + b, 0);
    return Object.entries(n)
      .map(([s, k]) => ({ s, f: tot ? k / tot : 0 }))
      .sort((a, b) => b.f - a.f);
  }, [cells]);
  const cat = useMemo(() => Object.fromEntries(share.map(({ s }) => [s, SOURCE_COLORS[s] ?? "#999"])), [share]);

  const chart = useMemo(() => {
    const rows = lb.data?.rows ?? [];
    const byLead = new Map<number, Record<string, number | null>>();
    for (const r of rows) {
      const row = byLead.get(r.lead_day) ?? { lead: r.lead_day };
      row[r.source] = r.rmse;
      byLead.set(r.lead_day, row);
    }
    return { data: [...byLead.values()].sort((a, b) => (a.lead as number) - (b.lead as number)), names: Array.from(new Set(rows.map((r) => r.source))) };
  }, [lb.data]);
  const leadRows = (lb.data?.rows ?? []).filter((r) => r.lead_day === lead);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Who to trust"
        icon="trust"
        subtitle="Which model has been most accurate recently, place by place, and how all models rank with 95 % intervals"
        actions={
          <>
            <Segmented
              ariaLabel="Region"
              value={region}
              onChange={(r) => {
                setRegion(r);
                setVariable(r === "rain_pilot" ? "precip" : "tmax");
              }}
              options={[
                { value: "rain_pilot", label: "Kerala coast" },
                { value: "heat_pilot", label: "Vidarbha" },
              ]}
            />
            <Segmented ariaLabel="Variable" value={variable} onChange={setVariable} options={[{ value: "precip", label: "Rain" }, { value: "tmax", label: "Max temp" }]} />
            <div data-tour="skill-lead">
              <Segmented ariaLabel="Lead day" value={lead} onChange={setLead} options={[1, 2, 3, 4, 5].map((l) => ({ value: l, label: `Day ${l}` }))} />
            </div>
          </>
        }
      />

      <div className="grid gap-6 xl:grid-cols-[1fr_340px]">
        <Card
          tour="skill-map"
          pad={false}
          className="overflow-hidden"
          title="Most accurate model in each grid cell"
          subtitle={sm.data ? `Leak-free decayed error (half-life ${sm.data.half_life_days} days) at run ${fmtDate(sm.data.init_time)}; only verification finished before the run is used` : undefined}
        >
          {sm.loading && <Skeleton className="h-[460px] rounded-none" />}
          {sm.error && <div className="p-5"><ErrorBox error={sm.error} onRetry={sm.reload} /></div>}
          {sm.data && <MapView cells={cells} categorical={cat} height="min(460px, 65vh)" formatCategory={(c) => `most accurate: ${label(c)}`} />}
        </Card>
        <Card title="Share of the region" subtitle={`Day ${lead}: cells where each model is best`}>
          {sm.loading ? (
            <Loading rows={4} />
          ) : share.length === 0 ? (
            <Empty>No skill history yet.</Empty>
          ) : (
            <ul className="space-y-3">
              {share.map(({ s, f }) => (
                <li key={s}>
                  <div className="flex items-center justify-between text-sm">
                    <span className="flex items-center gap-2">
                      <span className="h-2.5 w-2.5 rounded-sm" style={{ background: cat[s] }} />
                      {label(s)}
                    </span>
                    <span className="tabular font-medium">{Math.round(f * 100)}%</span>
                  </div>
                  <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-[var(--chip)]">
                    <div className="h-full rounded-full" style={{ width: `${f * 100}%`, background: cat[s] }} />
                  </div>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-5 text-xs leading-relaxed text-[var(--muted)]">
            The best model changes with place, season and lead time. That is why TRUSTCAST learns weights instead of trusting one model.
          </p>
        </Card>
      </div>

      <Card title="Leaderboard" subtitle={lb.data ? `${lb.data.period}. All forecasts scored on the same cases.` : undefined} right={<Pill tone="accent">Day {lead}</Pill>}>
        {lb.loading && <Loading what="leaderboard" rows={6} />}
        {lb.error && <ErrorBox error={lb.error} onRetry={lb.reload} />}
        {lb.data && (
          <div className="grid gap-8 lg:grid-cols-2">
            <div data-tour="forest">
              <Forest rows={leadRows} unit={unit} />
            </div>
            <div>
              <div className="mb-2 text-xs font-medium text-[var(--muted)]">RMSE by lead day ({unit})</div>
              <div className="h-72">
                <ResponsiveContainer>
                  <LineChart data={chart.data} margin={{ left: -10, right: 8, top: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="lead" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(v) => `Day ${v}`} />
                    <YAxis fontSize={12} tickLine={false} axisLine={false} domain={["auto", "auto"]} />
                    <Tooltip {...tooltipStyle} labelFormatter={(v) => `Day ${v}`} formatter={(v, n) => [fmt(Number(v), 2), label(String(n))]} />
                    <Legend iconType="circle" wrapperStyle={{ fontSize: 11 }} formatter={(n) => label(String(n))} />
                    {chart.names.map((s) => (
                      <Line
                        key={s}
                        type="monotone"
                        dataKey={s}
                        stroke={SOURCE_COLORS[s] ?? "#94a3b8"}
                        strokeWidth={BASELINES.includes(s) ? 1.5 : 2}
                        strokeDasharray={BASELINES.includes(s) ? "5 4" : undefined}
                        dot={{ r: 3 }}
                        connectNulls
                        isAnimationActive={false}
                      />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        )}
        {lb.data && leadRows.length > 0 && (
          <div className="mt-6 overflow-x-auto rounded-xl border border-[var(--border)]">
            <table className="w-full text-sm">
              <thead className="bg-[var(--surface-2)] text-left text-xs text-[var(--muted)]">
                <tr>
                  <th className="px-3 py-2 font-medium">Forecast</th>
                  <th className="px-3 py-2 font-medium">RMSE [95 % CI]</th>
                  <th className="px-3 py-2 font-medium">CRPS</th>
                  <th className="px-3 py-2 font-medium">ETS heavy</th>
                  <th className="px-3 py-2 font-medium">Recent RMSE</th>
                  <th className="px-3 py-2 text-right font-medium">Cases</th>
                </tr>
              </thead>
              <tbody>
                {[...leadRows]
                  .sort((a, b) => (a.rmse ?? 1e9) - (b.rmse ?? 1e9))
                  .map((r) => (
                    <tr key={r.source} className="border-t border-[var(--border)] hover:bg-[var(--surface-2)]">
                      <td className="px-3 py-2">
                        <span className="flex items-center gap-2">
                          <span className="h-2.5 w-2.5 rounded-full" style={{ background: SOURCE_COLORS[r.source] ?? "#94a3b8" }} />
                          {label(r.source)}
                          {BASELINES.includes(r.source) && <Pill>baseline</Pill>}
                        </span>
                      </td>
                      <td className="tabular px-3 py-2 font-mono text-xs">
                        {fmt(r.rmse, 2)} <span className="text-[var(--muted)]">[{fmt(r.rmse_lo, 2)}, {fmt(r.rmse_hi, 2)}]</span>
                      </td>
                      <td className="tabular px-3 py-2 font-mono text-xs">{fmt(r.crps, 2)}</td>
                      <td className="tabular px-3 py-2 font-mono text-xs">{fmt(r.ets_heavy, 3)}</td>
                      <td className="tabular px-3 py-2 font-mono text-xs">{fmt(r.recent_rmse, 2)}</td>
                      <td className="tabular px-3 py-2 text-right text-xs text-[var(--muted)]">{r.n_cases?.toLocaleString("en-IN") ?? "–"}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

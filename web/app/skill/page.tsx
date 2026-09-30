"use client";

import { useMemo, useState } from "react";
import { CartesianGrid, ErrorBar, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import MapView from "@/components/MapView";
import { Card, Empty, ErrorBox, Loading, fmt } from "@/components/ui";
import { LeaderboardRow, REGIONS, Region, SkillMap, Variable, label, useApi } from "@/lib/api";
import { SOURCE_COLORS } from "@/lib/colors";

export default function SkillPage() {
  const [region, setRegion] = useState<Region>("rain_pilot");
  const [variable, setVariable] = useState<Variable>("precip");
  const [lead, setLead] = useState(1);
  const sm = useApi<SkillMap>(`/v1/skill/map?region=${region}&variable=${variable}&lead_day=${lead}`);
  const lb = useApi<{ rows: LeaderboardRow[]; period: string }>(`/v1/skill/leaderboard?region=${region}&variable=${variable}`);

  const cells = useMemo(() => (sm.data?.cells ?? []).map((c) => ({ lat: c.lat, lon: c.lon, v: null, cat: c.best_source })), [sm.data]);
  const present = useMemo(() => Array.from(new Set(cells.map((c) => c.cat).filter(Boolean))) as string[], [cells]);
  const cat = useMemo(() => Object.fromEntries(present.map((s) => [s, SOURCE_COLORS[s] ?? "#999"])), [present]);

  const chart = useMemo(() => {
    const rows = lb.data?.rows ?? [];
    const byLead: Record<number, Record<string, number | [number, number] | null>> = {};
    for (const r of rows) {
      byLead[r.lead_day] ??= { lead: r.lead_day } as never;
      byLead[r.lead_day][r.source] = r.rmse;
      byLead[r.lead_day][`${r.source}_err`] = r.rmse !== null && r.rmse_lo !== null && r.rmse_hi !== null ? [r.rmse - r.rmse_lo, r.rmse_hi - r.rmse] : null;
    }
    return { data: Object.values(byLead), names: Array.from(new Set(rows.map((r) => r.source))) };
  }, [lb.data]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3 text-sm">
        <h1 className="mr-auto text-2xl font-bold">Who to trust</h1>
        <select className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-1" value={region} onChange={(e) => { const r = e.target.value as Region; setRegion(r); setVariable(REGIONS.find((x) => x.id === r)!.variable); }}>
          {REGIONS.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
        </select>
        <select className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-1" value={variable} onChange={(e) => setVariable(e.target.value as Variable)}>
          <option value="precip">Rainfall</option>
          <option value="tmax">Max temperature</option>
        </select>
        <label className="flex items-center gap-2">Lead day {lead}<input type="range" min={1} max={5} value={lead} onChange={(e) => setLead(Number(e.target.value))} /></label>
      </div>
      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <Card title="Model with the lowest recent error per cell (leak-free decayed MSE)">
          {sm.loading && <Loading what="skill map" />}
          {sm.error && <ErrorBox error={sm.error} onRetry={sm.reload} />}
          {sm.data && <MapView cells={cells} categorical={cat} height={440} />}
          <div className="mt-2 flex flex-wrap gap-2 text-xs">
            {present.map((s) => <span key={s} className="flex items-center gap-1"><span className="inline-block h-3 w-3 rounded-sm" style={{ background: cat[s] }} />{label(s)}</span>)}
          </div>
          {sm.data && <p className="mt-1 text-xs text-[var(--muted)]">Half-life {sm.data.half_life_days} days · only verification finished before the run is used.</p>}
        </Card>
        <Card title="Share of cells">
          {present.length === 0 ? <Empty>No skill history yet.</Empty> : (
            <ul className="space-y-1 text-sm">
              {present.map((s) => {
                const n = cells.filter((c) => c.cat === s).length;
                return <li key={s} className="flex justify-between"><span>{label(s)}</span><span className="font-mono">{Math.round((100 * n) / cells.length)} %</span></li>;
              })}
            </ul>
          )}
        </Card>
      </div>
      <Card title="Leaderboard: RMSE by lead day with 95 % intervals (development split)">
        {lb.loading && <Loading what="leaderboard" />}
        {lb.error && <ErrorBox error={lb.error} onRetry={lb.reload} />}
        {lb.data && (
          <>
            <div className="h-80">
              <ResponsiveContainer>
                <LineChart data={chart.data} margin={{ left: 0, right: 8, top: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                  <XAxis dataKey="lead" fontSize={12} label={{ value: "lead day", position: "insideBottom", offset: -2, fontSize: 11 }} />
                  <YAxis fontSize={12} />
                  <Tooltip formatter={(v, n) => [fmt(Number(v), 2), label(String(n))]} />
                  <Legend formatter={(n) => label(String(n))} />
                  {chart.names.map((s) => (
                    <Line key={s} dataKey={s} stroke={SOURCE_COLORS[s] ?? "#888"} strokeDasharray={["equal_mean", "superensemble", "persistence", "climatology"].includes(s) ? "5 4" : undefined} dot>
                      <ErrorBar dataKey={`${s}_err`} width={3} stroke={SOURCE_COLORS[s] ?? "#888"} />
                    </Line>
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-[var(--muted)]"><tr><th className="py-1">Forecast</th><th>Lead</th><th>RMSE [95 % CI]</th><th>CRPS</th><th>ETS heavy</th><th>Cases</th></tr></thead>
                <tbody>
                  {lb.data.rows.filter((r) => r.lead_day === lead).sort((a, b) => (a.rmse ?? 1e9) - (b.rmse ?? 1e9)).map((r) => (
                    <tr key={r.source} className="border-t border-[var(--border)]">
                      <td className="py-1">{label(r.source)}</td><td>{r.lead_day}</td>
                      <td className="font-mono">{fmt(r.rmse, 2)} [{fmt(r.rmse_lo, 2)}, {fmt(r.rmse_hi, 2)}]</td>
                      <td className="font-mono">{fmt(r.crps, 2)}</td><td className="font-mono">{fmt(r.ets_heavy, 3)}</td><td>{r.n_cases}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-2 text-xs text-[var(--muted)]">{lb.data.period}. All rows scored on the same cases.</p>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}

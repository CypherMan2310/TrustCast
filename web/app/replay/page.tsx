"use client";

import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, Empty, ErrorBox, Loading, Pill, fmt } from "@/components/ui";
import { Replay, label, useApi } from "@/lib/api";
import { SOURCE_COLORS } from "@/lib/colors";

interface Index {
  events: { event_id: string; title: string; focus_day: string; district_id: string; variable: string }[];
}

function ReplayView({ id }: { id: string }) {
  const r = useApi<Replay>(`/v1/replay/${id}`);
  const [lead, setLead] = useState(1);
  const data = r.data;
  const days = useMemo(() => (data ? Object.keys(data.observed).sort() : []), [data]);
  const names = useMemo(() => (data ? Array.from(new Set(data.series.map((s) => s.forecast))) : []), [data]);
  const rows = useMemo(() => days.map((d) => {
    const row: Record<string, number | string | null> = { day: d.slice(5), observed: data!.observed[d] };
    for (const s of data!.series.filter((x) => x.lead_day === lead)) row[s.forecast] = s.values[d] ?? null;
    return row;
  }), [days, data, lead]);
  const focus = useMemo(() => {
    if (!data) return [];
    const leads = Array.from(new Set(data.series.map((s) => s.lead_day))).sort();
    return leads.map((l) => {
      const row: Record<string, number | string | null> = { lead: `${l} day${l > 1 ? "s" : ""} ahead` };
      for (const s of data.series.filter((x) => x.lead_day === l)) row[s.forecast] = s.values[data.focus_day] ?? null;
      return row;
    });
  }, [data]);
  if (r.loading) return <Loading what="event replay" />;
  if (r.error) return <ErrorBox error={r.error} onRetry={r.reload} />;
  if (!data) return null;
  const unit = data.variable === "precip" ? "mm" : "°C";
  return (
    <div className="space-y-4">
      <Card title={`${data.title}: ${data.district_id}`} right={<Pill>observed on {data.focus_day}: {fmt(data.observed[data.focus_day])} {unit}</Pill>}>
        <div className="mb-2 flex items-center gap-2 text-sm">Lead day
          {[1, 2, 3, 4, 5].map((l) => <button key={l} onClick={() => setLead(l)} className={`rounded px-2 py-0.5 ${lead === l ? "bg-[var(--chip)] font-medium" : ""}`}>{l}</button>)}
        </div>
        <div className="h-80">
          <ResponsiveContainer>
            <LineChart data={rows} margin={{ left: 0, right: 8, top: 8 }}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
              <XAxis dataKey="day" fontSize={12} />
              <YAxis fontSize={12} unit={unit === "°C" ? "°" : ""} />
              <Tooltip formatter={(v, n) => [`${fmt(Number(v))} ${unit}`, label(String(n))]} />
              <Legend formatter={(n) => (n === "observed" ? "Observed (IMD)" : label(String(n)))} />
              <ReferenceLine x={data.focus_day.slice(5)} stroke="#e11d48" strokeDasharray="4 3" />
              <Line dataKey="observed" stroke="#000" strokeWidth={2.5} dot={{ r: 3 }} />
              {names.map((n) => <Line key={n} dataKey={n} stroke={SOURCE_COLORS[n] ?? "#888"} strokeWidth={n === "trustcast" ? 3 : 1.2} dot={false} strokeDasharray={n === "equal_mean" ? "5 4" : undefined} />)}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Card>
      <Card title={`What each forecast said for ${data.focus_day}, by days ahead`}>
        <div className="h-80">
          <ResponsiveContainer>
            <BarChart data={focus} margin={{ left: 0, right: 8, top: 8 }}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
              <XAxis dataKey="lead" fontSize={12} />
              <YAxis fontSize={12} />
              <Tooltip formatter={(v, n) => [`${fmt(Number(v))} ${unit}`, label(String(n))]} />
              <Legend formatter={(n) => label(String(n))} />
              <ReferenceLine y={data.observed[data.focus_day] ?? undefined} stroke="#000" label={{ value: "observed", fontSize: 11 }} />
              {names.map((n) => <Bar key={n} dataKey={n} fill={SOURCE_COLORS[n] ?? "#888"} />)}
            </BarChart>
          </ResponsiveContainer>
        </div>
        {data.notes.length > 0 && <ul className="mt-2 list-disc pl-5 text-xs text-[var(--muted)]">{data.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
      </Card>
    </div>
  );
}

export default function ReplayPage() {
  const idx = useApi<Index>("/v1/replay");
  const [sel, setSel] = useState<string | null>(null);
  const current = sel ?? idx.data?.events[0]?.event_id ?? null;
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Replay real events</h1>
      {idx.loading && <Loading what="events" />}
      {idx.error && <ErrorBox error={idx.error} onRetry={idx.reload} />}
      {idx.data && idx.data.events.length === 0 && <Empty>No replays built yet (scripts/build_replays.py).</Empty>}
      {idx.data && idx.data.events.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {idx.data.events.map((e) => (
            <button key={e.event_id} onClick={() => setSel(e.event_id)} className={`rounded-lg border px-3 py-1.5 text-sm ${current === e.event_id ? "border-[var(--accent)] bg-[var(--chip)]" : "border-[var(--border)]"}`}>
              {e.title} <span className="text-xs text-[var(--muted)]">{e.focus_day}</span>
            </button>
          ))}
        </div>
      )}
      {current && <ReplayView key={current} id={current} />}
    </div>
  );
}

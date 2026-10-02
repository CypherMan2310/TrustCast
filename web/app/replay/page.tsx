"use client";

import { useMemo, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, Empty, ErrorBox, Icon, Loading, PageHeader, Pill, Segmented, Skeleton, fmt, fmtDate, tooltipStyle } from "@/components/ui";
import { Replay, label, useApi } from "@/lib/api";
import { SOURCE_COLORS } from "@/lib/colors";
import { useTrainingReporter } from "@/components/training/TrainingProvider";

interface Index {
  events: { event_id: string; title: string; focus_day: string; district_id: string; variable: string }[];
}

const prettyDistrict = (id: string) =>
  id
    .split("-")
    .slice(1)
    .join(" ")
    .replace(/\b\w/g, (c) => c.toUpperCase()) || id;

function ReplayView({ id }: { id: string }) {
  const r = useApi<Replay>(`/v1/replay/${id}`);
  const [lead, setLeadState] = useState(1);
  const report = useTrainingReporter();
  const setLead = (l: number) => {
    setLeadState(l);
    report({ type: "replay-lead", lead: l });
  };
  const data = r.data;
  const days = useMemo(() => (data ? Object.keys(data.observed).sort() : []), [data]);
  const names = useMemo(() => (data ? Array.from(new Set(data.series.map((s) => s.forecast))) : []), [data]);
  const rows = useMemo(
    () =>
      days.map((d) => {
        const row: Record<string, number | string | null> = { day: d, observed: data!.observed[d] };
        for (const s of data!.series.filter((x) => x.lead_day === lead)) row[s.forecast] = s.values[d] ?? null;
        return row;
      }),
    [days, data, lead],
  );
  if (r.loading)
    return (
      <div className="space-y-6">
        <Skeleton className="h-40 rounded-2xl" />
        <Skeleton className="h-96 rounded-2xl" />
      </div>
    );
  if (r.error) return <ErrorBox error={r.error} onRetry={r.reload} />;
  if (!data) return null;
  const unit = data.variable === "precip" ? "mm" : "°C";
  const obs = data.observed[data.focus_day];
  const said = names
    .map((n) => ({ n, v: data.series.find((s) => s.forecast === n && s.lead_day === lead)?.values[data.focus_day] ?? null }))
    .filter((x) => x.v !== null && x.v !== undefined) as { n: string; v: number }[];
  const scaleMax = Math.max(obs ?? 0, ...said.map((x) => x.v), 1) * 1.08;
  const scaleMin = data.variable === "precip" ? 0 : Math.min(obs ?? 0, ...said.map((x) => x.v)) - 2;
  const pos = (v: number) => `${(100 * (v - scaleMin)) / (scaleMax - scaleMin)}%`;

  return (
    <div className="space-y-6">
      <Card
        tour="scorecard"
        title={`What each forecast said ${lead} day${lead > 1 ? "s" : ""} ahead`}
        subtitle={`${prettyDistrict(data.district_id)} · ${fmtDate(data.focus_day, { weekday: "long", day: "numeric", month: "long", year: "numeric" })}`}
        right={
          <div data-tour="replay-lead">
            <Segmented size="sm" ariaLabel="Days ahead" value={lead} onChange={setLead} options={[1, 2, 3, 4, 5].map((l) => ({ value: l, label: `${l}d` }))} />
          </div>
        }
      >
        <div className="grid gap-6 lg:grid-cols-[220px_1fr]">
          <div className="rounded-2xl bg-[var(--surface-2)] p-5">
            <div className="text-xs font-medium text-[var(--muted)]">Observed (IMD)</div>
            <div className="tabular mt-1 text-4xl font-semibold tracking-tight">
              {fmt(obs)}
              <span className="ml-1 text-base font-normal text-[var(--muted)]">{unit}</span>
            </div>
            <div className="mt-1 text-xs text-[var(--muted)]">district average</div>
          </div>
          <div className="space-y-2.5">
            {[...said]
              .sort((a, b) => Math.abs(a.v - (obs ?? 0)) - Math.abs(b.v - (obs ?? 0)))
              .map(({ n, v }) => {
                const c = SOURCE_COLORS[n] ?? "#94a3b8";
                const tc = n === "trustcast";
                return (
                  <div key={n} className="grid grid-cols-[150px_1fr_70px] items-center gap-3 text-sm">
                    <span className={`truncate ${tc ? "font-semibold" : ""}`}>{label(n)}</span>
                    <span className="relative h-5 rounded-full bg-[var(--chip)]">
                      <span className="absolute inset-y-0 left-0 rounded-full" style={{ width: pos(v), background: tc ? "linear-gradient(90deg,var(--accent),var(--accent-2))" : c, opacity: tc ? 1 : 0.75 }} />
                      {obs !== null && obs !== undefined && <span className="absolute -inset-y-1 w-0.5 rounded bg-[var(--text)]" style={{ left: pos(obs) }} title="observed" />}
                    </span>
                    <span className="tabular text-right text-xs font-medium">
                      {fmt(v)} {unit}
                    </span>
                  </div>
                );
              })}
            <p className="pt-1 text-[11px] text-[var(--faint)]">Sorted by closeness to the observation (black line).</p>
          </div>
        </div>
      </Card>

      <Card title="The event, day by day" subtitle={`Forecasts made ${lead} day${lead > 1 ? "s" : ""} ahead against IMD observations; the dashed line marks the peak day`}>
        <div className="h-80">
          <ResponsiveContainer>
            <LineChart data={rows} margin={{ left: -10, right: 8, top: 8 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="day" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(d) => fmtDate(String(d), { day: "numeric", month: "short" })} />
              <YAxis fontSize={12} tickLine={false} axisLine={false} unit={unit === "°C" ? "°" : ""} domain={["auto", "auto"]} />
              <Tooltip {...tooltipStyle} labelFormatter={(d) => fmtDate(String(d))} formatter={(v, n) => [`${fmt(Number(v))} ${unit}`, n === "observed" ? "Observed (IMD)" : label(String(n))]} />
              <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} formatter={(n) => (n === "observed" ? "Observed (IMD)" : label(String(n)))} />
              <ReferenceLine x={data.focus_day} stroke="var(--bad)" strokeDasharray="4 3" />
              <Line dataKey="observed" stroke="var(--text)" strokeWidth={2.5} dot={{ r: 3 }} isAnimationActive={false} />
              {names.map((n) => (
                <Line
                  key={n}
                  dataKey={n}
                  type="monotone"
                  stroke={n === "trustcast" ? "#4f46e5" : (SOURCE_COLORS[n] ?? "#94a3b8")}
                  strokeWidth={n === "trustcast" ? 3 : 1.4}
                  strokeOpacity={n === "trustcast" ? 1 : 0.8}
                  dot={false}
                  strokeDasharray={n === "equal_mean" ? "5 4" : undefined}
                  connectNulls
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Card>

      {data.notes.length > 0 && (
        <Card title="Notes" subtitle="How to read this replay honestly">
          <ul className="space-y-2 text-sm">
            {data.notes.map((n) => (
              <li key={n} className="flex gap-2">
                <Icon name="info" className="mt-0.5 h-4 w-4 shrink-0 text-[var(--faint)]" />
                <span className="text-[var(--muted)]">{n}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

export default function ReplayPage() {
  const report = useTrainingReporter();
  const idx = useApi<Index>("/v1/replay");
  const [sel, setSel] = useState<string | null>(null);
  const current = sel ?? idx.data?.events[0]?.event_id ?? null;
  return (
    <div className="space-y-6">
      <PageHeader title="Event replay" icon="replay" subtitle="Go back to real high-impact events and see what each model, and the blend, said beforehand" />
      {idx.loading && (
        <div className="grid gap-3 md:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-28 rounded-2xl" />)}
        </div>
      )}
      {idx.error && <ErrorBox error={idx.error} onRetry={idx.reload} />}
      {idx.data && idx.data.events.length === 0 && <Empty>No replays built yet (scripts/build_replays.py).</Empty>}
      {idx.data && idx.data.events.length > 0 && (
        <div data-tour="event-cards" className="grid gap-3 md:grid-cols-3">
          {idx.data.events.map((e) => {
            const on = current === e.event_id;
            return (
              <button
                key={e.event_id}
                onClick={() => {
                  setSel(e.event_id);
                  report({ type: "replay-selected", id: e.event_id, title: e.title });
                }}
                className={`flex gap-3 rounded-2xl border p-4 text-left shadow-[var(--shadow)] transition ${
                  on ? "border-[var(--accent)] bg-[var(--accent-soft)]/60 ring-2 ring-[var(--ring)]" : "border-[var(--border)] bg-[var(--surface)] hover:border-[var(--faint)]"
                }`}
              >
                <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl ${e.variable === "precip" ? "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300" : "bg-orange-100 text-orange-700 dark:bg-orange-500/15 dark:text-orange-300"}`}>
                  <Icon name={e.variable === "precip" ? "drop" : "thermo"} className="h-5 w-5" />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-semibold">{e.title}</span>
                  <span className="mt-0.5 block text-xs text-[var(--muted)]">
                    {prettyDistrict(e.district_id)} · {fmtDate(e.focus_day)}
                  </span>
                  <span className="mt-2 inline-block">
                    <Pill>{e.variable === "precip" ? "heavy rain" : "heat"}</Pill>
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      )}
      {current ? <ReplayView key={current} id={current} /> : idx.data && <Loading />}
    </div>
  );
}

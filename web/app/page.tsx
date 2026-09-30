"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import MapView, { Legend } from "@/components/MapView";
import { Card, Empty, ErrorBox, Loading, Pill, fmt } from "@/components/ui";
import { GridLayer, REGIONS, Region, Variable, label, useApi } from "@/lib/api";
import { stopsFor } from "@/lib/colors";

interface Alerts {
  init_time: string;
  rule: string;
  alerts: { district_id: string; district: string; state: string; lead_day: number; valid_day: string; level: string; probability: number | null; value: number | null; defer: boolean; coverage: number }[];
}

function layerLabel(l: string): string {
  if (l === "final") return "TRUSTCAST blend";
  if (l === "consensus") return "Equal-weight consensus";
  if (l === "disagreement") return "Model disagreement (std)";
  if (l === "lo90") return "90 % range: lower";
  if (l === "hi90") return "90 % range: upper";
  if (l === "defer") return "Low-confidence flag";
  if (l.startsWith("prob_ge_")) return `P(≥ ${l.replace("prob_ge_", "")})`;
  if (l.startsWith("source:")) return `Model: ${label(l.slice(7))}`;
  return l;
}

const LEVEL_TONE: Record<string, "bad" | "warn" | "neutral"> = { red: "bad", orange: "warn", yellow: "warn" };

export default function Home() {
  const router = useRouter();
  const [region, setRegion] = useState<Region>("rain_pilot");
  const [variable, setVariable] = useState<Variable>("precip");
  const [lead, setLead] = useState(1);
  const [layer, setLayer] = useState("final");
  const [init, setInit] = useState<string>("");
  const [mountedAt] = useState(() => Date.now()); // read the clock once, not during every render

  const products = useApi<{ products: Record<string, string[]> }>("/v1/products");
  const inits = products.data?.products[`${region}/${variable}`] ?? [];
  const q = `region=${region}&variable=${variable}&lead_day=${lead}&layer=${encodeURIComponent(layer)}${init ? `&init=${init}` : ""}`;
  const grid = useApi<GridLayer>(`/v1/forecast/grid?${q}`);
  const meta = useApi<{ regions: Record<string, { districts: GeoJSON.FeatureCollection | null }> }>("/v1/meta/regions");
  const alerts = useApi<Alerts>(`/v1/alerts/district?region=${region}&variable=${variable}${init ? `&init=${init}` : ""}`);

  const cells = useMemo(() => {
    const g = grid.data;
    if (!g) return [];
    const out: { lat: number; lon: number; v: number | null }[] = [];
    g.lats.forEach((la, i) => g.lons.forEach((lo, j) => out.push({ lat: la, lon: lo, v: g.values[i][j] })));
    return out;
  }, [grid.data]);
  const stops = stopsFor(layer, variable);
  const units = grid.data?.units ?? "";

  const pickRegion = (r: Region) => {
    setRegion(r);
    setVariable(REGIONS.find((x) => x.id === r)!.variable);
    setLayer("final");
    setInit("");
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
      <div className="space-y-3">
        <Card>
          <div className="flex flex-wrap items-end gap-3 text-sm">
            <label className="flex flex-col gap-1">
              <span className="text-xs text-[var(--muted)]">Region</span>
              <select className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-1" value={region} onChange={(e) => pickRegion(e.target.value as Region)}>
                {REGIONS.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-[var(--muted)]">Variable</span>
              <select className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-1" value={variable} onChange={(e) => { setVariable(e.target.value as Variable); setLayer("final"); }}>
                <option value="precip">24 h rainfall (IMD day)</option>
                <option value="tmax">Maximum temperature</option>
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-[var(--muted)]">Layer</span>
              <select className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-1" value={layer} onChange={(e) => setLayer(e.target.value)}>
                {(grid.data?.available_layers ?? ["final"]).map((l) => <option key={l} value={l}>{layerLabel(l)}</option>)}
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-[var(--muted)]">Run (00 UTC)</span>
              <select className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-1" value={init} onChange={(e) => setInit(e.target.value)}>
                <option value="">latest</option>
                {inits.map((s) => <option key={s} value={s}>{`${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6)}`}</option>)}
              </select>
            </label>
            <label className="flex min-w-48 flex-1 flex-col gap-1">
              <span className="text-xs text-[var(--muted)]">Lead day {lead}{grid.data ? ` · ${variable === "precip" ? "IMD day ending 08:30 IST" : "day of maximum"} ${grid.data.valid_day}` : ""}</span>
              <input type="range" min={1} max={5} value={lead} onChange={(e) => setLead(Number(e.target.value))} aria-label="Lead day" />
            </label>
          </div>
        </Card>
        {grid.error ? (
          <ErrorBox error={grid.error} onRetry={grid.reload} />
        ) : (
          <div className="relative">
            {grid.loading && <div className="absolute left-3 top-3 z-10 rounded bg-[var(--surface)]/90"><Loading what="forecast grid" /></div>}
            <MapView
              cells={cells}
              stops={stops}
              districts={meta.data?.regions[region]?.districts ?? null}
              onDistrictClick={(id) => router.push(`/district/${id}?variable=${variable}${init ? `&init=${init}` : ""}`)}
              formatValue={(v) => (units === "probability" ? `${Math.round(v * 100)} %` : `${fmt(v)} ${units}`)}
            />
          </div>
        )}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Legend stops={stops} units={units === "probability" ? "probability" : units} />
          {grid.data && (
            <span className="flex items-center gap-2 text-xs text-[var(--muted)]">
              {mountedAt - Date.parse(grid.data.init_time) > 2 * 86400e3 && <Pill tone="warn">not today&apos;s run: newest available product is from {grid.data.init_time.slice(0, 10)}</Pill>}
              Run {grid.data.init_time.slice(0, 10)} 00 UTC · click a district for its card
            </span>
          )}
        </div>
      </div>
      <Card title="District alerts" right={alerts.data && <span className="text-xs text-[var(--muted)]">{alerts.data.alerts.length}</span>}>
        {alerts.loading && <Loading what="alerts" />}
        {alerts.error && <ErrorBox error={alerts.error} onRetry={alerts.reload} />}
        {alerts.data && alerts.data.alerts.length === 0 && <Empty>No district above yellow level for this run.</Empty>}
        {alerts.data && alerts.data.alerts.length > 0 && (
          <ul className="max-h-[560px] space-y-1 overflow-auto">
            {alerts.data.alerts
              .sort((a, b) => (b.probability ?? 0) - (a.probability ?? 0))
              .map((a) => (
                <li key={`${a.district_id}-${a.lead_day}`}>
                  <Link href={`/district/${a.district_id}?variable=${variable}${init ? `&init=${init}` : ""}`} className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 hover:bg-[var(--chip)]">
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium">{a.district}</span>
                      <span className="text-xs text-[var(--muted)]">day {a.lead_day} · {a.valid_day}{a.coverage < 0.5 ? " · partial" : ""}</span>
                    </span>
                    <span className="flex items-center gap-1">
                      {a.defer && <Pill tone="warn">review</Pill>}
                      <Pill tone={LEVEL_TONE[a.level] ?? "neutral"}>{a.level} {a.probability !== null ? `${Math.round(a.probability * 100)}%` : ""}</Pill>
                    </span>
                  </Link>
                </li>
              ))}
          </ul>
        )}
        {alerts.data && <p className="mt-2 text-xs text-[var(--muted)]">Rule: {alerts.data.rule}</p>}
      </Card>
    </div>
  );
}

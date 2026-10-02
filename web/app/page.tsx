"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import MapView, { Legend } from "@/components/MapView";
import { Card, Empty, ErrorBox, Icon, Loading, PageHeader, Pill, Segmented, Select, Skeleton, Stat, fmt, fmtDate } from "@/components/ui";
import { GridLayer, REGIONS, Region, Variable, label, useApi } from "@/lib/api";
import { stopsFor } from "@/lib/colors";

interface Alerts {
  init_time: string;
  rule: string;
  alerts: { district_id: string; district: string; state: string; lead_day: number; valid_day: string; level: string; probability: number | null; value: number | null; defer: boolean; coverage: number }[];
}

const MAIN_LAYERS = ["final", "consensus", "disagreement", "defer"];

function layerLabel(l: string): string {
  if (l === "final") return "TRUSTCAST blend";
  if (l === "consensus") return "Equal-weight mean";
  if (l === "disagreement") return "Model disagreement";
  if (l === "lo90") return "90 % range: low";
  if (l === "hi90") return "90 % range: high";
  if (l === "defer") return "Low confidence";
  if (l.startsWith("prob_ge_")) return `Chance ≥ ${l.replace("prob_ge_", "")}`;
  if (l.startsWith("source:")) return label(l.slice(7));
  return l;
}

const LEVEL: Record<string, { bar: string; tone: "bad" | "warn" | "neutral" }> = {
  red: { bar: "bg-rose-500", tone: "bad" },
  orange: { bar: "bg-orange-500", tone: "warn" },
  yellow: { bar: "bg-yellow-400", tone: "warn" },
};

const DAY = 86400e3;

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

  const g = grid.data;
  const cells = useMemo(() => {
    if (!g) return [];
    const out: { lat: number; lon: number; v: number | null }[] = [];
    g.lats.forEach((la, i) => g.lons.forEach((lo, j) => out.push({ lat: la, lon: lo, v: g.values[i][j] })));
    return out;
  }, [g]);
  const stops = stopsFor(layer, variable);
  const units = g?.units ?? "";
  const isProb = units === "probability";
  const isValueLayer = !isProb && layer !== "disagreement" && layer !== "defer";
  const thr = variable === "precip" ? 64.5 : 40;
  const unit = variable === "precip" ? "mm" : "°C";

  const stats = useMemo(() => {
    const vals = cells.map((c) => c.v).filter((v): v is number => v !== null && Number.isFinite(v));
    if (!vals.length) return null;
    const max = Math.max(...vals);
    const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
    const above = vals.filter((v) => v >= thr).length / vals.length;
    return { max, mean, above, n: vals.length };
  }, [cells, thr]);

  // date of each lead tab, aligned with the API's label for the selected lead
  const tabDate = (l: number) => {
    if (!g) return "";
    const off = Date.parse(g.valid_day) - Date.parse(g.init_time.slice(0, 10)) - g.lead_day * DAY;
    return fmtDate(new Date(Date.parse(g.init_time.slice(0, 10)) + l * DAY + off).toISOString(), { day: "numeric", month: "short" });
  };

  const layers = g?.available_layers ?? ["final"];
  const extraLayers = layers.filter((l) => !MAIN_LAYERS.includes(l));
  const nAlerts = alerts.data?.alerts.length ?? 0;
  const nReview = alerts.data?.alerts.filter((a) => a.defer).length ?? 0;
  const stale = g && mountedAt - Date.parse(g.init_time) > 2 * DAY;

  const pickRegion = (r: Region) => {
    setRegion(r);
    setVariable(REGIONS.find((x) => x.id === r)!.variable);
    setLayer("final");
    setInit("");
  };
  const openDistrict = (id: string) => router.push(`/district/${id}?variable=${variable}${init ? `&init=${init}` : ""}`);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Forecast"
        icon="map"
        subtitle={
          g ? (
            <>
              One blended forecast from five AI and physics models, on the IMD 0.25° grid · run{" "}
              <span className="font-medium text-[var(--text)]">{fmtDate(g.init_time)} 00 UTC</span>
            </>
          ) : (
            "One blended forecast from five AI and physics models, on the IMD 0.25° grid"
          )
        }
        actions={
          <>
            <Segmented
              ariaLabel="Region"
              value={region}
              onChange={pickRegion}
              options={[
                { value: "rain_pilot", label: "Kerala coast" },
                { value: "heat_pilot", label: "Vidarbha" },
              ]}
            />
            <Segmented
              ariaLabel="Variable"
              value={variable}
              onChange={(v) => {
                setVariable(v);
                setLayer("final");
              }}
              options={[
                { value: "precip", label: <span className="flex items-center gap-1.5"><Icon name="drop" className="h-3.5 w-3.5" />Rain</span> },
                { value: "tmax", label: <span className="flex items-center gap-1.5"><Icon name="thermo" className="h-3.5 w-3.5" />Max temp</span> },
              ]}
            />
          </>
        }
      />

      {stale && (
        <div className="flex items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs text-[var(--muted)]">
          <Icon name="clock" className="h-4 w-4 text-[var(--warn)]" />
          Showing the newest available product ({fmtDate(g!.init_time)}), not today&apos;s run.
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        {!stats ? (
          Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-[104px] rounded-2xl" />)
        ) : (
          <>
            <Stat
              label={isProb ? "Highest chance" : isValueLayer ? "Region maximum" : "Highest value"}
              icon={variable === "precip" ? "drop" : "thermo"}
              value={isProb ? `${Math.round(stats.max * 100)}%` : fmt(stats.max)}
              unit={isProb ? undefined : units}
              tone="accent"
              hint={`${layerLabel(layer)} · day ${lead}`}
            />
            <Stat label="Region average" icon="layers" value={isProb ? `${Math.round(stats.mean * 100)}%` : fmt(stats.mean)} unit={isProb ? undefined : units} hint={`${stats.n} land cells`} />
            <Stat
              label={variable === "precip" ? "Area with heavy rain" : "Area at heatwave level"}
              icon="alert"
              value={isValueLayer ? `${Math.round(stats.above * 100)}%` : "–"}
              tone={isValueLayer && stats.above > 0 ? "warn" : "neutral"}
              hint={isValueLayer ? `cells ≥ ${thr} ${unit}` : "for value layers only"}
            />
            <Stat
              label="District alerts"
              icon="trust"
              value={alerts.loading ? "…" : nAlerts}
              tone={nAlerts ? "bad" : "ok"}
              hint={nReview ? `${nReview} flagged for forecaster review` : "no low-confidence flags"}
            />
          </>
        )}
      </div>

      <div className="grid gap-6 xl:grid-cols-[1fr_360px]">
        <Card pad={false} className="overflow-hidden">
          <div className="flex flex-wrap items-center gap-3 border-b border-[var(--border)] px-4 py-3">
            <Segmented
              size="sm"
              ariaLabel="Lead day"
              value={lead}
              onChange={setLead}
              options={[1, 2, 3, 4, 5].map((l) => ({
                value: l,
                label: (
                  <span className="flex flex-col items-center leading-tight">
                    <span>Day {l}</span>
                    {g && <span className="text-[10px] font-normal opacity-70">{tabDate(l)}</span>}
                  </span>
                ),
              }))}
            />
            <div className="ml-auto flex flex-wrap items-end gap-2">
              <Select value={layer} onChange={setLayer}>
                <optgroup label="Blend">
                  {layers.filter((l) => MAIN_LAYERS.includes(l)).map((l) => <option key={l} value={l}>{layerLabel(l)}</option>)}
                </optgroup>
                {extraLayers.some((l) => !l.startsWith("source:")) && (
                  <optgroup label="Uncertainty & events">
                    {extraLayers.filter((l) => !l.startsWith("source:")).map((l) => <option key={l} value={l}>{layerLabel(l)}</option>)}
                  </optgroup>
                )}
                {extraLayers.some((l) => l.startsWith("source:")) && (
                  <optgroup label="Single models">
                    {extraLayers.filter((l) => l.startsWith("source:")).map((l) => <option key={l} value={l}>{layerLabel(l)}</option>)}
                  </optgroup>
                )}
              </Select>
              <Select value={init} onChange={setInit}>
                <option value="">Latest run</option>
                {inits.map((s) => <option key={s} value={s}>{fmtDate(s)}</option>)}
              </Select>
            </div>
          </div>
          {grid.error ? (
            <div className="p-4"><ErrorBox error={grid.error} onRetry={grid.reload} /></div>
          ) : (
            <div className="relative">
              {grid.loading && (
                <div className="absolute top-3 left-3 z-10 flex items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--surface)]/95 px-3 py-1.5 text-xs text-[var(--muted)] shadow-[var(--shadow)]">
                  <span className="h-3 w-3 animate-spin rounded-full border-2 border-[var(--accent)] border-t-transparent" />
                  Loading map…
                </div>
              )}
              <MapView
                cells={cells}
                stops={stops}
                height="min(560px, 70vh)"
                districts={meta.data?.regions[region]?.districts ?? null}
                onDistrictClick={openDistrict}
                formatValue={(v) => (isProb ? `${Math.round(v * 100)} %` : `${fmt(v)} ${units}`)}
              />
            </div>
          )}
          <div className="flex flex-wrap items-end justify-between gap-4 border-t border-[var(--border)] px-4 py-3">
            <div className="w-full max-w-xl">
              <Legend stops={stops} units={units} title={layerLabel(layer)} />
            </div>
            {g && (
              <span className="text-xs text-[var(--muted)]">
                {variable === "precip" ? "24 h to 08:30 IST" : "day of maximum"} {fmtDate(g.valid_day)} · click a district to open it
              </span>
            )}
          </div>
        </Card>

        <Card
          title="District alerts"
          subtitle={alerts.data ? `Run ${fmtDate(alerts.data.init_time)} · all 5 days` : undefined}
          right={alerts.data && <Pill tone={nAlerts ? "bad" : "ok"} dot>{nAlerts}</Pill>}
          className="xl:sticky xl:top-6 xl:self-start"
        >
          {alerts.loading && <Loading what="alerts" rows={5} />}
          {alerts.error && <ErrorBox error={alerts.error} onRetry={alerts.reload} />}
          {alerts.data && nAlerts === 0 && <Empty icon="check">No district above yellow level for this run.</Empty>}
          {alerts.data && nAlerts > 0 && (
            <ul className="-mx-2 max-h-[600px] space-y-1 overflow-auto px-2">
              {[...alerts.data.alerts]
                .sort((a, b) => (b.probability ?? 0) - (a.probability ?? 0))
                .map((a) => {
                  const lv = LEVEL[a.level] ?? { bar: "bg-[var(--faint)]", tone: "neutral" as const };
                  return (
                    <li key={`${a.district_id}-${a.lead_day}`}>
                      <Link
                        href={`/district/${a.district_id}?variable=${variable}${init ? `&init=${init}` : ""}`}
                        className="group flex gap-3 rounded-xl border border-transparent p-2.5 transition hover:border-[var(--border)] hover:bg-[var(--surface-2)]"
                      >
                        <span className={`w-1 shrink-0 rounded-full ${lv.bar}`} />
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center justify-between gap-2">
                            <span className="truncate text-sm font-medium">{a.district}</span>
                            <Pill tone={lv.tone}>{a.level}</Pill>
                          </span>
                          <span className="mt-0.5 block text-xs text-[var(--muted)]">
                            {a.state} · day {a.lead_day} · {fmtDate(a.valid_day, { day: "numeric", month: "short" })}
                            {a.value !== null && ` · ${fmt(a.value)} ${unit}`}
                          </span>
                          {a.probability !== null && (
                            <span className="mt-1.5 flex items-center gap-2">
                              <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--chip)]">
                                <span className={`block h-full rounded-full ${lv.bar}`} style={{ width: `${Math.round(a.probability * 100)}%` }} />
                              </span>
                              <span className="tabular w-9 text-right text-xs font-medium">{Math.round(a.probability * 100)}%</span>
                            </span>
                          )}
                          {(a.defer || a.coverage < 0.5) && (
                            <span className="mt-1.5 flex gap-1">
                              {a.defer && <Pill tone="warn">forecaster review</Pill>}
                              {a.coverage < 0.5 && <Pill>partly in region</Pill>}
                            </span>
                          )}
                        </span>
                      </Link>
                    </li>
                  );
                })}
            </ul>
          )}
          {alerts.data && <p className="mt-3 border-t border-[var(--border)] pt-3 text-xs text-[var(--muted)]">Rule: {alerts.data.rule}</p>}
        </Card>
      </div>
    </div>
  );
}

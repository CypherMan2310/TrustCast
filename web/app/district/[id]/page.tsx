"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Area, Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Button, Card, ErrorBox, Icon, Loading, Pill, Segmented, Skeleton, fmt, fmtDate, inputCls, tooltipStyle } from "@/components/ui";
import { API_BASE, DistrictPayload, Variable, apiPost, label, useApi } from "@/lib/api";
import { SOURCE_COLORS } from "@/lib/colors";
import { useTrainingReporter, useTrainingRunning } from "@/components/training/TrainingProvider";

interface BulletinResp {
  text: string;
  validated: boolean;
  validation_errors: string[];
}

const OVERRIDE_SOURCES = ["ecmwf_ifs_ctrl", "ecmwf_aifs", "ncep_gfs", "ecmwf_ifs_ens", "ecmwf_aifs_ens"];

function OverrideForm({ districtId, variable, days }: { districtId: string; variable: Variable; days: string[] }) {
  const report = useTrainingReporter();
  const sandbox = useTrainingRunning();
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      const r = await apiPost<{ id: number; effect: string }>("/v1/feedback/override", {
        district_id: districtId,
        variable,
        valid_day: f.get("valid_day"),
        value: f.get("value") ? Number(f.get("value")) : null,
        distrust_sources: f.getAll("distrust"),
        reason: f.get("reason"),
        author: f.get("author"),
      });
      setMsg(sandbox ? r.effect : `Saved override #${r.id}: ${r.effect}`);
      report({ type: "override-saved" });
      form.reset();
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={submit} className="space-y-4 text-sm">
      <div className="grid grid-cols-2 gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium text-[var(--muted)]">Day</span>
          <select name="valid_day" className={inputCls}>
            {days.map((d) => <option key={d} value={d}>{fmtDate(d)}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium text-[var(--muted)]">Your value ({variable === "precip" ? "mm" : "°C"}, optional)</span>
          <input name="value" type="number" step="0.1" className={inputCls} />
        </label>
      </div>
      <fieldset>
        <legend className="mb-2 text-xs font-medium text-[var(--muted)]">Models you distrust here (their weight drops for about a week)</legend>
        <div className="flex flex-wrap gap-2">
          {OVERRIDE_SOURCES.map((s) => (
            <label key={s} className="cursor-pointer">
              <input type="checkbox" name="distrust" value={s} className="peer sr-only" />
              <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--border)] px-3 py-1 text-xs transition peer-checked:border-[var(--bad)] peer-checked:bg-rose-50 peer-checked:text-rose-700 peer-focus-visible:ring-2 peer-focus-visible:ring-[var(--ring)] dark:peer-checked:bg-rose-500/10 dark:peer-checked:text-rose-300">
                <span className="h-2 w-2 rounded-full" style={{ background: SOURCE_COLORS[s] }} />
                {label(s)}
              </span>
            </label>
          ))}
        </div>
      </fieldset>
      <textarea name="reason" required minLength={5} placeholder="Reason (required), e.g. model misses the orographic rain on the Ghats" className={`${inputCls} h-20 py-2`} />
      <div className="flex items-center gap-2">
        <input name="author" required placeholder="Your name / ID" className={inputCls} />
        <Button disabled={busy} className="shrink-0">{busy ? "Saving…" : "Save override"}</Button>
      </div>
      {msg && (
        <p className="flex items-center gap-2 rounded-xl bg-emerald-50 px-3 py-2 text-xs text-emerald-800 dark:bg-emerald-500/10 dark:text-emerald-300">
          <Icon name="check" /> {msg}
        </p>
      )}
      {err && <ErrorBox error={err} />}
    </form>
  );
}

function DistrictInner() {
  const raw = useParams<{ id: string }>().id;
  const id = decodeURIComponent(raw); // ids can contain non-ASCII letters (e.g. telangāna-...)
  const eid = encodeURIComponent(id);
  const sp = useSearchParams();
  const variable = (sp.get("variable") as Variable) ?? "precip";
  const init = sp.get("init");
  const [lang, setLangState] = useState<"en" | "hi">("en");
  const report = useTrainingReporter();
  const sandbox = useTrainingRunning();
  const setLang = (l: "en" | "hi") => {
    setLangState(l);
    report({ type: "bulletin-lang", lang: l });
  };
  const [sel, setSel] = useState(1);
  const q = `variable=${variable}${init ? `&init=${init}` : ""}`;
  const d = useApi<DistrictPayload>(`/v1/district/${eid}?${q}`);
  const b = useApi<BulletinResp>(`/v1/bulletin/${eid}?${q}&lang=${lang}`);

  if (d.loading)
    return (
      <div className="space-y-6">
        <Skeleton className="h-16 w-80" />
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-36 rounded-2xl" />)}</div>
        <Skeleton className="h-72 rounded-2xl" />
      </div>
    );
  if (d.error) return <ErrorBox error={d.error} onRetry={d.reload} />;
  if (!d.data) return null;
  const dist = d.data.district;
  const unit = variable === "precip" ? "mm" : "°C";
  const thr = variable === "precip" ? "64.5" : "40.0";
  const probOf = (l: (typeof dist.leads)[number]) => {
    const p = l.probabilities[thr];
    return p === null || p === undefined ? null : p;
  };
  const rows = dist.leads.map((l) => ({
    day: `Day ${l.lead_day}`,
    value: l.value,
    band: l.lo90 !== null && l.hi90 !== null ? [l.lo90, l.hi90] : null,
    prob: probOf(l) !== null ? Math.round(100 * (probOf(l) as number)) : null,
  }));
  const sources = Object.keys(dist.leads[0]?.weights ?? {});
  const wrows = dist.leads.map((l) => ({ day: `Day ${l.lead_day}`, ...Object.fromEntries(Object.entries(l.weights).map(([k, v]) => [k, Math.round(v * 1000) / 10])) }));
  const cur = dist.leads.find((l) => l.lead_day === sel) ?? dist.leads[0];
  const curWeights = Object.entries(cur?.weights ?? {}).filter(([, w]) => w >= 0.005).sort((a, b) => b[1] - a[1]);
  const prov = typeof d.data.meta.config_provenance === "string" ? d.data.meta.config_provenance : null;
  const avail = (d.data.meta.sources_available as Record<string, string[]> | undefined)?.[d.data.init_time.slice(0, 10)];

  return (
    <div className="space-y-6">
      <div>
        <Link href="/" className="inline-flex items-center gap-1 text-sm text-[var(--muted)] hover:text-[var(--text)]">
          <Icon name="arrowLeft" /> Forecast map
        </Link>
        <div className="mt-2 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">{dist.district}</h1>
            <p className="mt-1 text-sm text-[var(--muted)]">
              {dist.state} · {variable === "precip" ? "24 h rainfall (IMD day ending 08:30 IST)" : "daily maximum temperature"} · run {fmtDate(d.data.init_time)} 00 UTC
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {dist.coverage < 0.5 && <Pill tone="warn" dot>{Math.round(dist.coverage * 100)} % of district inside pilot region</Pill>}
            {avail && <Pill tone={avail.length >= 3 ? "accent" : "warn"} dot>{avail.length} model{avail.length === 1 ? "" : "s"} in this run</Pill>}
            {dist.leads.some((l) => l.defer) ? <Pill tone="warn" dot>low confidence on some days</Pill> : <Pill tone="ok" dot>models broadly agree</Pill>}
          </div>
        </div>
      </div>

      {/* five-day strip */}
      <div data-tour="day-strip" className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {dist.leads.map((l) => {
          const p = probOf(l);
          const on = l.lead_day === sel;
          return (
            <button
              key={l.lead_day}
              onClick={() => {
                setSel(l.lead_day);
                report({ type: "day-selected", lead: l.lead_day });
              }}
              className={`rounded-2xl border p-4 text-left shadow-[var(--shadow)] transition ${
                on ? "border-[var(--accent)] bg-[var(--accent-soft)]/60 ring-2 ring-[var(--ring)]" : "border-[var(--border)] bg-[var(--surface)] hover:border-[var(--faint)]"
              }`}
            >
              <div className="flex items-center justify-between text-xs font-medium text-[var(--muted)]">
                <span>Day {l.lead_day}</span>
                <span>{fmtDate(l.valid_day, { weekday: "short", day: "numeric", month: "short" })}</span>
              </div>
              <div className="tabular mt-2 text-3xl font-semibold tracking-tight">
                {fmt(l.value)}
                <span className="ml-1 text-sm font-normal text-[var(--muted)]">{unit}</span>
              </div>
              <div className="tabular text-xs text-[var(--muted)]">{l.lo90 !== null ? `90 % range ${fmt(l.lo90)}–${fmt(l.hi90)}` : "range n/a"}</div>
              {p === null && <div className="mt-3 text-[11px] text-[var(--faint)]">chance ≥ {thr}: n/a (no ensemble in this run)</div>}
              {p !== null && (
                <div className="mt-3">
                  <div className="flex justify-between text-[11px] text-[var(--muted)]">
                    <span>chance ≥ {thr}</span>
                    <span className="tabular font-medium text-[var(--text)]">{Math.round(p * 100)}%</span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[var(--chip)]">
                    <div className="h-full rounded-full bg-gradient-to-r from-violet-500 to-fuchsia-500" style={{ width: `${Math.max(2, Math.round(p * 100))}%` }} />
                  </div>
                </div>
              )}
              <div className="mt-3 flex flex-wrap gap-1">
                <Pill>{l.regime.replaceAll("_", " ")}</Pill>
                {l.defer && <Pill tone="warn">review</Pill>}
              </div>
            </button>
          );
        })}
      </div>

      {cur && (
        <Card tour="why" title={`Why day ${cur.lead_day} looks like this`} subtitle={fmtDate(cur.valid_day, { weekday: "long", day: "numeric", month: "long", year: "numeric" })}>
          <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
            <div className="space-y-3">
              <p className="text-[15px] leading-relaxed">{cur.sentence}</p>
              {cur.top_features.length > 0 && (
                <div>
                  <div className="mb-2 text-xs font-medium text-[var(--muted)]">Strongest drivers of the weighting (mean |SHAP|)</div>
                  <div className="space-y-1.5">
                    {cur.top_features.map(([n, v]) => {
                      const max = Math.max(...cur.top_features.map(([, x]) => Math.abs(x)), 1e-9);
                      return (
                        <div key={n} className="flex items-center gap-2 text-xs">
                          <span className="w-44 truncate text-[var(--muted)]">{n.replaceAll("_", " ")}</span>
                          <span className="h-1.5 flex-1 rounded-full bg-[var(--chip)]">
                            <span className="block h-full rounded-full bg-[var(--accent)]" style={{ width: `${(100 * Math.abs(v)) / max}%` }} />
                          </span>
                          <span className="tabular w-10 text-right">{v.toFixed(2)}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
            <div>
              <div className="mb-2 text-xs font-medium text-[var(--muted)]">Weight of each model</div>
              <div className="flex h-3 overflow-hidden rounded-full">
                {curWeights.map(([s, w]) => <span key={s} style={{ width: `${w * 100}%`, background: SOURCE_COLORS[s] ?? "#999" }} title={`${label(s)} ${Math.round(w * 100)}%`} />)}
              </div>
              <ul className="mt-3 space-y-1.5 text-sm">
                {curWeights.map(([s, w]) => (
                  <li key={s} className="flex items-center gap-2">
                    <span className="h-2.5 w-2.5 rounded-sm" style={{ background: SOURCE_COLORS[s] ?? "#999" }} />
                    <span className="flex-1 truncate">{label(s)}</span>
                    <span className="tabular font-medium">{Math.round(w * 100)}%</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Forecast by lead day" subtitle={`Blend with its calibrated 90 % range${variable === "precip" ? " and the chance of heavy rain" : ""}`}>
          <div className="h-72">
            <ResponsiveContainer>
              <ComposedChart data={rows} margin={{ left: -10, right: 4, top: 8 }}>
                <defs>
                  <linearGradient id="band" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#6366f1" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="#6366f1" stopOpacity={0.08} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="day" fontSize={12} tickLine={false} axisLine={false} />
                <YAxis yAxisId="v" fontSize={12} tickLine={false} axisLine={false} unit={unit === "°C" ? "°" : ""} />
                {variable === "precip" && <YAxis yAxisId="p" orientation="right" domain={[0, 100]} fontSize={12} tickLine={false} axisLine={false} unit="%" />}
                <Tooltip {...tooltipStyle} />
                <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
                {variable === "precip" && <Bar yAxisId="p" dataKey="prob" name={`chance ≥ ${thr} mm (%)`} fill="#a855f7" opacity={0.35} radius={[6, 6, 0, 0]} barSize={22} />}
                <Area yAxisId="v" dataKey="band" name="90 % range" fill="url(#band)" stroke="none" />
                <Line yAxisId="v" dataKey="value" name={`blend (${unit})`} stroke="#4f46e5" strokeWidth={2.5} dot={{ r: 4, fill: "#4f46e5" }} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card title="Who the blend trusts" subtitle="Weight of each model by lead day (%)">
          <div className="h-72">
            <ResponsiveContainer>
              <BarChart data={wrows} margin={{ left: -10, right: 4, top: 8 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="day" fontSize={12} tickLine={false} axisLine={false} />
                <YAxis domain={[0, 100]} fontSize={12} unit="%" tickLine={false} axisLine={false} />
                <Tooltip {...tooltipStyle} formatter={(v, n) => [`${v} %`, label(String(n))]} />
                <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} formatter={(n) => label(String(n))} />
                {sources.map((s, i) => (
                  <Bar key={s} dataKey={s} stackId="w" fill={SOURCE_COLORS[s] ?? "#999"} name={s} radius={i === sources.length - 1 ? [6, 6, 0, 0] : 0} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card
          tour="bulletin"
          title="Bulletin"
          subtitle="Generated from the numbers above; every number is checked"
          right={
            <div className="flex shrink-0 items-center gap-2">
              <Segmented size="sm" value={lang} onChange={setLang} options={[{ value: "en", label: "English" }, { value: "hi", label: "हिन्दी" }]} ariaLabel="Bulletin language" />
              <a className="inline-flex h-8 items-center gap-1 whitespace-nowrap rounded-lg border border-[var(--border)] px-2.5 text-xs font-medium hover:bg-[var(--chip)]" href={`${API_BASE}/v1/alerts/cap/${eid}?${q}`} target="_blank" rel="noreferrer">
                CAP XML <Icon name="external" className="h-3.5 w-3.5" />
              </a>
            </div>
          }
        >
          {b.loading && <Loading what="bulletin" rows={5} />}
          {b.error && <ErrorBox error={b.error} onRetry={b.reload} />}
          {b.data && (
            <>
              <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-4">
                <pre className="font-sans text-sm leading-relaxed whitespace-pre-wrap">{b.data.text}</pre>
              </div>
              <p className="mt-3 text-xs">
                {b.data.validated ? <Pill tone="ok" dot>every number checked against the forecast</Pill> : <Pill tone="bad" dot>number check failed: {b.data.validation_errors.join(", ")}</Pill>}
              </p>
            </>
          )}
        </Card>
        <Card
          tour="override"
          title="Forecaster override"
          subtitle="Your judgement feeds the skill tracker for this district"
          right={sandbox ? <Pill tone="accent" dot>Simulation</Pill> : undefined}
        >
          <OverrideForm districtId={id} variable={variable} days={dist.leads.map((l) => l.valid_day)} />
        </Card>
      </div>

      {prov && <p className="text-xs text-[var(--faint)]">Settings: {prov}</p>}
    </div>
  );
}

export default function DistrictPage() {
  return (
    <Suspense fallback={<Loading what="district" />}>
      <DistrictInner />
    </Suspense>
  );
}

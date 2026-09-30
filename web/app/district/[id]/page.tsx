"use client";

import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Area, Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, ErrorBox, Loading, Pill, fmt } from "@/components/ui";
import { API_BASE, DistrictPayload, Variable, apiPost, label, useApi } from "@/lib/api";
import { SOURCE_COLORS } from "@/lib/colors";

interface BulletinResp {
  text: string;
  validated: boolean;
  validation_errors: string[];
}

function OverrideForm({ districtId, variable, days }: { districtId: string; variable: Variable; days: string[] }) {
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
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
      setMsg(`Saved override #${r.id}: ${r.effect}`);
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const sources = ["ecmwf_ifs", "ecmwf_ifs_ctrl", "ecmwf_aifs", "ncep_gfs", "dwd_icon", "ncep_gefs", "ecmwf_ifs_ens", "ecmwf_aifs_ens"];
  return (
    <form onSubmit={submit} className="space-y-2 text-sm">
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--muted)]">Day</span>
          <select name="valid_day" className="rounded border border-[var(--border)] bg-[var(--surface)] px-2 py-1">{days.map((d) => <option key={d}>{d}</option>)}</select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--muted)]">Your value ({variable === "precip" ? "mm" : "°C"}, optional)</span>
          <input name="value" type="number" step="0.1" className="rounded border border-[var(--border)] bg-[var(--surface)] px-2 py-1" />
        </label>
      </div>
      <fieldset className="flex flex-wrap gap-x-3 gap-y-1">
        <legend className="text-xs text-[var(--muted)]">Models you distrust here (their weights drop for the next days)</legend>
        {sources.map((s) => (
          <label key={s} className="flex items-center gap-1 text-xs"><input type="checkbox" name="distrust" value={s} />{label(s)}</label>
        ))}
      </fieldset>
      <textarea name="reason" required minLength={5} placeholder="Reason (required)" className="h-16 w-full rounded border border-[var(--border)] bg-[var(--surface)] px-2 py-1" />
      <div className="flex items-center gap-2">
        <input name="author" required placeholder="Your name / ID" className="flex-1 rounded border border-[var(--border)] bg-[var(--surface)] px-2 py-1" />
        <button disabled={busy} className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">{busy ? "Saving…" : "Save override"}</button>
      </div>
      {msg && <p className="text-xs text-emerald-600 dark:text-emerald-400">{msg}</p>}
      {err && <ErrorBox error={err} />}
    </form>
  );
}

function DistrictInner() {
  const { id } = useParams<{ id: string }>();
  const sp = useSearchParams();
  const variable = (sp.get("variable") as Variable) ?? "precip";
  const init = sp.get("init");
  const [lang, setLang] = useState<"en" | "hi">("en");
  const q = `variable=${variable}${init ? `&init=${init}` : ""}`;
  const d = useApi<DistrictPayload>(`/v1/district/${id}?${q}`);
  const b = useApi<BulletinResp>(`/v1/bulletin/${id}?${q}&lang=${lang}`);

  if (d.loading) return <Loading what="district forecast" />;
  if (d.error) return <ErrorBox error={d.error} onRetry={d.reload} />;
  if (!d.data) return null;
  const dist = d.data.district;
  const unit = variable === "precip" ? "mm" : "°C";
  const thr = variable === "precip" ? "64.5" : "40.0";
  const rows = dist.leads.map((l) => ({
    day: `D${l.lead_day} ${l.valid_day.slice(5)}`,
    value: l.value,
    band: l.lo90 !== null && l.hi90 !== null ? [l.lo90, l.hi90] : null,
    prob: l.probabilities[thr] !== null && l.probabilities[thr] !== undefined ? Math.round(100 * (l.probabilities[thr] as number)) : null,
  }));
  const sources = Object.keys(dist.leads[0]?.weights ?? {});
  const wrows = dist.leads.map((l) => ({ day: `D${l.lead_day}`, ...Object.fromEntries(Object.entries(l.weights).map(([k, v]) => [k, Math.round(v * 1000) / 10])) }));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-2xl font-bold">{dist.district}</h1>
          <p className="text-sm text-[var(--muted)]">{dist.state} · {variable === "precip" ? "24 h rainfall (IMD day ending 08:30 IST)" : "daily maximum temperature"} · run {d.data.init_time.slice(0, 10)} 00 UTC</p>
        </div>
        <div className="flex gap-2">
          {dist.coverage < 0.5 && <Pill tone="warn">only {Math.round(dist.coverage * 100)} % of district inside pilot region</Pill>}
          {dist.leads.some((l) => l.defer) && <Pill tone="warn">low confidence on some days</Pill>}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Forecast by lead day">
          <div className="h-72">
            <ResponsiveContainer>
              <ComposedChart data={rows} margin={{ left: 0, right: 8, top: 8 }}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                <XAxis dataKey="day" fontSize={12} />
                <YAxis yAxisId="v" fontSize={12} unit={unit === "°C" ? "°" : ""} />
                {variable === "precip" && <YAxis yAxisId="p" orientation="right" domain={[0, 100]} fontSize={12} unit="%" />}
                <Tooltip />
                <Legend />
                <Area yAxisId="v" dataKey="band" name="90 % range" fill="#60a5fa" stroke="none" fillOpacity={0.25} />
                <Line yAxisId="v" dataKey="value" name={`blend (${unit})`} stroke="#2563eb" strokeWidth={2} dot />
                {variable === "precip" && <Bar yAxisId="p" dataKey="prob" name="P(≥ 64.5 mm) %" fill="#7c3aed" opacity={0.5} barSize={18} />}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card title="Who the blend trusts (weight %)">
          <div className="h-72">
            <ResponsiveContainer>
              <BarChart data={wrows} margin={{ left: 0, right: 8, top: 8 }}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                <XAxis dataKey="day" fontSize={12} />
                <YAxis domain={[0, 100]} fontSize={12} unit="%" />
                <Tooltip formatter={(v, n) => [`${v} %`, label(String(n))]} />
                {sources.map((s) => <Bar key={s} dataKey={s} stackId="w" fill={SOURCE_COLORS[s] ?? "#999"} name={s} />)}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <Card title="Explanation">
        <ul className="space-y-3">
          {dist.leads.map((l) => (
            <li key={l.lead_day} className="rounded-lg border border-[var(--border)] p-3">
              <div className="mb-1 flex flex-wrap items-center gap-2 text-sm">
                <b>Day {l.lead_day}</b><span className="text-[var(--muted)]">{l.valid_day}</span>
                <Pill>{l.regime.replaceAll("_", " ")}</Pill>
                {l.defer && <Pill tone="warn">forecaster review advised</Pill>}
                <span className="ml-auto font-mono">{fmt(l.value)} {unit}{l.lo90 !== null ? ` (${fmt(l.lo90)}–${fmt(l.hi90)})` : ""}</span>
              </div>
              <p className="text-sm">{l.sentence}</p>
              {l.top_features.length > 0 && (
                <p className="mt-1 text-xs text-[var(--muted)]">Top reasons: {l.top_features.map(([n, v]) => `${n} (${v.toFixed(2)})`).join(" · ")}</p>
              )}
            </li>
          ))}
        </ul>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Bulletin" right={
          <div className="flex gap-1 text-xs">
            {(["en", "hi"] as const).map((x) => (
              <button key={x} onClick={() => setLang(x)} className={`rounded px-2 py-0.5 ${lang === x ? "bg-[var(--chip)] font-medium" : ""}`}>{x === "en" ? "English" : "हिन्दी"}</button>
            ))}
            <a className="rounded border border-[var(--border)] px-2 py-0.5" href={`${API_BASE}/v1/alerts/cap/${id}?${q}`} target="_blank" rel="noreferrer">CAP XML</a>
          </div>
        }>
          {b.loading && <Loading what="bulletin" />}
          {b.error && <ErrorBox error={b.error} onRetry={b.reload} />}
          {b.data && (
            <>
              <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">{b.data.text}</pre>
              <p className="mt-2 text-xs">{b.data.validated ? <Pill tone="ok">every number checked against the forecast</Pill> : <Pill tone="bad">number check failed: {b.data.validation_errors.join(", ")}</Pill>}</p>
            </>
          )}
        </Card>
        <Card title="Forecaster override">
          <OverrideForm districtId={id} variable={variable} days={dist.leads.map((l) => l.valid_day)} />
        </Card>
      </div>
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

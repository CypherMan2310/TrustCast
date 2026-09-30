"use client";

import { Card, ErrorBox, Loading, Pill } from "@/components/ui";
import { SourceStatus, useApi } from "@/lib/api";

const TONE: Record<string, "ok" | "warn" | "bad" | "neutral"> = { ok: "ok", stale: "warn", failed: "bad", not_configured: "neutral", unknown: "neutral" };

export default function SourcesPage() {
  const s = useApi<{ sources: SourceStatus[] }>("/v1/sources");
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Sources</h1>
      <Card title="Forecast sources and their status">
        {s.loading && <Loading what="source status" />}
        {s.error && <ErrorBox error={s.error} onRetry={s.reload} />}
        {s.data && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-[var(--muted)]">
                <tr><th className="py-1">Source</th><th>Type</th><th>Status</th><th>Last archived run</th><th>Evaluation history</th><th>Adapters</th><th>Licence</th></tr>
              </thead>
              <tbody>
                {s.data.sources.map((x) => (
                  <tr key={x.source} className="border-t border-[var(--border)] align-top">
                    <td className="py-1.5 font-medium">{x.label}</td>
                    <td>{x.kind === "ai" ? "AI" : x.kind === "ens" ? "ensemble" : "NWP"}</td>
                    <td><Pill tone={TONE[x.status] ?? "neutral"}>{x.status.replace("_", " ")}</Pill>{x.detail && <div className="mt-0.5 max-w-xs text-xs text-[var(--muted)]">{x.detail}</div>}</td>
                    <td className="text-xs">{x.last_archived_init ?? "–"}</td>
                    <td className="text-xs">{x.eval_first_init ? `${x.eval_first_init} → ${x.eval_last_init}` : "–"}</td>
                    <td className="text-xs">{x.adapters.join(", ")}</td>
                    <td className="text-xs">{x.licence}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <p className="text-xs text-[var(--muted)]">
        Missing or stale sources are dropped from the blend and the remaining weights renormalised; nothing is substituted. NCMRWF NCUM/NEPS output is not public; the adapter slot exists and reports &quot;not configured&quot;.
      </p>
    </div>
  );
}

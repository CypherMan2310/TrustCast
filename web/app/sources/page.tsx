"use client";

import { Card, ErrorBox, Icon, PageHeader, Pill, Skeleton, Stat, fmtDate } from "@/components/ui";
import { SourceStatus, useApi } from "@/lib/api";
import { SOURCE_COLORS } from "@/lib/colors";

const TONE: Record<string, "ok" | "warn" | "bad" | "neutral"> = { ok: "ok", stale: "warn", failed: "bad", not_configured: "neutral", unknown: "neutral" };
const KIND: Record<string, { label: string; cls: string }> = {
  ai: { label: "AI model", cls: "bg-violet-100 text-violet-800 dark:bg-violet-500/15 dark:text-violet-300" },
  ens: { label: "Ensemble", cls: "bg-cyan-100 text-cyan-800 dark:bg-cyan-500/15 dark:text-cyan-300" },
  nwp: { label: "Physics (NWP)", cls: "bg-sky-100 text-sky-800 dark:bg-sky-500/15 dark:text-sky-300" },
};

export default function SourcesPage() {
  const s = useApi<{ sources: SourceStatus[] }>("/v1/sources");
  const list = s.data?.sources ?? [];
  const count = (st: string) => list.filter((x) => x.status === st).length;
  return (
    <div className="space-y-6">
      <PageHeader title="Sources" icon="server" subtitle="Every forecast source, its health and its licence. A missing source is dropped and the weights renormalised; nothing is ever filled in." />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {s.loading ? (
          Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-[104px] rounded-2xl" />)
        ) : (
          <>
            <Stat label="Sources" value={list.length} icon="server" hint="AI, physics and ensemble models" />
            <Stat label="Healthy" value={count("ok")} tone="ok" icon="check" hint="recent runs available" />
            <Stat label="Stale" value={count("stale")} tone={count("stale") ? "warn" : "neutral"} icon="clock" hint="provider stopped publishing" />
            <Stat label="Not configured" value={count("not_configured")} icon="info" hint="e.g. NCMRWF NCUM (not public)" />
          </>
        )}
      </div>

      {s.error && <ErrorBox error={s.error} onRetry={s.reload} />}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {s.loading && Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-48 rounded-2xl" />)}
        {list.map((x) => {
          const k = KIND[x.kind] ?? KIND.nwp;
          return (
            <Card key={x.source} className="flex flex-col">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <span className="h-9 w-1.5 rounded-full" style={{ background: SOURCE_COLORS[x.source] ?? "#94a3b8" }} />
                  <div>
                    <div className="font-semibold">{x.label}</div>
                    <span className={`mt-1 inline-block rounded-full px-2 py-0.5 text-[11px] font-medium ${k.cls}`}>{k.label}</span>
                  </div>
                </div>
                <Pill tone={TONE[x.status] ?? "neutral"} dot>
                  {x.status.replace("_", " ")}
                </Pill>
              </div>
              {x.detail && <p className="mt-3 text-xs leading-relaxed text-[var(--muted)]">{x.detail}</p>}
              <dl className="mt-4 grid grid-cols-2 gap-3 border-t border-[var(--border)] pt-3 text-xs">
                <div>
                  <dt className="text-[var(--faint)]">Last archived run</dt>
                  <dd className="mt-0.5 font-medium">{x.last_archived_init ? fmtDate(x.last_archived_init) : "–"}</dd>
                </div>
                <div>
                  <dt className="text-[var(--faint)]">Evaluation history</dt>
                  <dd className="mt-0.5 font-medium">{x.eval_first_init ? `${fmtDate(x.eval_first_init, { month: "short", year: "numeric" })} → ${fmtDate(x.eval_last_init, { month: "short", year: "numeric" })}` : "–"}</dd>
                </div>
              </dl>
              <div className="mt-auto flex flex-wrap items-center gap-1.5 pt-3 text-[11px] text-[var(--muted)]">
                <Icon name="doc" className="h-3.5 w-3.5" />
                {x.licence}
                {x.adapters.length > 0 && <span className="text-[var(--faint)]">· {x.adapters.join(", ")}</span>}
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

"use client";

/**
 * Training hub: mission list with progress, XP and badges, resume / restart, and the final recap once
 * every mission is complete. Opened from the sidebar "Training" button, the forecast page and the
 * first-visit offer, and after each mission.
 */

import { useEffect, useRef } from "react";
import { Icon } from "@/components/ui";
import { RECAP } from "./missions";
import { useTraining } from "./TrainingProvider";

export function TrainingHub() {
  const t = useTraining();
  const closeRef = useRef<HTMLButtonElement>(null);
  const pct = Math.round((100 * t.xp) / t.maxXp);
  const resumable = !t.running && t.mission;

  useEffect(() => {
    if (!t.hubOpen) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        t.closeHub();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [t.hubOpen, t]);

  if (!t.hubOpen) return null;
  return (
    <div className="fixed inset-0 z-[1100]" role="dialog" aria-modal aria-label="Forecaster training">
      <button aria-label="Close training" className="absolute inset-0 bg-slate-950/50 backdrop-blur-sm" onClick={t.closeHub} />
      <aside className="animate-rise absolute top-0 right-0 flex h-full w-full max-w-md flex-col overflow-y-auto border-l border-[var(--border)] bg-[var(--surface)] p-6 shadow-2xl">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-[11px] font-semibold tracking-wide text-[var(--accent)] uppercase">Guided tutorial</p>
            <h2 className="mt-1 text-xl font-semibold tracking-tight">Forecaster Training</h2>
          </div>
          <button ref={closeRef} onClick={t.closeHub} aria-label="Close" className="grid h-8 w-8 place-items-center rounded-lg hover:bg-[var(--chip)]">
            <Icon name="close" />
          </button>
        </div>
        <p className="mt-2 text-sm leading-relaxed text-[var(--muted)]">
          Six short missions on the real screens: read the blended forecast, open a district, see who to trust, replay a disaster, act as duty forecaster and check how every layer earned its place.
        </p>
        <span className="mt-3 inline-flex w-fit items-center gap-1.5 rounded-full bg-[var(--chip)] px-2.5 py-0.5 text-xs font-medium">
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--accent)]" /> Sandbox: nothing you do in training is saved
        </span>

        <div className="mt-5 rounded-2xl border border-[var(--border)] bg-[var(--surface-2)] p-4">
          <div className="flex items-baseline justify-between">
            <span className="tabular text-2xl font-semibold">
              {t.xp}
              <span className="ml-1 text-xs font-normal text-[var(--muted)]">/ {t.maxXp} XP</span>
            </span>
            <span className="text-xs text-[var(--muted)]">
              {t.completed.length}/{t.missions.length} missions
            </span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-[var(--chip)]" role="progressbar" aria-label="Training progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
            <div className="brand-gradient h-full rounded-full motion-safe:transition-all" style={{ width: `${pct}%` }} />
          </div>
        </div>

        {resumable && t.mission && (
          <button onClick={t.resume} className="brand-gradient mt-3 inline-flex h-10 items-center justify-center gap-2 rounded-xl px-4 text-sm font-semibold text-white shadow-md">
            <Icon name="replay" /> Resume: {t.mission.title} (step {t.step + 1})
          </button>
        )}

        {t.allDone && (
          <section className="mt-5 rounded-2xl border border-[var(--accent)]/40 bg-[var(--accent-soft)] p-4">
            <p className="text-[11px] font-semibold tracking-wide text-[var(--accent)] uppercase">All missions complete</p>
            <h3 className="mt-1 text-base font-semibold">You can run the forecast desk</h3>
            <ul className="mt-3 flex flex-wrap gap-1.5" aria-label="Badges earned">
              {t.missions.map((m) => (
                <li key={m.id} className="inline-flex items-center gap-1 rounded-full border border-[var(--accent)]/40 px-2 py-0.5 text-[11px] font-medium text-[var(--accent)]">
                  <Icon name="trust" className="h-3 w-3" /> {m.badge}
                </li>
              ))}
            </ul>
            <p className="mt-3 text-sm leading-relaxed text-[var(--muted)]">{RECAP}</p>
          </section>
        )}

        <ol className="mt-5 space-y-2">
          {t.missions.map((m, i) => {
            const done = t.completed.includes(m.id);
            return (
              <li key={m.id} className={`rounded-2xl border p-3 ${done ? "border-[var(--accent)]/30 bg-[var(--accent-soft)]/60" : "border-[var(--border)]"}`}>
                <div className="flex items-start gap-3">
                  <span
                    className={`mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full text-[11px] font-semibold ${done ? "brand-gradient text-white" : "bg-[var(--chip)] text-[var(--muted)]"}`}
                    aria-label={done ? "Complete" : "Not started"}
                  >
                    {done ? <Icon name="check" className="h-3.5 w-3.5" /> : i + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-[11px] font-medium tracking-wide text-[var(--muted)] uppercase">Badge · {m.badge}</p>
                    <p className="text-sm font-semibold">{m.title}</p>
                    <p className="mt-0.5 text-xs text-[var(--muted)]">{m.blurb}</p>
                  </div>
                  <button
                    onClick={() => t.start(m.id)}
                    aria-label={`${done ? "Replay" : "Start"} mission ${i + 1}: ${m.title}`}
                    className={`h-8 shrink-0 rounded-lg px-3 text-xs font-medium ${done ? "border border-[var(--border)] text-[var(--muted)] hover:text-[var(--text)]" : "bg-[var(--accent-soft)] text-[var(--accent)] hover:opacity-90"}`}
                  >
                    {done ? "Replay" : "Start"}
                  </button>
                </div>
              </li>
            );
          })}
        </ol>

        {(t.completed.length > 0 || t.mission) && (
          <button onClick={t.restart} className="mt-5 inline-flex w-fit items-center gap-1.5 text-xs font-medium text-[var(--muted)] hover:text-[var(--text)]">
            <Icon name="replay" className="h-3.5 w-3.5" /> Restart training
          </button>
        )}
      </aside>
    </div>
  );
}

"use client";

/**
 * Spotlight overlay + instruction bubble for a running mission.
 *
 * The page stays live: four dim panes surround the target (so only it can be clicked), a glowing
 * frame marks it, and a bubble carries the instruction with Back / Next / Skip. The target is
 * scrolled into view and focused once per step; Esc exits (handled by the provider). Motion is
 * CSS-only and switched off under prefers-reduced-motion.
 */

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import { Icon } from "@/components/ui";
import { MISSIONS } from "./missions";
import { useTraining } from "./TrainingProvider";

interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

const PAD = 8;

/** The visible element carrying `data-tour=id`. */
function findTarget(id: string): HTMLElement | null {
  const nodes = Array.from(document.querySelectorAll<HTMLElement>(`[data-tour="${id}"]`));
  return nodes.find((n) => n.getClientRects().length > 0 && getComputedStyle(n).visibility !== "hidden") ?? null;
}

const same = (a: Rect | null, b: Rect | null) =>
  !a || !b ? a === b : Math.abs(a.top - b.top) < 0.5 && Math.abs(a.left - b.left) < 0.5 && Math.abs(a.width - b.width) < 0.5 && Math.abs(a.height - b.height) < 0.5;

const subscribeNothing = () => () => {};

export function TrainingOverlay() {
  const t = useTraining();
  const mounted = useSyncExternalStore(subscribeNothing, () => true, () => false);
  const pathname = usePathname();
  const router = useRouter();
  const [tracked, setTracked] = useState<Rect | null>(null);
  const [vp, setVp] = useState({ w: 0, h: 0 });
  const focusedFor = useRef<string | null>(null);

  const mission = t.mission;
  const step = mission?.steps[t.step];
  const onRoute = mission && step ? (step.on ? step.on(pathname) : pathname === mission.route.split("?")[0]) : false;
  const active = t.running && Boolean(mission);
  const targetId = active && onRoute ? step?.target : undefined;
  const rect = targetId ? tracked : null;

  /* Track the target's rectangle every frame (it moves with scroll, data and layout). */
  useLayoutEffect(() => {
    if (!targetId) return;
    let frame = 0;
    let last: Rect | null = null;
    const tick = () => {
      const r = findTarget(targetId)?.getBoundingClientRect();
      const nr = r && r.width > 0 && r.height > 0 ? { top: r.top, left: r.left, width: r.width, height: r.height } : null;
      if (!same(last, nr)) {
        last = nr;
        setTracked(nr);
      }
      setVp((v) => (v.w === window.innerWidth && v.h === window.innerHeight ? v : { w: window.innerWidth, h: window.innerHeight }));
      frame = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(frame);
  }, [targetId]);

  /* Keep the viewport size for centred steps too. */
  useEffect(() => {
    const on = () => setVp({ w: window.innerWidth, h: window.innerHeight });
    on();
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);

  /* Bring the target into view and move focus to it once per step. */
  useEffect(() => {
    if (!targetId || !mission) return;
    const key = `${mission.id}:${t.step}`;
    if (focusedFor.current === key) return;
    let tries = 0;
    const id = window.setInterval(() => {
      const el = findTarget(targetId);
      tries += 1;
      if (!el && tries < 40) return;
      window.clearInterval(id);
      focusedFor.current = key;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      const behavior = reduce ? "auto" : "smooth";
      if (r.height > window.innerHeight * 0.45) window.scrollTo({ top: window.scrollY + r.top - 80, behavior });
      else el.scrollIntoView({ block: "center", behavior });
      if (!el.matches("a,button,input,select,textarea,[tabindex]")) el.setAttribute("tabindex", "-1");
      el.focus({ preventScroll: true });
    }, 150);
    return () => window.clearInterval(id);
  }, [targetId, mission, t.step]);

  if (!mounted) return null;
  const showDone = !t.running && t.justCompleted;
  if (!active && !showDone) return null;

  const mIndex = mission ? MISSIONS.findIndex((m) => m.id === mission.id) : -1;
  const total = mission?.steps.length ?? 0;

  /* Bubble placement: phones dock it to the top or bottom edge, wider screens float it by the target. */
  const narrow = vp.w > 0 && vp.w < 640;
  const bw = Math.min(380, Math.max(260, vp.w - 24));
  let style: React.CSSProperties;
  if (!rect) style = { left: "50%", top: "50%", transform: "translate(-50%, -50%)", width: bw };
  else if (narrow) style = rect.top + rect.height / 2 > vp.h / 2 ? { left: 12, right: 12, top: 12 } : { left: 12, right: 12, bottom: 12 };
  else {
    const below = vp.h - (rect.top + rect.height);
    const left = Math.max(12, Math.min(rect.left, vp.w - bw - 12));
    if (below > 250) style = { left, top: rect.top + rect.height + PAD + 10, width: bw };
    else if (rect.top > 250) style = { left, top: rect.top - PAD - 10, transform: "translateY(-100%)", width: bw };
    else style = { right: 16, bottom: 16, width: bw };
  }

  return createPortal(
    <div className="pointer-events-none fixed inset-0 z-[1200]" aria-live="polite">
      {active && onRoute && <DimPanes rect={rect} vp={vp} />}
      {active && !onRoute && <div className="pointer-events-auto absolute inset-0 bg-slate-950/60 backdrop-blur-[1px]" />}
      {showDone && <div className="pointer-events-auto absolute inset-0 bg-slate-950/65 backdrop-blur-[2px]" />}

      {rect && active && onRoute && (
        <div
          aria-hidden
          className="absolute rounded-2xl border-2 border-[var(--accent)]"
          style={{
            top: rect.top - PAD,
            left: rect.left - PAD,
            width: rect.width + PAD * 2,
            height: rect.height + PAD * 2,
            boxShadow: "0 0 0 4px var(--ring), 0 0 32px -2px var(--accent)",
          }}
        />
      )}

      <div className="pointer-events-none absolute" style={showDone ? { left: "50%", top: "50%", transform: "translate(-50%, -50%)", width: bw } : style}>
        <div
          key={showDone ? `done-${t.justCompleted?.id}` : `${mission?.id}-${t.step}-${onRoute}`}
          role="dialog"
          aria-modal="false"
          aria-label={showDone ? "Mission complete" : `Forecaster training: ${step?.title ?? ""}`}
          className="animate-rise pointer-events-auto max-h-[46vh] overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-2xl sm:max-h-[70vh]"
        >
          {showDone && t.justCompleted ? (
            <Done title={t.justCompleted.title} badge={t.justCompleted.badge} allDone={t.allDone} onContinue={t.dismissCompleted} />
          ) : (
            mission &&
            step && (
              <>
                <div className="flex items-center justify-between gap-2 text-[11px] font-semibold tracking-wide text-[var(--accent)] uppercase">
                  <span className="truncate">
                    Mission {mIndex + 1}/{MISSIONS.length} · {mission.title}
                  </span>
                  <span className="tabular text-[var(--muted)]">
                    {t.step + 1}/{total}
                  </span>
                </div>
                <div className="mt-2 flex gap-1" aria-hidden>
                  {mission.steps.map((s, i) => (
                    <span key={s.id} className={`h-1 flex-1 rounded-full ${i <= t.step ? "brand-gradient" : "bg-[var(--chip)]"}`} />
                  ))}
                </div>
                <h2 className="mt-3 text-base font-semibold tracking-tight">{step.title}</h2>
                {onRoute ? (
                  <p className="mt-1 text-sm leading-relaxed text-[var(--muted)]">{step.body}</p>
                ) : (
                  <div className="mt-1.5">
                    <p className="text-sm text-[var(--muted)]">This step happens on another screen.</p>
                    <button
                      type="button"
                      onClick={() => router.push(mission.route)}
                      className="mt-2 inline-flex items-center gap-1.5 rounded-xl bg-[var(--accent-soft)] px-3 py-1.5 text-sm font-medium text-[var(--accent)]"
                    >
                      <Icon name="map" /> Take me there
                    </button>
                  </div>
                )}
                {t.hint && (
                  <p className="mt-2 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:bg-amber-500/10 dark:text-amber-200">{t.hint}</p>
                )}
                {step.onEvent && t.satisfied && (
                  <p className="mt-2 flex items-center gap-1.5 text-xs font-medium text-[var(--ok)]">
                    <Icon name="check" className="h-4 w-4" /> Nice, that&apos;s it.
                  </p>
                )}
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={t.back}
                    disabled={t.step === 0}
                    className="inline-flex h-8 items-center gap-1 rounded-lg border border-[var(--border)] px-2.5 text-xs font-medium text-[var(--muted)] hover:text-[var(--text)] disabled:opacity-35"
                  >
                    <Icon name="arrowLeft" className="h-3.5 w-3.5" /> Back
                  </button>
                  <button
                    type="button"
                    onClick={t.next}
                    className="brand-gradient inline-flex h-8 items-center gap-1 rounded-lg px-3 text-xs font-semibold text-white shadow"
                  >
                    {t.step + 1 >= total ? "Finish" : step.onEvent && !t.satisfied ? "Skip step" : "Next"}
                  </button>
                  <button type="button" onClick={t.skip} className="ml-auto h-8 rounded-lg px-2 text-xs text-[var(--muted)] hover:text-[var(--text)]">
                    Skip mission
                  </button>
                </div>
                {step.onEvent && !t.satisfied && <p className="mt-2 text-[11px] text-[var(--faint)]">Waiting for you to do it on the page…</p>}
                <div className="mt-3 flex items-center justify-between gap-2 border-t border-[var(--border)] pt-2 text-[11px] text-[var(--muted)]">
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-[var(--chip)] px-2 py-0.5 font-medium">
                    <span className="h-1.5 w-1.5 rounded-full bg-[var(--accent)]" /> Training · sandbox
                  </span>
                  <span className="hidden lg:inline">Esc to pause</span>
                  <button type="button" onClick={t.exit} className="font-medium hover:text-[var(--text)]">
                    Pause
                  </button>
                </div>
              </>
            )
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

function DimPanes({ rect, vp }: { rect: Rect | null; vp: { w: number; h: number } }) {
  const dim = "pointer-events-auto absolute bg-slate-950/60";
  if (!rect) return <div className={`${dim} inset-0`} />;
  const top = Math.max(0, rect.top - PAD);
  const left = Math.max(0, rect.left - PAD);
  const right = Math.min(vp.w, rect.left + rect.width + PAD);
  const bottom = Math.min(vp.h, rect.top + rect.height + PAD);
  return (
    <>
      <div className={dim} style={{ left: 0, top: 0, width: "100%", height: top }} />
      <div className={dim} style={{ left: 0, top: bottom, width: "100%", bottom: 0 }} />
      <div className={dim} style={{ left: 0, top, width: left, height: bottom - top }} />
      <div className={dim} style={{ left: right, top, right: 0, height: bottom - top }} />
    </>
  );
}

function Done({ title, badge, allDone, onContinue }: { title: string; badge: string; allDone: boolean; onContinue: () => void }) {
  const ref = useRef<HTMLButtonElement>(null);
  useEffect(() => ref.current?.focus(), []);
  return (
    <div className="py-2 text-center">
      <span className="brand-gradient mx-auto grid h-14 w-14 place-items-center rounded-full text-white shadow-lg">
        <Icon name="trust" className="h-7 w-7" />
      </span>
      <p className="mt-3 text-[11px] font-semibold tracking-wide text-[var(--accent)] uppercase">Mission complete · +100 XP</p>
      <h2 className="mt-1 text-lg font-semibold">{title}</h2>
      <p className="mt-1 text-sm text-[var(--muted)]">
        Badge earned: <span className="font-semibold text-[var(--accent)]">{badge}</span>
      </p>
      <button ref={ref} type="button" onClick={onContinue} className="brand-gradient mt-4 inline-flex h-9 items-center gap-1 rounded-xl px-4 text-sm font-semibold text-white shadow">
        {allDone ? "See your results" : "Next mission"}
      </button>
    </div>
  );
}

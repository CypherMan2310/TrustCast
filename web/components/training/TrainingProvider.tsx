"use client";

/**
 * Forecaster Training: state, persistence, sandbox switch and the event bus pages report into.
 *
 * - Optional, skippable, resumable. Progress lives in localStorage (`trustcast.training.v1`); every
 *   access is try/catch-guarded, so without storage training still works, it just does not resume.
 * - While a mission runs, `setSandboxMode(true)` makes lib/api.ts simulate writes: a training
 *   override is never stored and never changes any weights.
 * - Pages report what the user did (`useTrainingReporter`); the provider decides, using the rules in
 *   missions.ts, whether that completes the current step.
 */

import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { setSandboxMode } from "@/lib/api";
import { MISSIONS, XP_PER_MISSION, type Mission, type TrainingEvent } from "./missions";
import { TrainingHub } from "./TrainingHub";
import { TrainingOffer } from "./TrainingOffer";
import { TrainingOverlay } from "./TrainingOverlay";

const STORAGE_KEY = "trustcast.training.v1";
const OFFERED_KEY = "trustcast.training.offered";

export const storage = {
  get(k: string): string | null {
    try {
      return window.localStorage.getItem(k);
    } catch {
      return null;
    }
  },
  set(k: string, v: string) {
    try {
      window.localStorage.setItem(k, v);
    } catch {
      /* private mode: training still works, it just does not resume */
    }
  },
};

interface Persisted {
  version: 1;
  completed: string[];
  active: { missionId: string; step: number } | null;
  running: boolean;
}

const EMPTY: Persisted = { version: 1, completed: [], active: null, running: false };

function load(): Persisted {
  const raw = storage.get(STORAGE_KEY);
  if (!raw) return EMPTY;
  try {
    const p = JSON.parse(raw) as Partial<Persisted>;
    if (p.version !== 1) return EMPTY;
    const known = new Set(MISSIONS.map((m) => m.id));
    const active = p.active && known.has(p.active.missionId) ? { missionId: p.active.missionId, step: Math.max(0, p.active.step ?? 0) } : null;
    return { version: 1, completed: (p.completed ?? []).filter((id) => known.has(id)), active, running: Boolean(p.running && active) };
  } catch {
    return EMPTY;
  }
}

export interface TrainingApi {
  missions: Mission[];
  completed: string[];
  xp: number;
  maxXp: number;
  running: boolean;
  mission: Mission | null;
  step: number;
  satisfied: boolean;
  hint: string | null;
  justCompleted: Mission | null;
  hubOpen: boolean;
  allDone: boolean;
  openHub: () => void;
  closeHub: () => void;
  start: (missionId: string) => void;
  resume: () => void;
  next: () => void;
  back: () => void;
  skip: () => void;
  exit: () => void;
  restart: () => void;
  dismissCompleted: () => void;
  report: (e: TrainingEvent) => void;
}

const Ctx = createContext<TrainingApi | null>(null);

export function useTraining(): TrainingApi {
  const c = useContext(Ctx);
  if (!c) throw new Error("useTraining must be used inside <TrainingProvider>");
  return c;
}

/** For pages: report what the user did. A no-op whenever no mission is running. */
export function useTrainingReporter(): (e: TrainingEvent) => void {
  return useContext(Ctx)?.report ?? noop;
}
const noop = () => {};

/** For pages: whether a training mission is running (sandbox on). */
export function useTrainingRunning(): boolean {
  return useContext(Ctx)?.running ?? false;
}

export function TrainingProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [state, setState] = useState<Persisted>(EMPTY);
  const [hydrated, setHydrated] = useState(false);
  const [hubOpen, setHubOpen] = useState(false);
  const [satisfied, setSatisfied] = useState(false);
  const [hint, setHint] = useState<string | null>(null);
  const [justCompleted, setJustCompleted] = useState<Mission | null>(null);
  const [showOffer, setShowOffer] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  /* Read storage after mount so server and client markup agree. */
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time read of browser-only storage
    setState(load());
    setHydrated(true);
    if (!storage.get(OFFERED_KEY)) {
      const t = window.setTimeout(() => setShowOffer(true), 1800);
      return () => window.clearTimeout(t);
    }
  }, []);

  useEffect(() => {
    if (hydrated) storage.set(STORAGE_KEY, JSON.stringify(state));
  }, [state, hydrated]);

  /* The sandbox is on exactly while a mission is running. */
  useEffect(() => {
    setSandboxMode(state.running);
    return () => setSandboxMode(false);
  }, [state.running]);

  const mission = useMemo(() => (state.active ? (MISSIONS.find((m) => m.id === state.active!.missionId) ?? null) : null), [state.active]);
  const step = state.active?.step ?? 0;
  const logic = mission?.steps[step];

  const resetStep = useCallback(() => {
    window.clearTimeout(timer.current);
    setSatisfied(false);
    setHint(null);
  }, []);

  const goTo = useCallback(
    (missionId: string, s: number) => {
      resetStep();
      setState((p) => ({ ...p, active: { missionId, step: s }, running: true }));
    },
    [resetStep],
  );

  const onStepRoute = useCallback((m: Mission, s: number, path: string) => {
    const st = m.steps[s];
    const base = m.route.split("?")[0];
    return st?.on ? st.on(path) : path === base;
  }, []);

  const start = useCallback(
    (missionId: string) => {
      const m = MISSIONS.find((x) => x.id === missionId);
      if (!m) return;
      setHubOpen(false);
      setShowOffer(false);
      storage.set(OFFERED_KEY, "1");
      setJustCompleted(null);
      goTo(missionId, 0);
      if (!onStepRoute(m, 0, pathname)) router.push(m.route);
    },
    [goTo, onStepRoute, pathname, router],
  );

  const resume = useCallback(() => {
    if (!state.active) return;
    const m = MISSIONS.find((x) => x.id === state.active!.missionId);
    setHubOpen(false);
    resetStep();
    setState((p) => ({ ...p, running: true }));
    if (m && !onStepRoute(m, state.active.step, pathname)) router.push(m.route);
  }, [state.active, onStepRoute, pathname, router, resetStep]);

  const complete = useCallback(() => {
    if (!mission) return;
    resetStep();
    setJustCompleted(mission);
    setState((p) => ({ ...p, completed: p.completed.includes(mission.id) ? p.completed : [...p.completed, mission.id], active: null, running: false }));
  }, [mission, resetStep]);

  const next = useCallback(() => {
    if (!mission) return;
    if (step + 1 >= mission.steps.length) complete();
    else goTo(mission.id, step + 1);
  }, [mission, step, goTo, complete]);

  const back = useCallback(() => {
    if (mission && step > 0) goTo(mission.id, step - 1);
  }, [mission, step, goTo]);

  const exit = useCallback(() => {
    resetStep();
    setState((p) => ({ ...p, running: false }));
  }, [resetStep]);

  const skip = useCallback(() => {
    resetStep();
    setState((p) => ({ ...p, active: null, running: false }));
    setHubOpen(true);
  }, [resetStep]);

  const restart = useCallback(() => {
    resetStep();
    setJustCompleted(null);
    setState(EMPTY);
  }, [resetStep]);

  /* Event bus: does what the user just did complete the current step? */
  const report = useCallback(
    (e: TrainingEvent) => {
      if (!state.running || !logic?.onEvent) return;
      const v = logic.onEvent(e);
      if (v === "done") {
        setHint(null);
        setSatisfied(true);
        // a short beat so the success state registers before the next instruction; an action that
        // navigates (opening a district) advances at once so the old step never shows off-screen
        window.clearTimeout(timer.current);
        timer.current = window.setTimeout(() => next(), e.type === "district-opened" ? 0 : 900);
      } else if (v && typeof v === "object") setHint(v.hint);
    },
    [state.running, logic, next],
  );
  useEffect(() => () => window.clearTimeout(timer.current), []);

  // stable function for pages, so a provider re-render never re-triggers their effects
  const reportRef = useRef(report);
  useEffect(() => {
    reportRef.current = report;
  }, [report]);
  const stableReport = useCallback((e: TrainingEvent) => reportRef.current(e), []);

  /* Esc exits a running mission from anywhere (progress kept). */
  useEffect(() => {
    if (!state.running) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !e.defaultPrevented) exit();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [state.running, exit]);

  const api: TrainingApi = {
    missions: MISSIONS,
    completed: state.completed,
    xp: state.completed.length * XP_PER_MISSION,
    maxXp: MISSIONS.length * XP_PER_MISSION,
    running: state.running,
    mission,
    step,
    satisfied: satisfied || !logic?.onEvent,
    hint,
    justCompleted,
    hubOpen,
    allDone: MISSIONS.every((m) => state.completed.includes(m.id)),
    openHub: () => {
      setShowOffer(false);
      storage.set(OFFERED_KEY, "1");
      setHubOpen(true);
    },
    closeHub: () => setHubOpen(false),
    start,
    resume,
    next,
    back,
    skip,
    exit,
    restart,
    dismissCompleted: () => {
      setJustCompleted(null);
      setHubOpen(true);
    },
    report: stableReport,
  };

  return (
    <Ctx.Provider value={api}>
      {children}
      <TrainingOverlay />
      <TrainingHub />
      {showOffer && !state.running && !hubOpen && (
        <TrainingOffer
          onStart={() => start(MISSIONS[0].id)}
          onDismiss={() => {
            setShowOffer(false);
            storage.set(OFFERED_KEY, "1");
          }}
        />
      )}
    </Ctx.Provider>
  );
}

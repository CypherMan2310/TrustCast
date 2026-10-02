"use client";

/** First-visit offer: a small, non-blocking card. Offered once, never forced. */

import { Icon } from "@/components/ui";

export function TrainingOffer({ onStart, onDismiss }: { onStart: () => void; onDismiss: () => void }) {
  return (
    <aside
      aria-label="Take the forecaster training"
      className="animate-rise fixed right-3 bottom-3 left-3 z-[1050] rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-2xl sm:right-5 sm:bottom-5 sm:left-auto sm:w-[340px]"
    >
      <div className="flex items-start gap-3">
        <span className="brand-gradient grid h-9 w-9 shrink-0 place-items-center rounded-xl text-white shadow">
          <Icon name="spark" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold">New here? Take the 5-minute training</p>
          <p className="mt-1 text-xs leading-relaxed text-[var(--muted)]">Six guided missions on the real screens, with badges. A sandbox: nothing you do is saved.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button onClick={onStart} className="brand-gradient h-8 rounded-lg px-3 text-xs font-semibold text-white shadow">
              Start training
            </button>
            <button onClick={onDismiss} className="h-8 rounded-lg border border-[var(--border)] px-3 text-xs font-medium text-[var(--muted)] hover:text-[var(--text)]">
              Maybe later
            </button>
          </div>
        </div>
        <button onClick={onDismiss} aria-label="Dismiss training offer" className="-mt-1 -mr-1 grid h-7 w-7 place-items-center rounded-lg text-[var(--muted)] hover:bg-[var(--chip)]">
          <Icon name="close" className="h-3.5 w-3.5" />
        </button>
      </div>
    </aside>
  );
}

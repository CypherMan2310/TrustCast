"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useSyncExternalStore } from "react";
import { Disclaimer, Icon, fmtDate } from "@/components/ui";
import { useApi } from "@/lib/api";

const NAV = [
  { href: "/", label: "Forecast", icon: "map", hint: "Blended forecast map and district alerts" },
  { href: "/skill", label: "Who to trust", icon: "trust", hint: "Recent skill per model and cell" },
  { href: "/replay", label: "Event replay", icon: "replay", hint: "What each model said before real events" },
  { href: "/verification", label: "Verification", icon: "chart", hint: "Layer gates and scores with 95 % intervals" },
  { href: "/sources", label: "Sources", icon: "server", hint: "Data sources and their health" },
];

function subscribeTheme(cb: () => void) {
  window.addEventListener("themechange", cb);
  return () => window.removeEventListener("themechange", cb);
}

function ThemeToggle({ full = false }: { full?: boolean }) {
  // the theme lives on <html data-theme>, set before hydration by the inline script in layout.tsx
  const theme = useSyncExternalStore(subscribeTheme, () => document.documentElement.dataset.theme ?? "light", () => "light");
  const toggle = () => {
    const t = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = t;
    try {
      localStorage.setItem("theme", t);
    } catch {
      /* private mode */
    }
    window.dispatchEvent(new CustomEvent("themechange", { detail: t }));
  };
  return (
    <button
      onClick={toggle}
      aria-label="Toggle dark mode"
      className={`inline-flex items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--surface)] text-sm text-[var(--muted)] transition hover:text-[var(--text)] ${full ? "w-full px-3 py-2" : "h-9 w-9 justify-center"}`}
    >
      <Icon name={theme === "dark" ? "sun" : "moon"} />
      {full && (theme === "dark" ? "Light mode" : "Dark mode")}
    </button>
  );
}

function isActive(path: string, href: string) {
  return href === "/" ? path === "/" || path.startsWith("/district") : path.startsWith(href);
}

function Status() {
  const h = useApi<{ status: string; products: Record<string, string | null> }>("/v1/health");
  const ok = h.data?.status === "ok";
  const latest = h.data ? Object.values(h.data.products).filter(Boolean).sort().at(-1) : null;
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-3 text-xs">
      <div className="flex items-center gap-2 font-medium">
        <span className="relative flex h-2 w-2">
          {ok && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />}
          <span className={`relative inline-flex h-2 w-2 rounded-full ${h.error ? "bg-rose-500" : ok ? "bg-emerald-500" : "bg-amber-500"}`} />
        </span>
        {h.error ? "API unreachable" : h.loading ? "Connecting…" : ok ? "System online" : `Status: ${h.data?.status}`}
      </div>
      {latest && <div className="mt-1 text-[var(--muted)]">Newest run {fmtDate(latest)} 00 UTC</div>}
    </div>
  );
}

function Brand() {
  return (
    <Link href="/" className="flex items-center gap-2.5">
      <span className="brand-gradient grid h-9 w-9 place-items-center rounded-xl text-white shadow-md">
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" aria-hidden>
          <path d="M4 15a4 4 0 0 1 3.5-4A5.5 5.5 0 0 1 18 9.5 3.5 3.5 0 0 1 18 16.5H7" />
          <path d="M8 20h8" />
        </svg>
      </span>
      <span className="leading-tight">
        <span className="block text-[15px] font-bold tracking-tight">TRUSTCAST</span>
        <span className="block text-[11px] text-[var(--muted)]">AI + NWP forecast blending</span>
      </span>
    </Link>
  );
}

function NavLinks({ path, onNavigate }: { path: string; onNavigate?: () => void }) {
  return (
    <nav className="space-y-1">
      {NAV.map((n) => {
        const on = isActive(path, n.href);
        return (
          <Link
            key={n.href}
            href={n.href}
            title={n.hint}
            onClick={onNavigate}
            className={`group flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition ${
              on ? "bg-[var(--accent-soft)] text-[var(--accent)]" : "text-[var(--muted)] hover:bg-[var(--chip)] hover:text-[var(--text)]"
            }`}
          >
            <Icon name={n.icon} className="h-[18px] w-[18px]" />
            {n.label}
            {on && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-[var(--accent)]" />}
          </Link>
        );
      })}
    </nav>
  );
}

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[248px_1fr]">
      {/* desktop sidebar */}
      <aside className="sticky top-0 hidden h-screen flex-col gap-6 border-r border-[var(--border)] bg-[var(--surface)] px-4 py-5 lg:flex">
        <Brand />
        <NavLinks path={path} />
        <div className="mt-auto space-y-3">
          <Status />
          <ThemeToggle full />
          <p className="px-1 text-[11px] leading-relaxed text-[var(--faint)]">SIH26081 · NCMRWF, MoES · prototype</p>
        </div>
      </aside>

      {/* mobile top bar + drawer */}
      <header className="sticky top-0 z-40 flex items-center justify-between gap-3 border-b border-[var(--border)] bg-[var(--surface)]/90 px-4 py-3 backdrop-blur lg:hidden">
        <Brand />
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <button
            onClick={() => setOpen(true)}
            aria-label="Open menu"
            aria-expanded={open}
            className="grid h-9 w-9 place-items-center rounded-xl border border-[var(--border)] bg-[var(--surface)]"
          >
            <Icon name="menu" />
          </button>
        </div>
      </header>
      {open && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal>
          <button aria-label="Close menu" className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setOpen(false)} />
          <div className="animate-rise absolute top-0 right-0 flex h-full w-72 flex-col gap-6 border-l border-[var(--border)] bg-[var(--surface)] p-5 shadow-2xl">
            <div className="flex items-center justify-between">
              <Brand />
              <button onClick={() => setOpen(false)} aria-label="Close menu" className="grid h-8 w-8 place-items-center rounded-lg hover:bg-[var(--chip)]">
                <Icon name="close" />
              </button>
            </div>
            <NavLinks path={path} onNavigate={() => setOpen(false)} />
            <div className="mt-auto">
              <Status />
            </div>
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-col">
        <div className="mx-auto w-full max-w-[1400px] px-4 pt-4 sm:px-6 lg:px-8 lg:pt-6">
          <Disclaimer />
        </div>
        <main key={path} className="animate-rise mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 sm:px-6 lg:px-8">
          {children}
        </main>
        <footer className="mx-auto w-full max-w-[1400px] px-4 pb-6 text-xs leading-relaxed text-[var(--faint)] sm:px-6 lg:px-8">
          <div className="border-t border-[var(--border)] pt-4">
            Decision-support tool. Not an official warning. · Forecasts: dynamical.org (CC BY 4.0) with ECMWF and NOAA data; Open-Meteo (CC BY 4.0);
            ECMWF open data. Observations: India Meteorological Department; NASA GPM IMERG. Boundaries: geoBoundaries (ODbL), DataMeet (CC BY 2.5 IN).
            Basemap: OpenFreeMap, © OpenMapTiles, data © OpenStreetMap contributors.
          </div>
        </footer>
      </div>
    </div>
  );
}

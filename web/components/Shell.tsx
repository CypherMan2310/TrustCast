"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Disclaimer } from "@/components/ui";

const NAV = [
  { href: "/", label: "Forecast map" },
  { href: "/skill", label: "Who to trust" },
  { href: "/replay", label: "Replay" },
  { href: "/verification", label: "Verification" },
  { href: "/sources", label: "Sources" },
];

function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark" | null>(null);
  useEffect(() => {
    const saved = (typeof localStorage !== "undefined" && localStorage.getItem("theme")) as "light" | "dark" | null;
    const t = saved ?? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    setTheme(t);
    document.documentElement.dataset.theme = t;
  }, []);
  const toggle = () => {
    const t = theme === "dark" ? "light" : "dark";
    setTheme(t);
    document.documentElement.dataset.theme = t;
    try {
      localStorage.setItem("theme", t);
    } catch {
      /* private mode */
    }
    window.dispatchEvent(new CustomEvent("themechange", { detail: t }));
  };
  return (
    <button onClick={toggle} aria-label="Toggle dark mode" className="rounded-md border border-[var(--border)] px-2 py-1 text-xs">
      {theme === "dark" ? "☀ Light" : "☾ Dark"}
    </button>
  );
}

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 border-b border-[var(--border)] bg-[var(--surface)]/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-2">
          <Link href="/" className="flex items-baseline gap-2">
            <span className="text-lg font-bold tracking-tight">TRUSTCAST</span>
            <span className="hidden text-xs text-[var(--muted)] sm:inline">multi-model forecast blending · SIH26081</span>
          </Link>
          <nav className="ml-auto hidden gap-1 md:flex">
            {NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                className={`rounded-md px-3 py-1.5 text-sm ${path === n.href ? "bg-[var(--chip)] font-medium" : "text-[var(--muted)] hover:bg-[var(--chip)]"}`}
              >
                {n.label}
              </Link>
            ))}
          </nav>
          <ThemeToggle />
          <button className="rounded-md border border-[var(--border)] px-2 py-1 text-xs md:hidden" onClick={() => setOpen(!open)} aria-expanded={open}>
            Menu
          </button>
        </div>
        {open && (
          <nav className="flex flex-col border-t border-[var(--border)] px-4 py-2 md:hidden">
            {NAV.map((n) => (
              <Link key={n.href} href={n.href} onClick={() => setOpen(false)} className="py-1.5 text-sm">
                {n.label}
              </Link>
            ))}
          </nav>
        )}
        <div className="mx-auto max-w-7xl px-4 pb-2">
          <Disclaimer />
        </div>
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-4">{children}</main>
      <footer className="border-t border-[var(--border)] px-4 py-3 text-center text-xs text-[var(--muted)]">
        Decision-support tool. Not an official warning. · Forecasts: Open-Meteo (CC BY 4.0) with ECMWF, NOAA, DWD, ECCC data;
        dynamical.org (CC BY 4.0); ECMWF open data. Observations: India Meteorological Department; NASA GPM IMERG. Boundaries:
        geoBoundaries (ODbL), DataMeet (CC BY 2.5 IN). Basemap © OpenStreetMap contributors © CARTO.
      </footer>
    </div>
  );
}

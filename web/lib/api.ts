"use client";

import { useCallback, useEffect, useState } from "react";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const DISCLAIMER = "Decision-support tool. Not an official warning.";

export type Variable = "precip" | "tmax";
export type Region = "rain_pilot" | "heat_pilot";

export const REGIONS: { id: Region; label: string; variable: Variable }[] = [
  { id: "rain_pilot", label: "Kerala + coastal Karnataka (rain)", variable: "precip" },
  { id: "heat_pilot", label: "Vidarbha (heat)", variable: "tmax" },
];

export const SOURCE_LABELS: Record<string, string> = {
  ecmwf_ifs: "ECMWF IFS (HRES)",
  ecmwf_ifs_ctrl: "ECMWF IFS control",
  ecmwf_aifs: "ECMWF AIFS (AI)",
  ncep_gfs: "NOAA GFS",
  dwd_icon: "DWD ICON",
  cmc_gem: "ECCC GEM",
  ncep_gefs: "NOAA GEFS (ens)",
  ecmwf_ifs_ens: "ECMWF IFS ENS",
  ecmwf_aifs_ens: "ECMWF AIFS ENS (AI)",
  equal_mean: "Equal-weight mean",
  superensemble: "Superensemble",
  persistence: "Persistence",
  climatology: "Climatology",
  trustcast: "TRUSTCAST blend",
};

export const label = (s: string) => SOURCE_LABELS[s] ?? s;

export interface GridLayer {
  disclaimer: string;
  region: string;
  variable: Variable;
  layer: string;
  units: string;
  init_time: string;
  lead_day: number;
  valid_day: string;
  lats: number[];
  lons: number[];
  values: (number | null)[][];
  vmin: number | null;
  vmax: number | null;
  available_layers: string[];
}

export interface LeadPayload {
  lead_day: number;
  valid_day: string;
  value: number | null;
  lo90: number | null;
  hi90: number | null;
  probabilities: Record<string, number | null>;
  weights: Record<string, number>;
  top_features: [string, number][];
  regime: string;
  defer: boolean;
  sentence: string;
}

export interface DistrictPayload {
  disclaimer: string;
  region: string;
  variable: Variable;
  units: string;
  init_time: string;
  meta: Record<string, unknown>;
  district: { district_id: string; district: string; state: string; coverage: number; leads: LeadPayload[] };
}

export interface SkillMap {
  region: string;
  variable: Variable;
  lead_day: number;
  init_time: string;
  half_life_days: number;
  cells: { lat: number; lon: number; best_source: string | null; dmse: Record<string, number | null> }[];
}

export interface LeaderboardRow {
  source: string;
  kind: string;
  lead_day: number;
  rmse: number | null;
  rmse_lo: number | null;
  rmse_hi: number | null;
  crps: number | null;
  ets_heavy: number | null;
  n_cases: number | null;
  recent_rmse: number | null;
}

export interface SourceStatus {
  source: string;
  label: string;
  kind: string;
  adapters: string[];
  status: string;
  detail: string;
  last_archived_init: string | null;
  eval_first_init: string | null;
  eval_last_init: string | null;
  licence: string;
}

export interface Replay {
  event_id: string;
  title: string;
  region: string;
  variable: Variable;
  district_id: string;
  focus_day: string;
  observed: Record<string, number | null>;
  series: { forecast: string; lead_day: number; values: Record<string, number | null> }[];
  notes: string[];
}

export async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      if (j?.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* keep status text */
    }
    throw new Error(detail);
  }
  return (await r.json()) as T;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof j?.detail === "string" ? j.detail : JSON.stringify(j?.detail ?? r.status));
  return j as T;
}

/** Fetch hook with explicit loading and error state (every data call in the UI uses it). */
export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(!!path);
  const [nonce, setNonce] = useState(0);
  const reload = useCallback(() => setNonce((n) => n + 1), []);
  useEffect(() => {
    if (!path) return;
    let alive = true;
    setLoading(true);
    setError(null);
    apiGet<T>(path)
      .then((d) => alive && setData(d))
      .catch((e: Error) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [path, nonce]);
  return { data, error, loading, reload };
}

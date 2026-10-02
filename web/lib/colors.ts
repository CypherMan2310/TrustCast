/** Colour scales for map layers (MapLibre expressions) and charts. */

// IMD daily rainfall categories (mm): very light 0.1-2.4, light 2.5-15.5, moderate 15.6-64.4,
// heavy 64.5-115.5, very heavy 115.6-204.4, extremely heavy >= 204.5
export const RAIN_STOPS: [number, string][] = [
  [0, "rgba(0,0,0,0)"],
  [0.1, "#d8f0fb"],
  [2.5, "#9ed4f2"],
  [15.6, "#4aa3e0"],
  [35, "#1f6fc4"],
  [64.5, "#f2c14e"],
  [115.6, "#e8743b"],
  [204.5, "#b3226b"],
];

export const TEMP_STOPS: [number, string][] = [
  [20, "#4b8fd6"],
  [28, "#a7d3a6"],
  [34, "#f6e27f"],
  [38, "#f4a259"],
  [40, "#e8603c"],
  [43, "#b8233e"],
  [46, "#6d0f38"],
];

export const PROB_STOPS: [number, string][] = [
  [0, "rgba(0,0,0,0)"],
  [0.05, "#efe7fb"],
  [0.2, "#c9b6f0"],
  [0.4, "#9b7be0"],
  [0.7, "#6a3fc7"],
  [1, "#3d1a8c"],
];

export const SPREAD_STOPS: [number, string][] = [
  [0, "rgba(0,0,0,0)"],
  [2, "#fde6c8"],
  [10, "#f7b267"],
  [25, "#e0662f"],
  [60, "#99290f"],
];

export const SOURCE_COLORS: Record<string, string> = {
  ecmwf_ifs: "#1f77b4",
  ecmwf_ifs_ctrl: "#6baed6",
  ecmwf_aifs: "#9467bd",
  ncep_gfs: "#d62728",
  dwd_icon: "#2ca02c",
  cmc_gem: "#8c564b",
  ncep_gefs: "#ff7f0e",
  ecmwf_ifs_ens: "#17becf",
  ecmwf_aifs_ens: "#e377c2",
  trustcast: "#4f46e5",
  equal_mean: "#94a3b8",
  superensemble: "#bcbd22",
  observed: "#334155",
};

export function stopsFor(layer: string, variable: "precip" | "tmax"): [number, string][] {
  if (layer.startsWith("prob_")) return PROB_STOPS;
  if (layer === "disagreement") return variable === "precip" ? SPREAD_STOPS : SPREAD_STOPS.map(([v, c]) => [v / 8, c]);
  if (layer === "defer") return [[0, "rgba(0,0,0,0)"], [1, "#e11d48"]];
  return variable === "precip" ? RAIN_STOPS : TEMP_STOPS;
}

/** MapLibre 'step' colour expression for a numeric property. */
export function stepExpression(stops: [number, string][], prop = "v"): unknown[] {
  const expr: unknown[] = ["step", ["get", prop], stops[0][1]];
  for (const [v, c] of stops.slice(1)) expr.push(v, c);
  return expr;
}

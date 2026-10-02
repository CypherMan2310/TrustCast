"use client";

import * as maplibregl from "maplibre-gl";
import { useEffect, useRef } from "react";
import { stepExpression } from "@/lib/colors";
import { featureNear } from "@/lib/geo";

const esc = (t: string) => t.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" })[c] as string);

export interface Cell {
  lat: number;
  lon: number;
  v: number | null;
  cat?: string | null;
}

interface Props {
  cells: Cell[];
  stops?: [number, string][];
  categorical?: Record<string, string>;
  districts?: GeoJSON.FeatureCollection | null;
  onDistrictClick?: (id: string, name: string) => void;
  formatValue?: (v: number) => string;
  formatCategory?: (c: string) => string;
  height?: number | string;
}

const H = 0.125;

// MapLibre v6 loads its worker as a separate ES module; serve it from public/ (see scripts/copy-maplibre-worker.mjs)
if (typeof window !== "undefined") maplibregl.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");

function cellsToGeoJSON(cells: Cell[]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: cells
      .filter((c) => c.v !== null || c.cat)
      .map((c) => ({
        type: "Feature",
        properties: { v: c.v ?? 0, cat: c.cat ?? "" },
        geometry: {
          type: "Polygon",
          coordinates: [[[c.lon - H, c.lat - H], [c.lon + H, c.lat - H], [c.lon + H, c.lat + H], [c.lon - H, c.lat + H], [c.lon - H, c.lat - H]]],
        },
      })),
  };
}

// Keyless vector basemap (OpenFreeMap, OSM data). CARTO raster tiles now need an API key.
const basemap = (dark: boolean) => `https://tiles.openfreemap.org/styles/${dark ? "dark" : "positron"}`;
const DATA_SOURCES = ["cells", "districts"];

// data layers go under the basemap labels so place names stay readable
const firstSymbol = (m: maplibregl.Map) => m.getStyle().layers.find((l) => l.type === "symbol")?.id;

const isDark = () => typeof document !== "undefined" && document.documentElement.dataset.theme === "dark";

export default function MapView({ cells, stops, categorical, districts, onDistrictClick, formatValue, formatCategory, height = 520 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const loaded = useRef(false);
  const latest = useRef({ cells, stops, categorical, districts, onDistrictClick, formatValue, formatCategory });

  const draw = () => {
    const m = map.current;
    if (!m || !loaded.current) return;
    const { cells: cs, stops: st, categorical: cat, districts: ds } = latest.current;
    const fc = cellsToGeoJSON(cs);
    const src = m.getSource("cells") as maplibregl.GeoJSONSource | undefined;
    if (src) src.setData(fc);
    else m.addSource("cells", { type: "geojson", data: fc });
    const color = cat
      ? (["match", ["get", "cat"], ...Object.entries(cat).flat(), "rgba(0,0,0,0)"] as unknown)
      : stepExpression(st ?? [[0, "#999"]]);
    if (!m.getLayer("cells-fill")) {
      m.addLayer({ id: "cells-fill", type: "fill", source: "cells", paint: { "fill-color": color as never, "fill-opacity": 0.78 } }, firstSymbol(m));
    } else {
      m.setPaintProperty("cells-fill", "fill-color", color as never);
    }
    if (ds) {
      const dsrc = m.getSource("districts") as maplibregl.GeoJSONSource | undefined;
      if (dsrc) dsrc.setData(ds);
      else {
        m.addSource("districts", { type: "geojson", data: ds });
        m.addLayer({ id: "districts-line", type: "line", source: "districts", paint: { "line-color": isDark() ? "#cbd5e1" : "#334155", "line-width": 0.8, "line-opacity": 0.8 } }, firstSymbol(m));
      }
    }
    if (fc.features.length) {
      const lons = cs.map((c) => c.lon);
      const lats = cs.map((c) => c.lat);
      const b: [number, number, number, number] = [Math.min(...lons) - H, Math.min(...lats) - H, Math.max(...lons) + H, Math.max(...lats) + H];
      const key = b.join(",");
      if (m.getContainer().dataset.bounds !== key) {
        m.fitBounds(b, { padding: 20, duration: 0 });
        m.getContainer().dataset.bounds = key;
      }
    }
  };

  useEffect(() => {
    if (!ref.current || map.current) return;
    const m = new maplibregl.Map({ container: ref.current, style: basemap(isDark()), center: [77, 15], zoom: 5, attributionControl: { compact: true } });
    map.current = m;
    if (process.env.NODE_ENV !== "production") (window as unknown as { __tcMap?: maplibregl.Map }).__tcMap = m; // dev-only handle for automated checks
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    // hover label: offset from the cursor and click-through (see .tc-hover in globals.css), so it never swallows a click
    const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 14, className: "tc-hover", maxWidth: "260px" });
    // draw as soon as the style is parsed; waiting for "load" would also wait for every basemap tile
    m.once("style.load", () => {
      loaded.current = true;
      m.getContainer().dataset.loaded = "1"; // marker for automated checks
      draw();
    });
    // District lookup uses the boundary geometry itself (lib/geo), not the rendered feature index,
    // so every district is clickable regardless of layer order, opacity or tile state.
    const districtAt = (pt: maplibregl.Point): GeoJSON.Feature | null => {
      const fc = latest.current.districts;
      if (!fc) return null;
      const tol = 5; // px: clicks on borders or tiny districts still register
      const probes = [[0, 0], [tol, 0], [-tol, 0], [0, tol], [0, -tol], [tol, tol], [-tol, -tol], [tol, -tol], [-tol, tol]].map(([dx, dy]) => {
        const ll = m.unproject([pt.x + dx, pt.y + dy]);
        return [ll.lng, ll.lat] as [number, number];
      });
      return featureNear(fc, probes);
    };
    m.on("mousemove", (e) => {
      const cell = m.getLayer("cells-fill") ? m.queryRenderedFeatures(e.point, { layers: ["cells-fill"] })[0] : undefined;
      const dist = latest.current.onDistrictClick || latest.current.districts ? districtAt(e.point) : null;
      if (!cell && !dist) {
        popup.remove();
        m.getCanvas().style.cursor = "";
        return;
      }
      m.getCanvas().style.cursor = dist && latest.current.onDistrictClick ? "pointer" : "";
      const { formatValue: fv, formatCategory: fc } = latest.current;
      const val = cell ? (cell.properties.cat ? (fc ? fc(String(cell.properties.cat)) : String(cell.properties.cat)) : fv ? fv(Number(cell.properties.v)) : String(cell.properties.v)) : "";
      const name = dist ? `<b>${esc(String(dist.properties?.district))}</b>, ${esc(String(dist.properties?.state))}<br/>` : "";
      popup.setLngLat(e.lngLat).setHTML(`<div style="font-size:12px">${name}${esc(val)}</div>`).addTo(m);
    });
    m.on("click", (e) => {
      const cb = latest.current.onDistrictClick;
      const f = cb ? districtAt(e.point) : null;
      if (cb && f) cb(String(f.properties?.district_id), String(f.properties?.district));
    });
    const onTheme = () => {
      // swap the basemap style and carry the data sources/layers over (inserted under the labels)
      m.setStyle(basemap(isDark()), {
        transformStyle: (prev, next) => {
          if (!prev) return next;
          const keep = prev.layers.filter((l) => "source" in l && DATA_SOURCES.includes(String(l.source)));
          const at = next.layers.findIndex((l) => l.type === "symbol");
          const layers = at < 0 ? [...next.layers, ...keep] : [...next.layers.slice(0, at), ...keep, ...next.layers.slice(at)];
          const sources = { ...next.sources };
          for (const k of DATA_SOURCES) if (prev.sources[k]) sources[k] = prev.sources[k];
          return { ...next, sources, layers };
        },
      });
      m.once("styledata", () => {
        if (m.getLayer("districts-line")) m.setPaintProperty("districts-line", "line-color", isDark() ? "#cbd5e1" : "#334155");
      });
    };
    window.addEventListener("themechange", onTheme);
    return () => {
      window.removeEventListener("themechange", onTheme);
      const el = m.getContainer();
      m.remove();
      map.current = null;
      loaded.current = false;
      delete el.dataset.loaded; // a re-mount (React StrictMode) must fit and mark again
      delete el.dataset.bounds;
    };
  }, []);

  useEffect(() => {
    latest.current = { cells, stops, categorical, districts, onDistrictClick, formatValue, formatCategory };
    draw();
  }, [cells, stops, categorical, districts, onDistrictClick, formatValue, formatCategory]);

  return <div ref={ref} style={{ height }} className="w-full overflow-hidden rounded-2xl" aria-label="Forecast map" role="region" />;
}

export function Legend({ stops, units, title }: { stops: [number, string][]; units: string; title?: string }) {
  // stepped colour bar: one swatch per class, labelled with its lower bound
  const shown = stops.filter(([, c]) => c !== "rgba(0,0,0,0)");
  const fmtV = (v: number) => (units === "probability" ? `${Math.round(v * 100)}%` : Number.isInteger(v) ? String(v) : v.toFixed(1));
  return (
    <div className="min-w-0">
      {title && <div className="mb-1 text-[11px] font-medium text-[var(--muted)]">{title}</div>}
      <div className="flex items-end gap-2">
        <div className="flex min-w-0 flex-1">
          {shown.map(([v, c], i) => (
            <div key={i} className="min-w-[34px] flex-1">
              <div className={`h-2.5 ${i === 0 ? "rounded-l-full" : ""} ${i === shown.length - 1 ? "rounded-r-full" : ""}`} style={{ background: c }} />
              <div className="tabular mt-1 text-[10px] text-[var(--muted)]">≥{fmtV(v)}</div>
            </div>
          ))}
        </div>
        <span className="pb-3.5 text-[11px] whitespace-nowrap text-[var(--muted)]">{units === "probability" ? "" : units}</span>
      </div>
    </div>
  );
}

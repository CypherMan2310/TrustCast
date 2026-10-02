"use client";

import * as maplibregl from "maplibre-gl";
import { useEffect, useRef } from "react";
import { stepExpression } from "@/lib/colors";

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

export default function MapView({ cells, stops, categorical, districts, onDistrictClick, formatValue, height = 520 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const loaded = useRef(false);
  const latest = useRef({ cells, stops, categorical, districts, onDistrictClick, formatValue });

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
        m.addLayer({ id: "districts-hit", type: "fill", source: "districts", paint: { "fill-color": "#000", "fill-opacity": 0 } }, firstSymbol(m));
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
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false });
    // draw as soon as the style is parsed; waiting for "load" would also wait for every basemap tile
    m.once("style.load", () => {
      loaded.current = true;
      m.getContainer().dataset.loaded = "1"; // marker for automated checks
      draw();
    });
    m.on("mousemove", (e) => {
      const f = m.queryRenderedFeatures(e.point, { layers: ["cells-fill", "districts-hit"].filter((l) => m.getLayer(l)) });
      const cell = f.find((x) => x.layer.id === "cells-fill");
      const dist = f.find((x) => x.layer.id === "districts-hit");
      if (!cell && !dist) {
        popup.remove();
        m.getCanvas().style.cursor = "";
        return;
      }
      m.getCanvas().style.cursor = dist ? "pointer" : "";
      const fv = latest.current.formatValue;
      const val = cell ? (cell.properties.cat ? String(cell.properties.cat) : fv ? fv(Number(cell.properties.v)) : String(cell.properties.v)) : "";
      const name = dist ? `<b>${dist.properties.district}</b>, ${dist.properties.state}<br/>` : "";
      popup.setLngLat(e.lngLat).setHTML(`<div style="font-size:12px">${name}${val}</div>`).addTo(m);
    });
    m.on("click", "districts-hit", (e) => {
      const f = e.features?.[0];
      if (f && latest.current.onDistrictClick) latest.current.onDistrictClick(String(f.properties.district_id), String(f.properties.district));
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
    latest.current = { cells, stops, categorical, districts, onDistrictClick, formatValue };
    draw();
  }, [cells, stops, categorical, districts, onDistrictClick, formatValue]);

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

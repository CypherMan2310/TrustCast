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
  height?: number;
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

function basemap(dark: boolean): maplibregl.StyleSpecification {
  const flavour = dark ? "dark_all" : "light_all";
  return {
    version: 8,
    sources: {
      base: {
        type: "raster",
        tiles: ["a", "b", "c"].map((s) => `https://${s}.basemaps.cartocdn.com/${flavour}/{z}/{x}/{y}.png`),
        tileSize: 256,
        attribution: "© OpenStreetMap contributors © CARTO",
      },
    },
    layers: [{ id: "base", type: "raster", source: "base" }],
  };
}

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
      m.addLayer({ id: "cells-fill", type: "fill", source: "cells", paint: { "fill-color": color as never, "fill-opacity": 0.78 } });
    } else {
      m.setPaintProperty("cells-fill", "fill-color", color as never);
    }
    if (ds) {
      const dsrc = m.getSource("districts") as maplibregl.GeoJSONSource | undefined;
      if (dsrc) dsrc.setData(ds);
      else {
        m.addSource("districts", { type: "geojson", data: ds });
        m.addLayer({ id: "districts-hit", type: "fill", source: "districts", paint: { "fill-color": "#000", "fill-opacity": 0 } });
        m.addLayer({ id: "districts-line", type: "line", source: "districts", paint: { "line-color": isDark() ? "#cbd5e1" : "#334155", "line-width": 0.8, "line-opacity": 0.8 } });
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
    m.on("load", () => {
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
      // swap only the basemap tiles; data layers stay
      const flavour = isDark() ? "dark_all" : "light_all";
      const s = m.getSource("base") as maplibregl.RasterTileSource | undefined;
      s?.setTiles(["a", "b", "c"].map((x) => `https://${x}.basemaps.cartocdn.com/${flavour}/{z}/{x}/{y}.png`));
      if (m.getLayer("districts-line")) m.setPaintProperty("districts-line", "line-color", isDark() ? "#cbd5e1" : "#334155");
    };
    window.addEventListener("themechange", onTheme);
    return () => {
      window.removeEventListener("themechange", onTheme);
      m.remove();
      map.current = null;
      loaded.current = false;
    };
  }, []);

  useEffect(() => {
    latest.current = { cells, stops, categorical, districts, onDistrictClick, formatValue };
    draw();
  }, [cells, stops, categorical, districts, onDistrictClick, formatValue]);

  return <div ref={ref} style={{ height }} className="w-full overflow-hidden rounded-xl border border-[var(--border)]" aria-label="Forecast map" role="region" />;
}

export function Legend({ stops, units }: { stops: [number, string][]; units: string }) {
  return (
    <div className="flex flex-wrap items-center gap-1 text-xs text-[var(--muted)]">
      {stops.map(([v, c], i) => (
        <span key={i} className="flex items-center gap-1">
          <span className="inline-block h-3 w-5 rounded-sm border border-[var(--border)]" style={{ background: c }} />
          {i === 0 ? `<${stops[1]?.[0] ?? v}` : `≥${v}`}
        </span>
      ))}
      <span className="ml-1">{units}</span>
    </div>
  );
}

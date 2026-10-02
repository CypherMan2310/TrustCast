/** Point-in-polygon lookup for district boundaries (GeoJSON Polygon / MultiPolygon, lon/lat). */

type Ring = number[][];

function inRing(x: number, y: number, ring: Ring): boolean {
  // ray casting; edges are treated half-open so shared borders belong to exactly one side
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function inPolygon(x: number, y: number, rings: Ring[]): boolean {
  if (!rings.length || !inRing(x, y, rings[0])) return false;
  for (let h = 1; h < rings.length; h++) if (inRing(x, y, rings[h])) return false; // holes
  return true;
}

/** The feature whose geometry contains (lon, lat), or null. */
export function featureAt(fc: GeoJSON.FeatureCollection | null | undefined, lon: number, lat: number): GeoJSON.Feature | null {
  if (!fc) return null;
  for (const f of fc.features) {
    const g = f.geometry;
    if (!g) continue;
    if (g.type === "Polygon" && inPolygon(lon, lat, g.coordinates as Ring[])) return f;
    if (g.type === "MultiPolygon" && (g.coordinates as Ring[][]).some((p) => inPolygon(lon, lat, p))) return f;
  }
  return null;
}

/** Exact hit first, then the first hit among nearby probe points (for clicks on borders or tiny districts). */
export function featureNear(fc: GeoJSON.FeatureCollection | null | undefined, probes: [number, number][]): GeoJSON.Feature | null {
  for (const [lon, lat] of probes) {
    const f = featureAt(fc, lon, lat);
    if (f) return f;
  }
  return null;
}

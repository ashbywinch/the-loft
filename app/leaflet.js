/**
 * Leaflet is ~225 KB and only the Places map uses it. Load it on that route
 * instead of putting it on every page; the Places view keeps its SVG dot
 * fallback when this fails.
 */

let pending = null;

export function loadLeaflet() {
  if (typeof window !== "undefined" && window.L?.map && window.L?.heatLayer) return Promise.resolve();
  if (pending) return pending;
  pending = new Promise((resolve, reject) => {
    const css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = "vendor/leaflet.css";
    document.head.append(css);

    const leaflet = document.createElement("script");
    leaflet.src = "vendor/leaflet.js";
    leaflet.onload = () => {
      const heat = document.createElement("script");
      heat.src = "vendor/leaflet-heat.js";
      heat.onload = () => resolve();
      heat.onerror = () => {
        pending = null;
        reject(new Error("leaflet-heat failed"));
      };
      document.head.append(heat);
    };
    leaflet.onerror = () => {
      pending = null;
      reject(new Error("leaflet failed"));
    };
    document.head.append(leaflet);
  });
  return pending;
}

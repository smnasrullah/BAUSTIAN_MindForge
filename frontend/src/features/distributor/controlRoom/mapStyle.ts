// Offline-first style: the bundled Natural Earth boundary on a solid base, coloured from the design
// tokens (light by default, dark in the dark theme). Online raster tiles exist only as a hidden layer
// the user can switch on. No glyphs or sprites, so nothing is fetched unless that toggle is on.
import type { FeatureCollection } from "geojson";
import type { ExpressionSpecification, Map as MlMap, RasterTileSource, StyleSpecification } from "maplibre-gl";

import type { MapPalette } from "./mapPalette";

export const SRC = { agents: "agents", swaps: "swaps", droplets: "droplets" } as const;
export const LAYER = {
  tiles: "online-tiles",
  land: "bd-land",
  clusterEdge: "cluster-edge",
  cluster: "cluster-core",
  clusterInner: "cluster-inner",
  glow: "agent-halo",
  alert: "agent-alert-ring",
  ripple: "agent-ripple",
  dot: "agent-dot",
} as const;

export const BOUNDARY_URL = "/geo/bangladesh.geojson";
// "@2x" tiles (512 px drawn at 256): sharp street labels on high-density screens instead of upscaled blur.
export const tileUrls = (dark: boolean) =>
  ["a", "b", "c"].map((s) => `https://${s}.basemaps.cartocdn.com/${dark ? "dark_all" : "light_all"}/{z}/{x}/{y}@2x.png`);
/** Google-Maps-like light street tiles (road names, transit, places), used by the van map in both themes. */
export const streetTileUrls = () =>
  ["a", "b", "c"].map((s) => `https://${s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}@2x.png`);
const EMPTY: FeatureCollection = { type: "FeatureCollection", features: [] };

export const LAND_OPACITY = { offline: 1, online: 0.35 } as const;

const IS_CLUSTER: ExpressionSpecification = ["has", "point_count"];
const HOVER: ExpressionSpecification = ["boolean", ["feature-state", "hover"], false];

/**
 * Risk is never colour alone on the map: size grows with risk (safe 5, watch 6.5, act now 8),
 * "Act now" dots carry an extra outer ring, and the legend explains both.
 */
const BASE_R: ExpressionSpecification = ["match", ["get", "level"], "red", 8, "amber", 6.5, 5];
const DOT_R: ExpressionSpecification = ["+", BASE_R, ["case", ["get", "selected"], 2, HOVER, 1.5, 0]];
const CLUSTER_R: ExpressionSpecification = ["step", ["get", "point_count"], 15, 10, 19, 50, 23];

function riskColor(p: MapPalette): ExpressionSpecification {
  return ["match", ["get", "level"], "red", p.risk.red, "amber", p.risk.amber, p.risk.green];
}

/** Colour by the worst level inside a cluster (maxSev: 0 safe, 1 watch, 2 act). */
function clusterColor(p: MapPalette): ExpressionSpecification {
  return ["match", ["get", "maxSev"], 2, p.risk.red, 1, p.risk.amber, p.risk.green];
}

export function mapStyle(boundaryUrl: string, online: boolean, p: MapPalette): StyleSpecification {
  return {
    version: 8,
    sources: {
      tiles: {
        type: "raster",
        tiles: tileUrls(p.dark),
        tileSize: 256,
        maxzoom: 18,
        attribution: "© OpenStreetMap contributors © CARTO",
      },
      boundary: { type: "geojson", data: boundaryUrl, attribution: "Natural Earth (public domain)" },
      [SRC.agents]: {
        type: "geojson",
        data: EMPTY,
        cluster: true,
        clusterRadius: 42,
        clusterMaxZoom: 9,
        clusterProperties: { maxSev: ["max", ["get", "sev"]] },
      },
      [SRC.swaps]: { type: "geojson", data: EMPTY },
      [SRC.droplets]: { type: "geojson", data: EMPTY },
    },
    layers: [
      { id: "background", type: "background", paint: { "background-color": p.water } },
      {
        id: LAYER.tiles,
        type: "raster",
        source: "tiles",
        layout: { visibility: online ? "visible" : "none" },
        paint: { "raster-opacity": 0.85 },
      },
      {
        id: LAYER.land,
        type: "fill",
        source: "boundary",
        paint: { "fill-color": p.land, "fill-opacity": online ? LAND_OPACITY.online : LAND_OPACITY.offline },
      },
      { id: "bd-divisions", type: "line", source: "boundary", paint: { "line-color": p.border, "line-width": 1 } },
      {
        id: "swap-lines",
        type: "line",
        source: SRC.swaps,
        layout: { "line-cap": "round" },
        paint: {
          "line-color": p.flow,
          "line-width": ["case", ["get", "relevant"], 2.5, 1.5],
          "line-opacity": ["case", ["get", "relevant"], 0.9, 0.35],
          "line-dasharray": [2, 2],
        },
      },
      // Cluster: dark edge, risk-coloured ring, calm centre for the (DOM) count label.
      {
        id: LAYER.clusterEdge,
        type: "circle",
        source: SRC.agents,
        filter: IS_CLUSTER,
        paint: { "circle-color": p.outline, "circle-radius": ["+", CLUSTER_R, 1.5] },
      },
      {
        id: LAYER.cluster,
        type: "circle",
        source: SRC.agents,
        filter: IS_CLUSTER,
        paint: { "circle-color": clusterColor(p), "circle-radius": CLUSTER_R },
      },
      {
        id: LAYER.clusterInner,
        type: "circle",
        source: SRC.agents,
        filter: IS_CLUSTER,
        paint: { "circle-color": p.halo, "circle-radius": ["-", CLUSTER_R, 4] },
      },
      // Single agents: halo (separates the dot from borders), act-now ring, selection ring, dot.
      {
        id: LAYER.glow,
        type: "circle",
        source: SRC.agents,
        filter: ["!", IS_CLUSTER],
        paint: { "circle-color": p.halo, "circle-radius": ["+", DOT_R, 2.5], "circle-opacity": 0.95 },
      },
      {
        id: LAYER.alert,
        type: "circle",
        source: SRC.agents,
        filter: ["all", ["!", IS_CLUSTER], ["==", ["get", "level"], "red"]],
        paint: {
          "circle-radius": ["+", DOT_R, 5.5],
          "circle-opacity": 0,
          "circle-stroke-color": p.risk.red,
          "circle-stroke-width": 2,
          "circle-stroke-opacity": 0.9,
        },
      },
      {
        id: LAYER.ripple,
        type: "circle",
        source: SRC.agents,
        filter: ["all", ["!", IS_CLUSTER], ["==", ["get", "selected"], true]],
        paint: {
          "circle-radius": ["+", DOT_R, 9],
          "circle-opacity": 0,
          "circle-stroke-color": p.selected,
          "circle-stroke-width": 2.5,
          "circle-stroke-opacity": 1,
        },
      },
      {
        id: LAYER.dot,
        type: "circle",
        source: SRC.agents,
        filter: ["!", IS_CLUSTER],
        paint: {
          "circle-color": riskColor(p),
          "circle-radius": DOT_R,
          "circle-stroke-color": p.outline,
          "circle-stroke-width": ["case", HOVER, 2.5, ["get", "selected"], 2, 1.25],
        },
      },
      {
        id: "droplets",
        type: "circle",
        source: SRC.droplets,
        paint: {
          "circle-color": p.droplet,
          "circle-radius": 3.5,
          "circle-stroke-color": p.outline,
          "circle-stroke-width": 1,
        },
      },
    ],
  };
}

/** Re-colour a live map after a theme switch: every *-color paint value comes from mapStyle itself. */
export function applyMapPalette(map: MlMap, boundaryUrl: string, online: boolean, p: MapPalette): void {
  for (const layer of mapStyle(boundaryUrl, online, p).layers) {
    if (!("paint" in layer) || !layer.paint) continue;
    for (const [prop, value] of Object.entries(layer.paint)) {
      if (prop.endsWith("-color") && map.getLayer(layer.id)) map.setPaintProperty(layer.id, prop, value);
    }
  }
  map.getSource<RasterTileSource>("tiles")?.setTiles(tileUrls(p.dark));
}

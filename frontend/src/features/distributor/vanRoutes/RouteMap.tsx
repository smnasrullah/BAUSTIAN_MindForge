import "maplibre-gl/dist/maplibre-gl.css";

import type { FeatureCollection } from "geojson";
import {
  Map as MlMap,
  NavigationControl,
  type ExpressionSpecification,
  type GeoJSONSource,
  type Marker,
  type RasterTileSource,
} from "maplibre-gl";
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useTranslation } from "react-i18next";

import type { VanPlan } from "../../../api/vanPlans";
import { formatNumber } from "../../../lib/format";
import { useReducedMotionPref } from "../../../lib/motionPrefs";
import { useLocale } from "../../../lib/prefs";
import { MS } from "../../../styles/motion";
import { VAN_NS } from "../../../i18n/vanRoutes";
import { BD_BOUNDS } from "../controlRoom/mapModel";
import { readMapPalette } from "../controlRoom/mapPalette";
import { applyMapPalette, BOUNDARY_URL, LAND_OPACITY, LAYER as BASE, mapStyle, streetTileUrls } from "../controlRoom/mapStyle";
import { ARROW_IMAGE, arrowImage } from "./routeArrows";
import { clearStopMarkers, syncDepotMarker, syncStopMarkers } from "./routeMarkers";
import { readRoutePalette } from "./routePalette";
import { planBounds, routeLines, spokeLines, stopMarkers, type MapView, type StopMarker } from "./vanRoutesModel";

export interface RouteMapProps {
  plan: VanPlan;
  view: MapView;
  selectedStopId: number | null;
  onSelect: (stopId: number) => void;
  /** Online street tiles under the routes (off = the bundled offline map only). */
  onlineTiles: boolean;
  /** WebGL or style start-up failed; the page keeps the list and the numbers. */
  onFail: () => void;
  /** Text summary for screen readers. */
  label: string;
  /** Bumped by the "Fit route" button: frames the whole plan again. */
  fitSignal?: number;
}

const SRC = { routes: "van-routes", spokes: "van-spokes" } as const;
const LAYER = { casing: "van-route-casing", line: "van-route-line", approx: "van-route-approx", arrow: "van-route-arrow", spoke: "van-spoke" } as const;
/** Layers of the optimised view; the spoke layer is the separate-trips view. */
const ROUTE_LAYERS = [LAYER.casing, LAYER.line, LAYER.approx, LAYER.arrow] as const;
const EMPTY: FeatureCollection = { type: "FeatureCollection", features: [] };
/** Street level around one stop; the map never zooms out to reach a stop. */
const FOCUS_ZOOM = 12;

const boundaryHref = () => new URL(BOUNDARY_URL, window.location.origin).href;

/** Line width by zoom: thin over the whole country, a bold road-like stroke at street level. */
const width = (atCountry: number, atStreet: number): ExpressionSpecification => ["interpolate", ["linear"], ["zoom"], 6, atCountry, 13, atStreet];

/** Adds the van sources and layers on top of the control-room base style (boundary, water, land). */
function addVanLayers(m: MlMap): void {
  const p = readMapPalette();
  m.addSource(SRC.routes, { type: "geojson", data: EMPTY });
  m.addSource(SRC.spokes, { type: "geojson", data: EMPTY });
  if (!m.hasImage(ARROW_IMAGE)) m.addImage(ARROW_IMAGE, arrowImage(), { sdf: true, pixelRatio: 2 });
  m.addLayer({
    id: LAYER.spoke,
    type: "line",
    source: SRC.spokes,
    layout: { "line-cap": "round", visibility: "none" },
    paint: { "line-color": p.outline, "line-width": 1.5, "line-opacity": 0.6, "line-dasharray": [2, 2] },
  });
  m.addLayer({
    id: LAYER.casing,
    type: "line",
    source: SRC.routes,
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": p.halo, "line-width": width(6, 11), "line-opacity": 0.95 },
  });
  m.addLayer({
    id: LAYER.line,
    type: "line",
    source: SRC.routes,
    layout: { "line-cap": "round", "line-join": "round" },
    filter: ["!", ["get", "approx"]],
    paint: { "line-color": ["get", "color"], "line-width": width(3.5, 7) },
  });
  // No road polyline for this leg: a thin dashed straight line, so nobody reads it as a road.
  m.addLayer({
    id: LAYER.approx,
    type: "line",
    source: SRC.routes,
    filter: ["get", "approx"],
    layout: { "line-cap": "butt", "line-join": "round" },
    paint: { "line-color": ["get", "color"], "line-width": width(2.5, 4.5), "line-dasharray": [1.5, 1.5] },
  });
  // Travel direction: chevrons repeat along every leg, in the halo colour so they read on any van colour.
  m.addLayer({
    id: LAYER.arrow,
    type: "symbol",
    source: SRC.routes,
    layout: {
      "symbol-placement": "line",
      "symbol-spacing": 70,
      "icon-image": ARROW_IMAGE,
      "icon-size": ["interpolate", ["linear"], ["zoom"], 6, 0.6, 13, 1],
      "icon-rotation-alignment": "map",
      "icon-allow-overlap": true,
      "icon-ignore-placement": true,
    },
    paint: { "icon-color": p.halo },
  });
}

/** Ink and halo on the light street tiles, whatever the theme: routes and markers keep high contrast. */
const STREET_INK = { halo: "#ffffff", outline: "#0f172a" } as const;
const STREET_VARS = { "--map-halo": STREET_INK.halo, "--map-outline": STREET_INK.outline } as CSSProperties;

/** Street tiles on = light standard map, opaque, offline land hidden, white route casing. Off = offline map. */
function applyStreetBase(m: MlMap, on: boolean): void {
  m.setLayoutProperty(BASE.tiles, "visibility", on ? "visible" : "none");
  m.setPaintProperty(BASE.tiles, "raster-opacity", on ? 1 : 0.85);
  m.setPaintProperty(BASE.land, "fill-opacity", on ? 0 : LAND_OPACITY.offline);
  if (on) m.getSource<RasterTileSource>("tiles")?.setTiles(streetTileUrls());
  if (!m.getLayer(LAYER.casing)) return;
  const p = readMapPalette();
  const halo = on ? STREET_INK.halo : p.halo;
  m.setPaintProperty(LAYER.casing, "line-color", halo);
  m.setPaintProperty(LAYER.arrow, "icon-color", halo);
  m.setPaintProperty(LAYER.spoke, "line-color", on ? STREET_INK.outline : p.outline);
}

/** MapLibre map of one van plan: route lines in van colours, numbered stops, the depot. Loaded lazily. */
export default function RouteMap({ plan, view, selectedStopId, onSelect, onlineTiles, onFail, label, fitSignal = 0 }: RouteMapProps) {
  const { t: tv } = useTranslation(VAN_NS);
  const reduced = useReducedMotionPref();
  const { digits } = useLocale();
  const ref = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<MlMap | null>(null);
  const [palette, setPalette] = useState<string[]>(() => readRoutePalette());
  const stopMarks = useRef(new Map<number, Marker>());
  const depotMark = useRef<Marker | null>(null);
  const handlers = useRef({ onFail, onSelect });
  const online = useRef(onlineTiles);

  useEffect(() => {
    handlers.current = { onFail, onSelect };
  }, [onFail, onSelect]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let m: MlMap;
    try {
      m = new MlMap({
        container: el,
        style: mapStyle(boundaryHref(), online.current, readMapPalette()),
        bounds: BD_BOUNDS,
        fitBoundsOptions: { padding: 16 },
        maxBounds: [
          [84, 18],
          [96.5, 29],
        ],
        minZoom: 5,
        maxZoom: 15,
        dragRotate: false,
        pitchWithRotate: false,
        touchPitch: false,
        attributionControl: { compact: true },
      });
    } catch {
      handlers.current.onFail();
      return;
    }
    m.touchZoomRotate.disableRotation();
    m.addControl(new NavigationControl({ showCompass: false }), "top-right");
    // A listener keeps maplibre from logging; a missing boundary file must not break the page.
    m.on("error", () => undefined);
    m.on("load", () => {
      addVanLayers(m);
      setMap(m);
    });

    // Theme switch: re-colour the base map and re-read the route colours.
    const themeWatch = new MutationObserver(() => {
      if (!m.isStyleLoaded()) return;
      const p = readMapPalette();
      applyMapPalette(m, boundaryHref(), online.current, p);
      if (m.getLayer(LAYER.casing)) {
        m.setPaintProperty(LAYER.casing, "line-color", p.halo);
        m.setPaintProperty(LAYER.arrow, "icon-color", p.halo);
        m.setPaintProperty(LAYER.spoke, "line-color", p.outline);
      }
      applyStreetBase(m, online.current);
      setPalette(readRoutePalette());
    });
    themeWatch.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const resize = new ResizeObserver(() => m.resize());
    resize.observe(el);
    const stops = stopMarks.current;
    return () => {
      themeWatch.disconnect();
      resize.disconnect();
      clearStopMarkers(stops);
      depotMark.current?.remove();
      depotMark.current = null;
      m.remove();
    };
  }, []);

  useEffect(() => {
    if (!map) return;
    map.getSource<GeoJSONSource>(SRC.routes)?.setData(routeLines(plan, palette));
    map.getSource<GeoJSONSource>(SRC.spokes)?.setData(spokeLines(plan));
  }, [map, plan, palette]);

  useEffect(() => {
    if (!map) return;
    const optimised = view === "optimised";
    for (const id of ROUTE_LAYERS) map.setLayoutProperty(id, "visibility", optimised ? "visible" : "none");
    map.setLayoutProperty(LAYER.spoke, "visibility", optimised ? "none" : "visible");
  }, [map, view]);

  useEffect(() => {
    online.current = onlineTiles;
    if (!map) return;
    applyStreetBase(map, onlineTiles);
  }, [map, onlineTiles]);

  const markers = useMemo(() => stopMarkers(plan), [plan]);
  useEffect(() => {
    if (!map) return;
    syncStopMarkers(map, stopMarks.current, markers, {
      palette,
      view,
      selectedId: selectedStopId,
      onSelect: (id) => handlers.current.onSelect(id),
      format: (n) => formatNumber(n, digits),
      label: (s) =>
        s.dropped
          ? tv("map.skippedLabel", { name: s.agentName })
          : `${tv("map.stopLabel", { van: formatNumber(s.vehicle ?? 0, digits), seq: formatNumber(s.seq ?? 0, digits), name: s.agentName })}. ${tv(s.health === "risk" ? "map.risk" : "map.ok")}`,
    });
  }, [map, markers, palette, view, selectedStopId, tv, digits]);

  // Centre the chosen stop (from the list or a marker), a little above the middle so the stop card
  // below it does not cover it. Only a new selection moves the camera, not a refetch of the plan.
  const markerById = useRef(new Map<number, StopMarker>());
  useEffect(() => {
    markerById.current = new Map(markers.map((s) => [s.id, s]));
  }, [markers]);
  useEffect(() => {
    const stop = selectedStopId === null ? undefined : markerById.current.get(selectedStopId);
    if (!map || !stop) return;
    map.easeTo({ center: [stop.lng, stop.lat], zoom: Math.max(map.getZoom(), FOCUS_ZOOM), offset: [0, -48], duration: reduced ? 0 : MS.slow * 2 });
  }, [map, selectedStopId, reduced]);

  const { lat, lng, name } = plan.depot;
  useEffect(() => {
    if (!map) return;
    depotMark.current = syncDepotMarker(map, depotMark.current, [lng, lat], tv("map.depotLabel", { name }));
  }, [map, lat, lng, name, tv]);

  // Frame the plan when it first appears and whenever a re-solve produces a new one. The plan object
  // changes on every refetch, so only a new plan id moves the camera.
  const bounds = useRef(planBounds(plan));
  useEffect(() => {
    bounds.current = planBounds(plan);
  }, [plan]);
  const planId = plan.id;
  useEffect(() => {
    if (map && planId > 0 && bounds.current) map.fitBounds(bounds.current, { padding: 56, maxZoom: 12, duration: reduced ? 0 : MS.reveal });
  }, [map, planId, reduced]);

  // Explicit request only ("Fit route"); the first value is skipped, the plan effect above frames it.
  const lastFit = useRef(fitSignal);
  useEffect(() => {
    if (lastFit.current === fitSignal) return;
    lastFit.current = fitSignal;
    if (map && bounds.current) map.fitBounds(bounds.current, { padding: 56, maxZoom: 12, duration: reduced ? 0 : MS.reveal });
  }, [map, fitSignal, reduced]);

  return (
    <div
      ref={ref}
      role="region"
      aria-label={label}
      data-testid="route-map"
      data-ready={map ? "true" : "false"}
      data-view={view}
      data-tiles={onlineTiles ? "online" : "offline"}
      style={onlineTiles ? STREET_VARS : undefined}
      className="absolute inset-0 overflow-hidden rounded-[var(--radius-card)] bg-(--map-water)"
    />
  );
}

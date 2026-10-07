// DOM markers for the van map: numbered stops (real buttons, so the keyboard and screen readers reach
// them) and the depot. DOM markers instead of symbol layers keep the map style glyph-free and offline.
import { Marker, type Map as MlMap } from "maplibre-gl";

import { routeColor } from "./routePalette";
import type { MapView, StopMarker } from "./vanRoutesModel";

const STOP_CLASS =
  "num grid cursor-pointer place-items-center rounded-full border-2 border-(--map-outline) text-xs font-bold text-(--route-ink) shadow-soft";
const DEPOT_CLASS = "grid size-9 place-items-center rounded-lg border-2 border-(--map-outline) bg-(--map-halo) text-(--map-outline) shadow-soft";
// lucide "warehouse", inline: static markup with no user text in it.
const DEPOT_SVG =
  '<svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 8.35V20a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V8.35A1 1 0 0 1 2.63 7.4l9-4.2a1 1 0 0 1 .74 0l9 4.2a1 1 0 0 1 .63.95Z"/><path d="M6 18h12"/><path d="M6 14h12"/><rect x="6" y="10" width="12" height="12"/></svg>';

export interface StopMarkerContext {
  palette: readonly string[];
  view: MapView;
  selectedId: number | null;
  label: (stop: StopMarker) => string;
  /** Numbers on the markers, in the user's digits. */
  format: (n: number) => string;
  onSelect: (stopId: number) => void;
}

// The fill stays the van colour (route identity); the ring carries the cash status. A stockout-risk stop
// also gets a "!" badge, so the status never rests on colour alone.
const HEALTH_RING = { risk: "var(--risk-act)", ok: "var(--risk-safe)" } as const;
const BADGE_CLASS =
  "pointer-events-none absolute -right-1.5 -top-1.5 grid size-3.5 place-items-center rounded-full border border-(--map-halo) bg-(--act-solid) text-[9px] font-bold leading-none text-white";

function paint(el: HTMLButtonElement, stop: StopMarker, ctx: StopMarkerContext): void {
  const selected = ctx.selectedId === stop.id;
  const numbered = ctx.view === "optimised" && !stop.dropped && stop.seq !== null;
  const color = routeColor(ctx.palette, stop.vehicle ?? 1);
  const small = ctx.view === "separate" && !stop.dropped;
  el.className = `${STOP_CLASS} ${small ? "size-4" : "size-7"}`;
  el.textContent = stop.dropped ? "×" : numbered && stop.seq !== null ? ctx.format(stop.seq) : "";
  if (stop.health === "risk") {
    // maplibre positions the marker element absolutely, so the badge anchors to it.
    const badge = document.createElement("span");
    badge.className = BADGE_CLASS;
    badge.setAttribute("aria-hidden", "true");
    badge.dataset.badge = "risk";
    badge.textContent = "!";
    el.appendChild(badge);
  }
  // A dropped stop is a hollow ring, a separate-trip stop a small neutral dot: never colour alone.
  el.style.background = stop.dropped ? "var(--map-halo)" : ctx.view === "separate" ? "var(--map-outline)" : color;
  if (stop.health) el.style.borderColor = HEALTH_RING[stop.health];
  else el.style.removeProperty("border-color");
  el.dataset.health = stop.health ?? "none";
  if (stop.dropped) el.style.color = "var(--map-outline)";
  else el.style.removeProperty("color");
  el.style.boxShadow = selected ? "0 0 0 3px var(--map-halo), 0 0 0 5px var(--map-selected)" : "";
  el.dataset.selected = selected ? "true" : "false";
  el.setAttribute("aria-label", ctx.label(stop));
  el.setAttribute("aria-pressed", String(selected));
  el.title = ctx.label(stop);
}

/** One marker per stop; existing markers are updated in place so keyboard focus survives a selection change. */
export function syncStopMarkers(map: MlMap, store: Map<number, Marker>, stops: readonly StopMarker[], ctx: StopMarkerContext): void {
  const keep = new Set<number>();
  for (const stop of stops) {
    keep.add(stop.id);
    let marker = store.get(stop.id);
    if (!marker) {
      const el = document.createElement("button");
      el.type = "button";
      el.setAttribute("data-testid", "route-stop-marker");
      el.dataset.stopId = String(stop.id);
      marker = new Marker({ element: el }).setLngLat([stop.lng, stop.lat]).addTo(map);
      store.set(stop.id, marker);
    }
    const el = marker.getElement() as HTMLButtonElement;
    el.onclick = () => ctx.onSelect(stop.id);
    marker.setLngLat([stop.lng, stop.lat]);
    paint(el, stop, ctx);
  }
  for (const [id, marker] of store) {
    if (!keep.has(id)) {
      marker.remove();
      store.delete(id);
    }
  }
}

export function syncDepotMarker(map: MlMap, current: Marker | null, lngLat: [number, number], label: string): Marker {
  const marker = current ?? new Marker({ element: depotElement() }).setLngLat(lngLat).addTo(map);
  marker.setLngLat(lngLat);
  const el = marker.getElement();
  el.setAttribute("aria-label", label);
  el.title = label;
  return marker;
}

function depotElement(): HTMLElement {
  const el = document.createElement("div");
  el.className = DEPOT_CLASS;
  el.setAttribute("role", "img");
  el.setAttribute("data-testid", "route-depot-marker");
  el.innerHTML = DEPOT_SVG;
  return el;
}

export function clearStopMarkers(store: Map<number, Marker>): void {
  for (const marker of store.values()) marker.remove();
  store.clear();
}

import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RouteMap, { type RouteMapProps } from "./RouteMap";
import { vanPlan } from "./testFixtures";

// A recording stand-in for maplibre-gl: jsdom has no WebGL, so the test checks what the component
// asks the map to draw (sources, layers, visibility, markers), not pixels.
const h = vi.hoisted(() => {
  class FakeSource {
    data: { features?: unknown[] } | null = null;
    setData(d: { features?: unknown[] }): void {
      this.data = d;
    }
  }
  class FakeMap {
    static last: FakeMap | null = null;
    static failNext = false;
    handlers = new Map<string, () => void>();
    sources = new Map<string, FakeSource>();
    layers: string[] = [];
    layout: Record<string, string> = {};
    paint: Record<string, unknown> = {};
    images = new Map<string, { sdf?: boolean }>();
    fits: unknown[] = [];
    eases: { center: number[]; zoom: number; duration: number }[] = [];
    removed = false;
    touchZoomRotate = { disableRotation: (): void => undefined };
    constructor() {
      if (FakeMap.failNext) {
        FakeMap.failNext = false;
        throw new Error("webgl");
      }
      FakeMap.last = this;
    }
    on(event: string, fn: () => void): this {
      this.handlers.set(event, fn);
      return this;
    }
    off(): this {
      return this;
    }
    addControl(): void {}
    addSource(id: string): void {
      this.sources.set(id, new FakeSource());
    }
    addLayer(layer: { id: string }): void {
      this.layers.push(layer.id);
    }
    getSource(id: string): FakeSource | undefined {
      return this.sources.get(id);
    }
    getLayer(): object {
      return {};
    }
    setLayoutProperty(id: string, _prop: string, value: string): void {
      this.layout[id] = value;
    }
    setPaintProperty(id: string, prop: string, value: unknown): void {
      this.paint[`${id}:${prop}`] = value;
    }
    hasImage(id: string): boolean {
      return this.images.has(id);
    }
    addImage(id: string, _img: unknown, opts: { sdf?: boolean } = {}): void {
      this.images.set(id, opts);
    }
    isStyleLoaded(): boolean {
      return true;
    }
    fitBounds(bounds: unknown): void {
      this.fits.push(bounds);
    }
    easeTo(opts: { center: number[]; zoom: number; duration: number }): void {
      this.eases.push(opts);
    }
    getZoom(): number {
      return 9;
    }
    resize(): void {}
    remove(): void {
      this.removed = true;
    }
    fire(event: string): void {
      this.handlers.get(event)?.();
    }
  }
  class FakeMarker {
    static all: FakeMarker[] = [];
    el: HTMLElement;
    lngLat: number[] = [];
    removed = false;
    constructor(opts: { element: HTMLElement }) {
      this.el = opts.element;
      FakeMarker.all.push(this);
    }
    setLngLat(p: number[]): this {
      this.lngLat = p;
      return this;
    }
    addTo(): this {
      return this;
    }
    getElement(): HTMLElement {
      return this.el;
    }
    remove(): void {
      this.removed = true;
    }
  }
  class FakeNavigation {}
  return { FakeMap, FakeMarker, FakeNavigation };
});

vi.mock("maplibre-gl", () => ({ Map: h.FakeMap, Marker: h.FakeMarker, NavigationControl: h.FakeNavigation }));

const props: RouteMapProps = { plan: vanPlan(), view: "optimised", selectedStopId: null, onSelect: () => undefined, onlineTiles: false, onFail: () => undefined, label: "Van routes map" };

function loaded(over: Partial<RouteMapProps> = {}) {
  const view = render(<RouteMap {...props} {...over} />);
  const map = h.FakeMap.last as InstanceType<typeof h.FakeMap>;
  act(() => map.fire("load"));
  return { map, ...view };
}

const stopButtons = () => h.FakeMarker.all.filter((m) => m.el.getAttribute("data-testid") === "route-stop-marker" && !m.removed);

describe("RouteMap", () => {
  beforeEach(() => {
    h.FakeMap.last = null;
    h.FakeMap.failNext = false;
    h.FakeMarker.all = [];
  });

  it("is a labelled region that is ready once the style has loaded", () => {
    const { map } = loaded();
    const region = screen.getByRole("region", { name: "Van routes map" });
    expect(region).toHaveAttribute("data-ready", "true");
    expect(map.layers).toEqual(["van-spoke", "van-route-casing", "van-route-line", "van-route-approx", "van-route-arrow"]);
  });

  it("draws direction chevrons from an SDF image so each leg shows its travel order", () => {
    const { map } = loaded();
    expect(map.images.get("van-arrow")).toEqual({ sdf: true, pixelRatio: 2 });
    expect(map.layout["van-route-arrow"]).toBe("visible");
  });

  it("keeps street tiles off by default and switches them on when asked", () => {
    const { map, rerender } = loaded();
    expect(map.layout["online-tiles"]).toBe("none");
    expect(screen.getByTestId("route-map")).toHaveAttribute("data-tiles", "offline");
    rerender(<RouteMap {...props} onlineTiles />);
    expect(map.layout["online-tiles"]).toBe("visible");
    // Light street tiles are opaque and the offline land is hidden; the route casing turns white.
    expect(map.paint["online-tiles:raster-opacity"]).toBe(1);
    expect(map.paint["bd-land:fill-opacity"]).toBe(0);
    expect(map.paint["van-route-casing:line-color"]).toBe("#ffffff");
    expect(screen.getByTestId("route-map")).toHaveAttribute("data-tiles", "online");
    rerender(<RouteMap {...props} onlineTiles={false} />);
    expect(map.paint["bd-land:fill-opacity"]).toBe(1);
  });

  it("feeds the route lines and the separate-trip spokes to the map", () => {
    const { map } = loaded();
    expect(map.getSource("van-routes")?.data?.features).toHaveLength(5);
    expect(map.getSource("van-spokes")?.data?.features).toHaveLength(3);
  });

  it("frames the plan once", () => {
    const { map, rerender } = loaded();
    expect(map.fits).toHaveLength(1);
    rerender(<RouteMap {...props} selectedStopId={1} />);
    expect(map.fits).toHaveLength(1);
    rerender(<RouteMap {...props} plan={vanPlan({ id: 8 })} />);
    expect(map.fits).toHaveLength(2);
  });

  it("places a numbered button for every stop and one depot marker", () => {
    loaded();
    const stops = stopButtons();
    expect(stops).toHaveLength(5);
    const first = stops.find((m) => m.el.dataset["stopId"] === "1");
    expect(first?.el.textContent).toBe("1");
    expect(first?.el.getAttribute("aria-label")).toBe("Van 1, stop 1: Rahim Telecom. Van arrives in time");
    expect(first?.lngLat).toEqual([90.41, 23.81]);
    // A stop the van does not serve is a hollow "×", not a number.
    const skipped = stops.find((m) => m.el.dataset["stopId"] === "4");
    expect(skipped?.el.textContent).toBe("×");
    expect(skipped?.el.getAttribute("aria-label")).toBe("Not served by van: Karim Pharmacy");
    const depot = h.FakeMarker.all.find((m) => m.el.getAttribute("data-testid") === "route-depot-marker");
    expect(depot?.lngLat).toEqual([90.4, 23.78]);
    expect(depot?.el.getAttribute("aria-label")).toBe("Dhaka depot (depot)");
  });

  it("reports a click on a stop and marks the selected one", () => {
    const onSelect = vi.fn();
    const { rerender } = loaded({ onSelect });
    fireEvent.click(stopButtons().find((m) => m.el.dataset["stopId"] === "2")?.el as HTMLElement);
    expect(onSelect).toHaveBeenCalledWith(2);
    rerender(<RouteMap {...props} onSelect={onSelect} selectedStopId={2} />);
    const marks = stopButtons();
    expect(marks.find((m) => m.el.dataset["stopId"] === "2")?.el.dataset["selected"]).toBe("true");
    expect(marks.find((m) => m.el.dataset["stopId"] === "1")?.el.dataset["selected"]).toBe("false");
  });

  it("rings each served stop by its cash status and badges a stockout risk", () => {
    loaded();
    const byId = (id: string) => stopButtons().find((m) => m.el.dataset["stopId"] === id)?.el as HTMLElement;
    // Stop 2 arrives after its deadline: red ring, "!" badge, and the status in its name.
    expect(byId("2").dataset["health"]).toBe("risk");
    expect(byId("2").style.borderColor).toBe("var(--risk-act)");
    expect(byId("2").querySelector("[data-badge='risk']")).not.toBeNull();
    expect(byId("2").getAttribute("aria-label")).toBe("Van 1, stop 2: Salma Store. Stockout likely before the van");
    expect(byId("1").dataset["health"]).toBe("ok");
    expect(byId("1").style.borderColor).toBe("var(--risk-safe)");
    expect(byId("1").querySelector("[data-badge]")).toBeNull();
    // A skipped stop keeps the neutral hollow ring.
    expect(byId("4").dataset["health"]).toBe("none");
    expect(byId("4").style.borderColor).toBe("");
  });

  it("pans once to a newly chosen stop", () => {
    const { map, rerender } = loaded();
    expect(map.eases).toHaveLength(0);
    rerender(<RouteMap {...props} selectedStopId={3} />);
    expect(map.eases).toHaveLength(1);
    expect(map.eases[0]?.center).toEqual([90.36, 23.72]);
    expect(map.eases[0]?.zoom).toBe(12);
    // A refetch of the same plan does not move the camera again.
    rerender(<RouteMap {...props} plan={vanPlan()} selectedStopId={3} />);
    expect(map.eases).toHaveLength(1);
    rerender(<RouteMap {...props} selectedStopId={null} />);
    expect(map.eases).toHaveLength(1);
  });

  it("switches between the optimised routes and the separate trips", () => {
    const { map, rerender } = loaded();
    expect(map.layout["van-route-line"]).toBe("visible");
    expect(map.layout["van-spoke"]).toBe("none");
    rerender(<RouteMap {...props} view="separate" />);
    expect(map.layout["van-route-line"]).toBe("none");
    expect(map.layout["van-route-casing"]).toBe("none");
    expect(map.layout["van-route-arrow"]).toBe("none");
    expect(map.layout["van-spoke"]).toBe("visible");
    // Separate trips carry no sequence numbers.
    expect(stopButtons().find((m) => m.el.dataset["stopId"] === "1")?.el.textContent).toBe("");
    expect(screen.getByTestId("route-map")).toHaveAttribute("data-view", "separate");
  });

  it("drops markers for stops that are no longer in the plan", () => {
    const { rerender } = loaded();
    const plan = vanPlan();
    rerender(<RouteMap {...props} plan={{ ...plan, id: 9, unrouted: [] }} />);
    expect(stopButtons()).toHaveLength(3);
  });

  it("tells the page when the map cannot start", () => {
    h.FakeMap.failNext = true;
    const onFail = vi.fn();
    render(<RouteMap {...props} onFail={onFail} />);
    expect(onFail).toHaveBeenCalledTimes(1);
  });

  it("removes the map and its markers on unmount", () => {
    const { map, unmount } = loaded();
    unmount();
    expect(map.removed).toBe(true);
    expect(h.FakeMarker.all.every((m) => m.removed)).toBe(true);
  });
});

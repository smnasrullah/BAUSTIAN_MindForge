import { Globe, Maximize2, Truck } from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useState, type ComponentType } from "react";
import { useTranslation } from "react-i18next";

import type { VanPlan } from "../../../api/vanPlans";
import { Skeleton } from "../../../components/ui/Skeleton";
import { ErrorState } from "../../../components/ui/StatePanel";
import { cn } from "../../../lib/cn";
import { formatDuration, formatMoney, formatNumber } from "../../../lib/format";
import { useLocale } from "../../../lib/prefs";
import { VAN_NS } from "../../../i18n/vanRoutes";
import { useControlRoomStore } from "../controlRoom/controlRoomStore";
import type { RouteMapProps } from "./RouteMap";
import { routeVar } from "./routePalette";
import { StopCard } from "./StopCard";
import { hasApproxLegs, stopMarkers, type MapView, type StopHealth } from "./vanRoutesModel";

/** If the map chunk cannot load (offline after a deploy), report it like a WebGL failure. */
function MapLoadFailed({ onFail }: RouteMapProps) {
  useEffect(() => onFail(), [onFail]);
  return null;
}

const RouteMap = lazy(
  (): Promise<{ default: ComponentType<RouteMapProps> }> => import("./RouteMap").catch(() => ({ default: MapLoadFailed })),
);

const OVERLAY = "glass rounded-[var(--radius-input)] border border-line px-3 py-2 text-xs text-fg shadow-soft";
// Same ring and badge as the map markers (routeMarkers.ts).
const HEALTH_RING: Record<StopHealth, string> = { risk: "var(--risk-act)", ok: "var(--risk-safe)" };

function HealthKey({ health }: { health: StopHealth }) {
  const { t: tv } = useTranslation(VAN_NS);
  return (
    <li className="flex items-center gap-2" data-testid={`legend-${health}`}>
      <span aria-hidden className="relative size-4 shrink-0 rounded-full border-2 bg-surface-2" style={{ borderColor: HEALTH_RING[health] }}>
        {health === "risk" ? (
          <span className="absolute -right-1.5 -top-1.5 grid size-3 place-items-center rounded-full bg-(--act-solid) text-[8px] font-bold leading-none text-white">!</span>
        ) : null}
      </span>
      <span>{tv(health === "risk" ? "map.risk" : "map.ok")}</span>
    </li>
  );
}

function Legend({ plan, view }: { plan: VanPlan; view: MapView }) {
  const { t: tv } = useTranslation(VAN_NS);
  const { lang, digits } = useLocale();
  const health = new Set(stopMarkers(plan).flatMap((s) => (s.health ? [s.health] : [])));
  return (
    <ul className={cn(OVERLAY, "space-y-1")} aria-label={tv("map.legend")} data-testid="route-legend">
      {view === "optimised" ? (
        plan.routes.map((r) => (
          <li key={r.id} className="flex items-center gap-2">
            <span aria-hidden className="h-1 w-5 shrink-0 rounded-full" style={{ background: routeVar(r.vehicle_no) }} />
            <Truck aria-hidden className="size-3.5" />
            <span className="font-semibold">{tv("map.route", { n: formatNumber(r.vehicle_no, digits) })}</span>
            <span className="num text-muted" data-testid="legend-route-summary">
              {tv("map.routeSummary", {
                km: formatNumber(r.km, digits, { fraction: 1 }),
                time: formatDuration(r.minutes / 60, lang, digits),
                cost: formatMoney(r.cost_bdt, digits, { lang }),
              })}
            </span>
          </li>
        ))
      ) : (
        <li className="flex items-center gap-2">
          <span aria-hidden className="w-5 shrink-0 border-t-2 border-dashed border-(--map-outline)" />
          <span className="font-semibold">{tv("map.spoke")}</span>
        </li>
      )}
      {view === "optimised" && hasApproxLegs(plan) ? (
        <li className="flex items-center gap-2" data-testid="legend-approx">
          <span aria-hidden className="w-5 shrink-0 border-t-2 border-dashed border-(--map-outline)" />
          <span>{tv("map.approx")}</span>
        </li>
      ) : null}
      {health.has("risk") ? <HealthKey health="risk" /> : null}
      {health.has("ok") ? <HealthKey health="ok" /> : null}
      {plan.unrouted.length > 0 ? (
        <li className="flex items-center gap-2">
          <span aria-hidden className="num grid size-4 shrink-0 place-items-center rounded-full border-2 border-(--map-outline) bg-(--map-halo) text-[10px] font-bold">
            ×
          </span>
          <span>{tv("map.skipped")}</span>
        </li>
      ) : null}
    </ul>
  );
}

interface RouteMapPaneProps {
  plan: VanPlan | undefined;
  status: "pending" | "error" | "ready";
  onRetry: () => void;
  retrying: boolean;
  view: MapView;
  selectedStopId: number | null;
  onSelect: (stopId: number) => void;
  /** Close the stop card (clears the selection). */
  onClear: () => void;
  /** A re-solve is running: the old plan stays on the map, dimmed. */
  busy: boolean;
  className?: string;
}

/** The map frame: lazy MapLibre map, legend, and the skeleton / error / failed-WebGL states. */
export function RouteMapPane({ plan, status, onRetry, retrying, view, selectedStopId, onSelect, onClear, busy, className }: RouteMapPaneProps) {
  const { t } = useTranslation();
  const { t: tv } = useTranslation(VAN_NS);
  const { digits } = useLocale();
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [fitSignal, setFitSignal] = useState(0);
  const onFail = useCallback(() => setFailed(true), []);
  // One persisted choice for both distributor maps: street tiles need internet, so they stay opt-in.
  const onlineTiles = useControlRoomStore((s) => s.onlineTiles);
  const setOnlineTiles = useControlRoomStore((s) => s.setOnlineTiles);
  const served = plan ? plan.routes.reduce((n, r) => n + r.stops.length, 0) : 0;
  const summary = plan
    ? tv("map.label", {
        vans: formatNumber(plan.routes.length, digits),
        stops: formatNumber(served, digits),
        skipped: formatNumber(plan.unrouted.length, digits),
      })
    : tv("title");

  return (
    <section
      aria-label={tv("title")}
      aria-busy={busy}
      className={cn("relative isolate min-h-[360px] overflow-hidden rounded-[var(--radius-card)] border border-line bg-(--map-water) shadow-soft", className)}
      data-testid="route-map-pane"
    >
      {failed ? (
        <div className="absolute inset-0 grid place-items-center p-6">
          <ErrorState
            compact
            title={t("controlRoom.map.failTitle")}
            body={t("controlRoom.map.failBody")}
            onRetry={() => {
              setFailed(false);
              setAttempt((n) => n + 1);
            }}
          />
        </div>
      ) : plan ? (
        <Suspense fallback={<Skeleton className="absolute inset-0 rounded-none" />}>
          <RouteMap
            key={attempt}
            plan={plan}
            view={view}
            selectedStopId={selectedStopId}
            onSelect={onSelect}
            onlineTiles={onlineTiles}
            onFail={onFail}
            label={summary}
            fitSignal={fitSignal}
          />
        </Suspense>
      ) : null}

      {plan ? (
        <div className="pointer-events-none absolute left-3 top-3 z-10 flex max-w-[calc(100%-4.5rem)] flex-col items-start gap-2 [&>*]:pointer-events-auto">
          <Legend plan={plan} view={view} />
          {failed ? null : (
            <button
              type="button"
              onClick={() => setFitSignal((n) => n + 1)}
              data-testid="route-fit"
              className={cn(OVERLAY, "inline-flex min-h-11 items-center gap-2 font-semibold")}
            >
              <Maximize2 aria-hidden className="size-4" />
              {tv("map.fit")}
            </button>
          )}
          {failed ? null : (
            <button
              type="button"
              aria-pressed={onlineTiles}
              onClick={() => setOnlineTiles(!onlineTiles)}
              data-testid="route-tiles-toggle"
              className={cn(OVERLAY, "inline-flex min-h-11 items-center gap-2 font-semibold", onlineTiles && "ring-1 ring-pulse")}
              title={t("controlRoom.map.tilesHint")}
            >
              <Globe aria-hidden className="size-4" />
              {t(onlineTiles ? "controlRoom.map.tilesOn" : "controlRoom.map.tilesOff")}
            </button>
          )}
        </div>
      ) : null}

      {plan && !failed ? (
        <div className="pointer-events-none absolute inset-x-3 bottom-8 z-10 flex [&>*]:pointer-events-auto">
          <StopCard plan={plan} stopId={selectedStopId} onClose={onClear} />
        </div>
      ) : null}

      {busy ? <div aria-hidden className="absolute inset-0 z-10 bg-bg/40" data-testid="route-map-busy" /> : null}
      {status === "pending" ? <Skeleton className="absolute inset-0 z-10 rounded-none" /> : null}
      {status === "error" ? (
        <div className="absolute inset-0 z-20 grid place-items-center bg-bg/70 p-6 backdrop-blur-sm">
          <ErrorState compact onRetry={onRetry} retrying={retrying} />
        </div>
      ) : null}
    </section>
  );
}

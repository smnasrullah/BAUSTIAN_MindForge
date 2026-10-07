import { Truck, Undo2, Warehouse } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { VanPlan, VanRoute } from "../../../api/vanPlans";
import { formatDuration, formatMoney, formatNumber } from "../../../lib/format";
import { useLocale } from "../../../lib/prefs";
import { VAN_NS } from "../../../i18n/vanRoutes";
import { itinerary, type ItineraryLeg } from "./itinerary";
import { routeVar } from "./routePalette";
import { StopRow } from "./StopRow";

/** The drive between two steps: a bar in the van colour, then distance and time from the stored leg. */
function LegConnector({ leg, vehicle }: { leg: ItineraryLeg | null; vehicle: number }) {
  const { t: tv } = useTranslation(VAN_NS);
  const { lang, digits } = useLocale();
  const values = leg ? { km: formatNumber(leg.km, digits, { fraction: 1 }), time: formatDuration(leg.minutes / 60, lang, digits) } : null;
  return (
    <li className="flex items-center gap-3 pl-[1.375rem]" data-testid="van-leg" data-km={leg?.km ?? ""}>
      <span aria-hidden className="h-6 w-1 shrink-0 rounded-full" style={{ background: routeVar(vehicle) }} />
      <span className="num text-xs text-muted">
        {values ? tv(leg?.source === "estimate" ? "itinerary.legEstimate" : "itinerary.leg", values) : tv("itinerary.legMissing")}
      </span>
    </li>
  );
}

function DepotStep({ name, kind, cumKm }: { name: string; kind: "start" | "return"; cumKm?: number }) {
  const { t: tv } = useTranslation(VAN_NS);
  const { digits } = useLocale();
  const Icon = kind === "start" ? Warehouse : Undo2;
  return (
    <li className="flex items-center gap-3 rounded-2xl border border-dashed border-line px-3 py-2" data-testid={`van-${kind}`}>
      <span aria-hidden className="grid size-7 shrink-0 place-items-center rounded-lg border-2 border-(--map-outline) bg-(--map-halo) text-(--map-outline)">
        <Icon className="size-4" />
      </span>
      <span className="min-w-0 flex-1 text-small font-semibold">{tv(kind === "start" ? "itinerary.start" : "itinerary.back", { name })}</span>
      {cumKm !== undefined ? (
        <span className="num text-xs text-muted">{tv("itinerary.total", { km: formatNumber(cumKm, digits, { fraction: 1 }) })}</span>
      ) : null}
    </li>
  );
}

interface RouteItineraryProps {
  plan: VanPlan;
  route: VanRoute;
  selectedStopId: number | null;
  onSelect: (stopId: number) => void;
}

/** One van, turn by turn: depot, each stop with the drive that reaches it, and the drive back. */
export function RouteItinerary({ plan, route, selectedStopId, onSelect }: RouteItineraryProps) {
  const { t: tv } = useTranslation(VAN_NS);
  const { lang, digits } = useLocale();
  const steps = itinerary(route);
  return (
    <section aria-labelledby={`van-${route.id}`} data-testid="van-route" data-vehicle={route.vehicle_no} className="space-y-2">
      <h3 id={`van-${route.id}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-small font-semibold">
        <span className="inline-flex items-center gap-2">
          <span aria-hidden className="h-1 w-5 rounded-full" style={{ background: routeVar(route.vehicle_no) }} />
          <Truck aria-hidden className="size-4" />
          {tv("stops.van", { n: formatNumber(route.vehicle_no, digits) })}
        </span>
        <span className="num text-xs font-normal text-muted">
          {tv("stops.vanMeta", {
            km: formatNumber(route.km, digits, { fraction: 1 }),
            time: formatDuration(route.minutes / 60, lang, digits),
            load: formatMoney(route.cash_load_bdt, digits, { compact: true, lang }),
          })}
        </span>
        <span className="num text-xs font-normal text-muted" data-testid="van-route-cost">
          {tv("itinerary.cost", { cost: formatMoney(route.cost_bdt, digits) })}
        </span>
      </h3>
      <ol className="space-y-1" aria-label={tv("itinerary.label", { n: formatNumber(route.vehicle_no, digits) })}>
        {steps.map((step) =>
          step.kind === "depot" ? (
            <DepotStep key="start" name={plan.depot.name} kind="start" />
          ) : step.kind === "stop" ? (
            [
              <LegConnector key={`leg-${step.stop.id}`} leg={step.leg} vehicle={route.vehicle_no} />,
              <StopRow
                key={step.stop.id}
                stop={step.stop}
                vehicle={route.vehicle_no}
                selected={selectedStopId === step.stop.id}
                onSelect={() => onSelect(step.stop.id)}
              />,
            ]
          ) : (
            [
              <LegConnector key="leg-return" leg={step.leg} vehicle={route.vehicle_no} />,
              <DepotStep key="return" name={plan.depot.name} kind="return" cumKm={route.km} />,
            ]
          ),
        )}
      </ol>
    </section>
  );
}

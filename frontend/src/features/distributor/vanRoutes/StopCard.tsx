import { ArrowRight, Clock, Route, X } from "lucide-react";
import { motion } from "motion/react";
import { useTranslation } from "react-i18next";

import type { VanPlan } from "../../../api/vanPlans";
import { MoneyText } from "../../../components/ui/MoneyText";
import { RISK_STYLE } from "../../../components/ui/risk";
import { TimeText } from "../../../components/ui/TimeText";
import { cn } from "../../../lib/cn";
import { formatDuration, formatMoney, formatNumber } from "../../../lib/format";
import { useReducedMotionPref } from "../../../lib/motionPrefs";
import { useLocale } from "../../../lib/prefs";
import { fadeOnly, fadeRise } from "../../../styles/motion";
import { VAN_NS } from "../../../i18n/vanRoutes";
import { stopTrip } from "./itinerary";
import { routeVar } from "./routePalette";
import { findStop, stopHealth } from "./vanRoutesModel";

interface StopCardProps {
  plan: VanPlan;
  stopId: number | null;
  onClose: () => void;
}

const ROW = "flex items-baseline justify-between gap-3 border-t border-line py-1.5";

/**
 * The chosen stop over the map: van and sequence number, the delivery instruction, ETA, cash to bring,
 * the drive in and where the van goes next, deadline and cash status.
 */
export function StopCard({ plan, stopId, onClose }: StopCardProps) {
  const { t: tv } = useTranslation(VAN_NS);
  const { lang, digits } = useLocale();
  const reduced = useReducedMotionPref();
  const found = findStop(plan, stopId);
  if (!found) return null;

  const { stop, vehicle } = found;
  const health = stopHealth(stop);
  const risk = health ? RISK_STYLE[health === "risk" ? "red" : "green"] : null;
  const RiskIcon = risk?.icon;
  const served = vehicle !== null && stop.seq !== null;
  const trip = served ? stopTrip(plan, stop.id) : null;

  return (
    <motion.section
      key={stop.id}
      variants={reduced ? fadeOnly : fadeRise}
      initial="hidden"
      animate="show"
      aria-label={tv("card.label")}
      aria-live="polite"
      data-testid="stop-card"
      data-stop-id={stop.id}
      data-health={health ?? "none"}
      className="glass w-full rounded-[var(--radius-card)] border border-line p-3 text-small text-fg shadow-soft sm:w-80"
    >
      <div className="flex items-start gap-2">
        <span
          aria-hidden
          className={cn(
            "num mt-0.5 grid size-7 shrink-0 place-items-center rounded-full border-2 border-(--map-outline) text-xs font-bold",
            served ? "text-(--route-ink)" : "bg-surface text-fg",
          )}
          style={served ? { background: routeVar(vehicle) } : undefined}
        >
          {served ? formatNumber(stop.seq ?? 0, digits) : "×"}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold text-muted" data-testid="stop-card-seq">
            {served ? tv("card.stop", { van: formatNumber(vehicle, digits), seq: formatNumber(stop.seq ?? 0, digits) }) : tv("card.skipped")}
          </p>
          <p className="truncate font-semibold">{stop.agent_name}</p>
          <p className="num text-xs text-muted">{stop.agent_code}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={tv("card.close")}
          data-testid="stop-card-close"
          className="-m-1 grid size-11 shrink-0 place-items-center rounded-full text-muted hover:bg-surface-2 hover:text-fg"
        >
          <X aria-hidden className="size-4" />
        </button>
      </div>

      {served ? (
        <p className="mt-2 rounded-xl bg-surface-2 px-2.5 py-1.5 text-xs font-semibold" data-testid="stop-card-instruction">
          {tv("card.instruction", { amount: formatMoney(stop.amount_bdt, digits, { lang }), name: stop.agent_name })}
        </p>
      ) : null}

      <dl className="mt-2">
        <div className={ROW}>
          <dt className="inline-flex items-center gap-1 text-muted">
            <Clock aria-hidden className="size-3.5" />
            {tv("card.eta")}
          </dt>
          <dd className="num font-semibold" data-testid="stop-card-eta">
            {served && stop.eta_lo ? (
              <>
                <TimeText at={stop.eta_lo} />
                {stop.eta_hi && stop.eta_hi !== stop.eta_lo ? (
                  <>
                    {"–"}
                    <TimeText at={stop.eta_hi} />
                  </>
                ) : null}
              </>
            ) : (
              tv("card.noEta")
            )}
          </dd>
        </div>
        <div className={ROW}>
          <dt className="text-muted">{tv("card.bring")}</dt>
          <dd data-testid="stop-card-amount">
            <MoneyText value={stop.amount_bdt} className="font-semibold" />
          </dd>
        </div>
        {trip ? (
          <div className={ROW} data-testid="stop-card-leg">
            <dt className="inline-flex items-center gap-1 text-muted">
              <Route aria-hidden className="size-3.5" />
              {tv(trip.fromDepot ? "card.fromDepot" : "card.fromPrev")}
            </dt>
            <dd className="num font-semibold">
              {trip.leg
                ? tv(trip.leg.source === "estimate" ? "itinerary.legEstimate" : "itinerary.leg", { km: formatNumber(trip.leg.km, digits, { fraction: 1 }), time: formatDuration(trip.leg.minutes / 60, lang, digits) })
                : tv("itinerary.legMissing")}
            </dd>
          </div>
        ) : null}
        {trip ? (
          <div className={ROW} data-testid="stop-card-next">
            <dt className="inline-flex items-center gap-1 text-muted">
              <ArrowRight aria-hidden className="size-3.5" />
              {tv("card.next")}
            </dt>
            <dd className="min-w-0 truncate font-semibold">
              {trip.next === "depot"
                ? tv("itinerary.back", { name: plan.depot.name })
                : tv("card.nextStop", { seq: formatNumber(trip.next.seq ?? 0, digits), name: trip.next.agent_name })}
            </dd>
          </div>
        ) : null}
        {stop.deadline ? (
          <div className={ROW}>
            <dt className="text-muted">{tv("card.deadline")}</dt>
            <dd className="num">
              <TimeText at={stop.deadline} />
            </dd>
          </div>
        ) : null}
      </dl>

      {risk && RiskIcon ? (
        <p className={cn("mt-2 flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold", risk.bg, risk.fg)} data-testid="stop-card-health">
          <RiskIcon aria-hidden className="size-3.5" />
          {tv(health === "risk" ? "map.risk" : "map.ok")}
        </p>
      ) : stop.reason ? (
        <p className="mt-2 text-xs text-muted">{tv(`stops.reason.${stop.reason}`)}</p>
      ) : null}
    </motion.section>
  );
}

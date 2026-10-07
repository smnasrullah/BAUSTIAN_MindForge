import { CircleCheck, Clock, Lock, MapPin, Scale, TriangleAlert, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { VanStop } from "../../../api/vanPlans";
import { MoneyText } from "../../../components/ui/MoneyText";
import { TimeText } from "../../../components/ui/TimeText";
import { cn } from "../../../lib/cn";
import { formatDuration, formatMoney, formatNumber, formatPercent } from "../../../lib/format";
import { useLocale } from "../../../lib/prefs";
import { VAN_NS } from "../../../i18n/vanRoutes";
import { routeVar } from "./routePalette";

function Eta({ stop }: { stop: VanStop }) {
  if (!stop.eta_lo) return null;
  const range = stop.eta_hi && stop.eta_hi !== stop.eta_lo;
  return (
    <span className="num">
      <TimeText at={stop.eta_lo} />
      {range && stop.eta_hi ? (
        <>
          {"–"}
          <TimeText at={stop.eta_hi} />
        </>
      ) : null}
    </span>
  );
}

function Chip({ tone, icon: Icon, children }: { tone: "safe" | "act" | "plain"; icon: LucideIcon; children: ReactNode }) {
  const style = tone === "safe" ? "bg-safe/12 text-safe-fg" : tone === "act" ? "bg-act/12 text-act-fg" : "bg-surface-2 text-muted";
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold", style)}>
      <Icon aria-hidden className="size-3.5" />
      {children}
    </span>
  );
}

export function StopRow({ stop, vehicle, selected, onSelect }: { stop: VanStop; vehicle: number | null; selected: boolean; onSelect: () => void }) {
  const { t: tv } = useTranslation(VAN_NS);
  const { lang, digits } = useLocale();
  const dropped = stop.status === "dropped";
  const late = stop.late_h ?? 0;
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        data-testid="van-stop"
        data-stop-id={stop.id}
        data-status={stop.status}
        title={tv("stops.open")}
        className={cn(
          "flex w-full min-h-11 items-start gap-3 rounded-2xl border p-3 text-left transition-colors hover:bg-surface-2",
          selected ? "border-pulse bg-surface-2 ring-2 ring-pulse/30" : "border-line bg-surface",
        )}
      >
        <span
          aria-hidden
          className={cn(
            "num mt-0.5 grid size-7 shrink-0 place-items-center rounded-full border-2 border-(--map-outline) text-xs font-bold",
            dropped ? "bg-surface text-fg" : "text-(--route-ink)",
          )}
          style={dropped ? undefined : { background: routeVar(vehicle ?? 1) }}
        >
          {dropped ? "×" : formatNumber(stop.seq ?? 0, digits)}
        </span>
        <span className="min-w-0 flex-1 space-y-1">
          <span className="flex flex-wrap items-baseline justify-between gap-x-3">
            <span className="min-w-0 truncate font-semibold">{stop.agent_name}</span>
            <span className="num text-xs text-muted">{stop.agent_code}</span>
          </span>
          <span className="flex flex-wrap items-center gap-x-4 gap-y-1 text-small">
            <span>
              <span className="text-muted">{tv("stops.amount")} </span>
              <MoneyText value={stop.amount_bdt} compact className="font-semibold" />
            </span>
            {!dropped && stop.eta_lo ? (
              <span className="inline-flex items-center gap-1">
                <Clock aria-hidden className="size-3.5 text-muted" />
                <span className="text-muted">{tv("stops.arrives")} </span>
                <Eta stop={stop} />
              </span>
            ) : null}
            {stop.deadline ? (
              <span className="inline-flex items-center gap-1">
                <span className="text-muted">{tv("stops.deadline")} </span>
                <TimeText at={stop.deadline} />
              </span>
            ) : null}
          </span>
          {dropped && stop.reason ? (
            <span className="block text-small text-muted" data-testid="drop-reason" data-reason={stop.reason}>
              {tv(`stops.reason.${stop.reason}`)}
            </span>
          ) : null}
          {stop.pin && stop.pin !== "exclude" ? (
            <span className="flex" data-testid="stop-pin" data-pin={stop.pin}>
              <Chip tone="plain" icon={Lock}>
                {tv(`stops.pin.${stop.pin}`)}
              </Chip>
            </span>
          ) : null}
          {dropped && stop.reason ? null : (
            <span className="flex flex-wrap items-center gap-1.5">
              {late > 0 ? (
                <Chip tone="act" icon={TriangleAlert}>
                  {tv("stops.late", { hours: formatDuration(late, lang, digits) })}
                </Chip>
              ) : (
                <Chip tone="safe" icon={CircleCheck}>
                  {tv("stops.onTime")}
                </Chip>
              )}
              {stop.penalty_bdt > 0 ? (
                <span className="num text-xs text-muted">
                  {tv("stops.penalty", { amount: formatMoney(stop.penalty_bdt, digits, { compact: true, lang }) })}
                </span>
              ) : null}
              {stop.stockout_before_arrival_p !== null ? (
                <span className="num text-xs text-muted">{tv("stops.stockoutP", { pct: formatPercent(stop.stockout_before_arrival_p, digits) })}</span>
              ) : null}
              {stop.stockout_risk_flag ? (
                <span data-testid="stop-at-risk">
                  <Chip tone="act" icon={TriangleAlert}>
                    {tv("stops.atRisk")}
                  </Chip>
                </span>
              ) : null}
              {stop.fairness_forced ? (
                <Chip tone="plain" icon={Scale}>
                  {tv("stops.fairness")}
                </Chip>
              ) : null}
              {stop.status === "delivered" ? (
                <Chip tone="safe" icon={MapPin}>
                  {tv("stops.delivered")}
                </Chip>
              ) : null}
            </span>
          )}
        </span>
      </button>
    </li>
  );
}

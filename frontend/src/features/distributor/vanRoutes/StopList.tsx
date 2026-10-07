import { TrendingDown, TrendingUp } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { VanPlan } from "../../../api/vanPlans";
import { cn } from "../../../lib/cn";
import { formatMoney, formatNumber } from "../../../lib/format";
import { useLocale } from "../../../lib/prefs";
import { VAN_NS } from "../../../i18n/vanRoutes";
import { RouteItinerary } from "./RouteItinerary";
import { StopRow } from "./StopRow";
import { savingsHeadline } from "./vanRoutesModel";

interface StopListProps {
  plan: VanPlan;
  selectedStopId: number | null;
  onSelect: (stopId: number) => void;
}

/** What this order saves against one trip per agent, from the same numbers as the savings panel. */
function SavingsStrip({ plan }: { plan: VanPlan }) {
  const { t: tv } = useTranslation(VAN_NS);
  const { lang, digits } = useLocale();
  const head = savingsHeadline(plan);
  const better = head.kmSaved >= 0 && head.bdtSaved >= 0;
  const Icon = better ? TrendingDown : TrendingUp;
  const values = {
    km: formatNumber(Math.abs(head.kmSaved), digits, { fraction: 1 }),
    bdt: formatMoney(Math.abs(head.bdtSaved), digits, { compact: true, lang }),
  };
  const km = head.kmSaved >= 0 ? "itinerary.kmLess" : "itinerary.kmMore";
  const money = head.bdtSaved >= 0 ? "itinerary.bdtLess" : "itinerary.bdtMore";
  return (
    <p
      className={cn("flex items-start gap-2 rounded-2xl px-3 py-2 text-small font-semibold", better ? "bg-safe/12 text-safe-fg" : "bg-act/12 text-act-fg")}
      data-testid="itinerary-savings"
      data-better={better ? "true" : "false"}
    >
      <Icon aria-hidden className="mt-0.5 size-4 shrink-0" />
      <span>
        {tv(km, values)} {tv(money, values)}
      </span>
    </p>
  );
}

/** Every van turn by turn (depot, stops with ETA, cash and the drive between them, back), then the skipped agents with why. */
export function StopList({ plan, selectedStopId, onSelect }: StopListProps) {
  const { t: tv } = useTranslation(VAN_NS);
  return (
    <div className="space-y-5" data-testid="stop-list">
      {plan.routes.length > 0 ? <SavingsStrip plan={plan} /> : null}
      {plan.routes.map((r) => (
        <RouteItinerary key={r.id} plan={plan} route={r} selectedStopId={selectedStopId} onSelect={onSelect} />
      ))}
      {plan.unrouted.length > 0 ? (
        <section aria-labelledby="van-skipped" className="space-y-2" data-testid="van-skipped">
          <div>
            <h3 id="van-skipped" className="text-small font-semibold">
              {tv("stops.skippedTitle")}
            </h3>
            <p className="text-xs text-muted">{tv("stops.skippedLead")}</p>
          </div>
          <ul className="space-y-2">
            {plan.unrouted.map((s) => (
              <StopRow key={s.id} stop={s} vehicle={null} selected={selectedStopId === s.id} onSelect={() => onSelect(s.id)} />
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

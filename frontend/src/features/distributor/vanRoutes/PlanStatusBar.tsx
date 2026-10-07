import { CircleCheck, CircleX, Clock, Layers, Route, ShieldCheck, type LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { PlanStatus, VanPlan } from "../../../api/vanPlans";
import { LangText } from "../../../components/ui/LangText";
import { TimeText } from "../../../components/ui/TimeText";
import { cn } from "../../../lib/cn";
import { formatNumber } from "../../../lib/format";
import { useLocale } from "../../../lib/prefs";
import { VAN_NS } from "../../../i18n/vanRoutes";

const STATUS: Record<PlanStatus, { icon: LucideIcon; tone: string }> = {
  pending: { icon: Clock, tone: "bg-watch/15 text-fg" },
  approved: { icon: CircleCheck, tone: "bg-safe/12 text-safe-fg" },
  rejected: { icon: CircleX, tone: "bg-act/12 text-act-fg" },
  superseded: { icon: Layers, tone: "bg-surface-2 text-muted" },
};

const CHIP = "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold";

/** Pending / approved / rejected / superseded: colour + icon + word. */
export function PlanStatusChip({ status, testId = "plan-status" }: { status: PlanStatus; testId?: string }) {
  const { t: tv } = useTranslation(VAN_NS);
  const { icon: Icon, tone } = STATUS[status];
  return (
    <span className={cn(CHIP, tone)} data-testid={testId} data-status={status}>
      <Icon aria-hidden className="size-3.5" />
      {tv(`status.${status}`)}
    </span>
  );
}

/** Status, where the distances came from, how it was solved, and the advisory notice. */
export function PlanStatusBar({ plan }: { plan: VanPlan }) {
  const { t: tv } = useTranslation(VAN_NS);
  const { digits } = useLocale();

  return (
    <div className="space-y-2" data-testid="plan-status-bar" data-status={plan.status} data-distance-source={plan.distance_source}>
      <div className="flex flex-wrap items-center gap-2">
        <PlanStatusChip status={plan.status} />
        <span className={cn(CHIP, "bg-surface-2 text-muted")} data-testid="plan-distance-source">
          <Route aria-hidden className="size-3.5" />
          {tv(`meta.${plan.distance_source}`)}
        </span>
        <span className="num text-xs text-muted">
          {tv("meta.solver", { name: plan.solver })} · {tv("meta.solved", { ms: formatNumber(plan.solve_ms, digits) })} ·{" "}
          {tv("meta.horizon", { hours: formatNumber(plan.horizon_h, digits) })}
        </span>
        <span className="text-xs text-muted">
          {tv("meta.planned", { when: "" })}
          <TimeText at={plan.planned_at} mode="datetime" />
          {plan.model_version ? <span className="num"> · {plan.model_version}</span> : null}
        </span>
      </div>
      {plan.decided_at ? (
        <p className="text-small" data-testid="plan-decision">
          {tv("decidedAt", { when: "" })}
          <TimeText at={plan.decided_at} mode="datetime" />
          {plan.note ? (
            <>
              {" · "}
              {tv("decidedNote", { note: "" })}
              <LangText text={plan.note} />
            </>
          ) : null}
        </p>
      ) : null}
      <p className="flex items-center gap-1.5 text-xs text-muted">
        <ShieldCheck aria-hidden className="size-3.5" />
        {tv("notice")}
      </p>
    </div>
  );
}

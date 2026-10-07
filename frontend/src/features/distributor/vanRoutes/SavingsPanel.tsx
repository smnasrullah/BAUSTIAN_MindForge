import { ArrowDownRight, ArrowUpRight, Equal, TriangleAlert } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { VanPlan } from "../../../api/vanPlans";
import { SourceChip } from "../../../components/ui/SourceChip";
import { cn } from "../../../lib/cn";
import { formatDuration, formatMoney, formatNumber, formatPercent } from "../../../lib/format";
import { useLocale } from "../../../lib/prefs";
import { VAN_NS } from "../../../i18n/vanRoutes";
import { PlanStatusChip } from "./PlanStatusBar";
import { lateHours, savingsHeadline, savingsRows, type SavingsRow } from "./vanRoutesModel";

/** Below this the change is rounding noise, shown as "no change". */
const EPS = 0.05;

function useAmount() {
  const { digits, lang } = useLocale();
  return (unit: SavingsRow["unit"], value: number): string =>
    unit === "bdt" ? formatMoney(value, digits, { compact: true, lang }) : formatNumber(value, digits, { fraction: unit === "km" ? 1 : 0 });
}

function Change({ row }: { row: SavingsRow }) {
  const { t: tv } = useTranslation(VAN_NS);
  const amount = useAmount();
  if (Math.abs(row.delta) < EPS) {
    return (
      <span className="inline-flex items-center gap-1 text-muted">
        <Equal aria-hidden className="size-3.5" />
        {tv("savings.same")}
      </span>
    );
  }
  const better = row.delta < 0;
  const Icon = better ? ArrowDownRight : ArrowUpRight;
  return (
    <span className={cn("inline-flex items-center gap-1 font-semibold", better ? "text-safe-fg" : "text-act-fg")} data-better={better}>
      <Icon aria-hidden className="size-3.5" />
      {tv(better ? "savings.less" : "savings.more", { value: amount(row.unit, Math.abs(row.delta)) })}
    </span>
  );
}

function Headline({ testId, label, value, shareText, better }: { testId: string; label: string; value: string; shareText: string; better: boolean }) {
  const Icon = better ? ArrowDownRight : ArrowUpRight;
  return (
    <div className="rounded-2xl bg-surface-2 p-3" data-testid={testId} data-better={better}>
      <p className="text-xs font-semibold text-muted">{label}</p>
      <p className="num font-display text-h3 font-bold">{value}</p>
      <p className={cn("inline-flex items-center gap-1 text-xs font-semibold", better ? "text-safe-fg" : "text-act-fg")}>
        <Icon aria-hidden className="size-3.5" />
        {shareText}
      </p>
    </div>
  );
}

/** This plan against one separate van trip per agent. If the total is worse, it says so. */
export function SavingsPanel({ plan }: { plan: VanPlan }) {
  const { t: tv } = useTranslation(VAN_NS);
  const { lang, digits } = useLocale();
  const amount = useAmount();
  const rows = savingsRows(plan);
  const total = rows.find((r) => r.key === "totalBdt");
  const late = lateHours(plan);
  const head = savingsHeadline(plan);
  const kmBetter = head.kmSaved >= 0;
  const bdtBetter = head.bdtSaved >= 0;
  const share = (better: boolean, ratio: number) =>
    tv(better ? "savings.shareLess" : "savings.shareMore", { pct: formatPercent(Math.abs(ratio), digits) });

  return (
    <section aria-labelledby="savings-title" className="ap-card space-y-3 p-4" data-testid="savings-panel">
      <div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="savings-title" className="font-display text-h3 font-bold">
            {tv("savings.title")}
          </h2>
          <SourceChip source="rule" />
        </div>
        <p className="text-small text-muted">{tv("savings.lead")}</p>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Headline
          testId="savings-head-km"
          label={tv(kmBetter ? "savings.kmSaved" : "savings.kmExtra")}
          value={tv("savings.kmValue", { km: formatNumber(Math.abs(head.kmSaved), digits, { fraction: 1 }) })}
          shareText={share(kmBetter, head.kmShare)}
          better={kmBetter}
        />
        <Headline
          testId="savings-head-bdt"
          label={tv(bdtBetter ? "savings.bdtSaved" : "savings.bdtExtra")}
          value={formatMoney(Math.abs(head.bdtSaved), digits, { compact: true, lang })}
          shareText={share(bdtBetter, head.bdtShare)}
          better={bdtBetter}
        />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 text-small" data-testid="savings-approval">
        <span className="text-muted">{tv("savings.approval")}</span>
        <PlanStatusChip status={plan.status} testId="savings-status" />
      </div>

      <table className="w-full text-small">
        <thead>
          <tr className="text-left text-xs uppercase text-muted">
            <th scope="col" className="py-1 pr-2 font-semibold">
              <span className="sr-only">{tv("savings.title")}</span>
            </th>
            <th scope="col" className="py-1 pr-2 text-right font-semibold">
              {tv("savings.before")}
            </th>
            <th scope="col" className="py-1 pr-2 text-right font-semibold">
              {tv("savings.after")}
            </th>
            <th scope="col" className="py-1 text-right font-semibold">
              {tv("savings.change")}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="border-t border-line" data-testid={`savings-${r.key}`}>
              <th scope="row" className="py-2 pr-2 text-left font-medium">
                {tv(`savings.${r.key}`)}
              </th>
              <td className="num py-2 pr-2 text-right text-muted">{amount(r.unit, r.before)}</td>
              <td className="num py-2 pr-2 text-right font-semibold">{amount(r.unit, r.after)}</td>
              <td className="py-2 text-right">
                <Change row={r} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {total && total.delta > EPS ? (
        <p role="alert" className="flex items-start gap-2 rounded-2xl bg-act/12 p-3 text-small text-act-fg" data-testid="savings-worse">
          <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
          {tv("savings.worse")}
        </p>
      ) : null}

      <p className="text-small" data-testid="savings-late">
        {late.stops > 0
          ? tv("savings.late", { hours: formatDuration(late.hours, lang, digits), count: formatNumber(late.stops, digits) })
          : tv("savings.onTime")}
      </p>
      <p className="text-xs text-muted">{tv("savings.basis")}</p>
    </section>
  );
}

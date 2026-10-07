import { useTranslation } from "react-i18next";

import type { VanPlan } from "../../../api/vanPlans";
import { SourceChip } from "../../../components/ui/SourceChip";
import { formatDuration, formatNumber, formatPercent } from "../../../lib/format";
import { useLocale } from "../../../lib/prefs";
import { VAN_NS } from "../../../i18n/vanRoutes";
import { groupRows, parseGroup } from "./vanRoutesModel";

/** Who the plan reaches, by area and tier: by van, by a suggested swap, or not at all. */
export function FairnessPanel({ plan }: { plan: VanPlan }) {
  const { t: tv } = useTranslation(VAN_NS);
  const { lang, digits } = useLocale();
  const rows = groupRows(plan);
  const n = (value: number) => formatNumber(value, digits);

  return (
    <section aria-labelledby="fairness-title" className="ap-card space-y-3 p-4" data-testid="fairness-panel">
      <div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="fairness-title" className="font-display text-h3 font-bold">
            {tv("fairness.title")}
          </h2>
          <SourceChip source="rule" />
        </div>
        <p className="text-small text-muted">{tv("fairness.lead")}</p>
      </div>

      {rows.length === 0 ? (
        <p className="text-small text-muted">{tv("fairness.empty")}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[22rem] text-small">
            <thead>
              <tr className="text-left text-xs uppercase text-muted">
                <th scope="col" className="py-1 pr-2 font-semibold">
                  {tv("fairness.group")}
                </th>
                <th scope="col" className="py-1 pr-2 text-right font-semibold">
                  {tv("fairness.van")}
                </th>
                <th scope="col" className="py-1 pr-2 text-right font-semibold">
                  {tv("fairness.swap")}
                </th>
                <th scope="col" className="py-1 pr-2 text-right font-semibold">
                  {tv("fairness.none")}
                </th>
                <th scope="col" className="py-1 pr-2 text-right font-semibold">
                  {tv("fairness.covered")}
                </th>
                <th scope="col" className="py-1 text-right font-semibold">
                  {tv("fairness.maxLate")}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((g) => {
                const parsed = parseGroup(g.group);
                return (
                  <tr key={g.group} className="border-t border-line" data-testid="fairness-row" data-group={g.group}>
                    <th scope="row" className="py-2 pr-2 text-left font-medium">
                      {parsed
                        ? tv("fairness.groupLabel", { area: tv(`fairness.area.${parsed.area}`), tier: n(parsed.tier) })
                        : g.group}
                    </th>
                    <td className="num py-2 pr-2 text-right">{n(g.van)}</td>
                    <td className="num py-2 pr-2 text-right">{n(g.swap)}</td>
                    <td className="num py-2 pr-2 text-right">{n(g.notServed)}</td>
                    <td className="num py-2 pr-2 text-right font-semibold" data-testid="fairness-covered">
                      {formatPercent(g.covered, digits)}
                    </td>
                    <td className="num py-2 text-right text-muted">{g.maxLateH > 0 ? formatDuration(g.maxLateH, lang, digits) : "–"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

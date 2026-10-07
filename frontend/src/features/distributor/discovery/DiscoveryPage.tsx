import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { usePainPoints } from "../../../api/hooks/evidence";
import type { PainPoints } from "../../../api/types";
import { PageHeader } from "../../../components/ui/PageHeader";
import { SkeletonCard, SkeletonText } from "../../../components/ui/Skeleton";
import { EmptyState, ErrorState } from "../../../components/ui/StatePanel";
import { formatMoney, formatNumber, formatPercent } from "../../../lib/format";
import { useLocale } from "../../../lib/prefs";

type Kind = "FIELD" | "LITERATURE" | "SIMULATED";
const CHIP: Record<Kind, string> = {
  FIELD: "bg-pulse/12 text-pulse-fg",
  LITERATURE: "bg-surface-2 text-muted",
  SIMULATED: "bg-brand/20 text-fg",
};

function Chip({ kind, count }: { kind: Kind; count?: number }) {
  const { t } = useTranslation();
  return (
    <span data-testid={`chip-${kind}`} className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${CHIP[kind]}`}>
      {t(`discovery.chip.${kind}`)}
      {count === undefined ? null : <span className="num">{count}</span>}
    </span>
  );
}

function Incidence({ data }: { data: NonNullable<PainPoints["incidence"]> }) {
  const { t } = useTranslation();
  const { digits } = useLocale();
  const pct = (v: number) => formatPercent(v, digits);
  return (
    <section aria-labelledby="disc-inc" className="ap-card p-5" data-testid="incidence-table">
      <h2 id="disc-inc" className="font-display text-h2 font-bold">{t("discovery.incidenceTitle")}</h2>
      <p className="mt-1 text-small text-muted">{t("discovery.incidenceNote")}</p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-small">
          <thead className="text-left text-muted">
            <tr>
              {(["base", "ai", "avoided", "pct", "value", "trips"] as const).map((k) => (
                <th key={k} className="py-1.5 pr-3 font-semibold">{t(`discovery.col.${k}`)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.buffer_factor} className="border-t border-line num">
                <td className="py-1.5 pr-3">{formatNumber(r.baseline_stockout_hours, digits)} ({pct(r.baseline_share)})</td>
                <td className="py-1.5 pr-3">{formatNumber(r.ai_stockout_hours, digits)} ({pct(r.ai_share)})</td>
                <td className="py-1.5 pr-3">{formatNumber(r.hours_avoided, digits)}</td>
                <td className="py-1.5 pr-3">{r.percent_reduction === null ? "-" : pct(r.percent_reduction)}</td>
                <td className="py-1.5 pr-3">{formatMoney(r.value_saved_bdt, digits)}</td>
                <td className="py-1.5 pr-3">{formatNumber(r.van_trips_avoided, digits)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** Liquidity pain-point discovery: FIELD / LITERATURE / SIMULATED evidence, never mixed up. */
export function DiscoveryPage() {
  const { t } = useTranslation();
  const { lang, digits } = useLocale();
  const q = usePainPoints();
  const navigate = useNavigate();
  const bn = lang === "bn";

  if (q.isPending) {
    return (
      <div className="space-y-4" aria-busy="true">
        <SkeletonText lines={2} className="max-w-md" />
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );
  }
  if (q.isError) return <ErrorState onRetry={() => void q.refetch()} retrying={q.isFetching} />;
  const d = q.data;

  return (
    <div className="space-y-4" data-testid="discovery-page">
      <PageHeader title={t("discovery.title")} description={t("discovery.lead")}>
        <p className="mt-3 text-xs text-muted num">{t("discovery.fieldCount", { n: formatNumber(d.field_interviews_count, digits) })}</p>
      </PageHeader>

      {d.field_interviews_count === 0 ? (
        <EmptyState compact title={t("discovery.noField")} body={t("discovery.noFieldBody")} action={{ label: t("discovery.openHelp"), onClick: () => navigate("/help") }} />
      ) : null}
      <p className="text-small text-muted">{t("discovery.simulatedNote")}</p>

      <section aria-labelledby="disc-pain" className="ap-card p-5">
        <h2 id="disc-pain" className="font-display text-h2 font-bold">{t("discovery.painTitle")}</h2>
        <ol className="mt-3 divide-y divide-line">
          {d.pain_points.map((p) => (
            <li key={p.tag} data-testid="pain-point" className="flex flex-wrap items-center justify-between gap-3 py-3">
              <div className="min-w-0">
                <p className="font-semibold">{bn ? p.label_bn : p.label_en}</p>
                <p className="text-small text-muted">
                  {t("discovery.feature")}:{" "}
                  <Link to={p.feature_route} className="font-semibold text-pulse-fg underline underline-offset-2">
                    {bn ? p.feature_bn : p.feature_en}
                  </Link>
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Chip kind="FIELD" count={p.field_count} />
                <Chip kind="LITERATURE" count={p.literature_count} />
                <Chip kind="SIMULATED" count={p.simulated_count} />
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="disc-lit" className="ap-card p-5">
        <h2 id="disc-lit" className="font-display text-h2 font-bold">{t("discovery.literatureTitle")}</h2>
        <ul className="mt-3 space-y-2 text-small">
          {d.literature.map((l) => (
            <li key={l.source}>
              <span className="font-semibold">{l.source}</span> <span className="text-muted">({l.year_note})</span>: {l.fact}
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="disc-sim" className="ap-card p-5">
        <h2 id="disc-sim" className="font-display text-h2 font-bold">{t("discovery.personasTitle")}</h2>
        <ul className="mt-3 space-y-2 text-small">
          {d.personas.map((p) => (
            <li key={p.id}>
              <Chip kind="SIMULATED" /> <span className="font-semibold">{bn ? p.title_bn : p.title_en}</span>: {bn ? p.hypothesis_bn : p.hypothesis_en}
            </li>
          ))}
        </ul>
      </section>

      {d.incidence ? <Incidence data={d.incidence} /> : null}
    </div>
  );
}

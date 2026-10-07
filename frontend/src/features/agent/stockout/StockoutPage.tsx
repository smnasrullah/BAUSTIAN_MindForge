import { ChartLine } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { useAgentSummary } from "../../../api/hooks/agents";
import type { FloatSummary } from "../../../api/types";
import { ConfidenceRing } from "../../../components/ui/ConfidenceRing";
import { LiquidButton } from "../../../components/ui/LiquidButton";
import { RISK_STYLE } from "../../../components/ui/risk";
import { RiskPill } from "../../../components/ui/RiskPill";
import { SkeletonCard } from "../../../components/ui/Skeleton";
import { ErrorState } from "../../../components/ui/StatePanel";
import { formatDateTime, formatDuration, formatMoney, formatPercent } from "../../../lib/format";
import { useLocale } from "../../../lib/prefs";
import { NoAgentState, NoPredictionState } from "../AgentPageStates";
import { FLOATS, stockoutFlag } from "../runwayModel";
import { useMyAgentId } from "../useAgentData";
import { HorizonLadder } from "./HorizonLadder";

/** Time to stockout per float, with confidence and the 6 / 24 / 72 h risk ladder. */
export function StockoutPage() {
  const { t } = useTranslation();
  const { lang, digits } = useLocale();
  const id = useMyAgentId();
  const summary = useAgentSummary(id);
  const floats = FLOATS.flatMap((ft) => summary.data?.floats.filter((f) => f.float_type === ft) ?? []);

  return (
    <div className="space-y-4">
      <header>
        <h1 className="font-display text-h1 font-bold">{t("stockout.title")}</h1>
        {summary.data ? (
          <p className="num mt-1 text-small text-muted">
            {t("stockout.lead", { time: formatDateTime(new Date(summary.data.as_of), lang, digits) })}
          </p>
        ) : null}
      </header>
      {id === null ? (
        <NoAgentState />
      ) : summary.isPending ? (
        <div className={FLOAT_GRID}>
          <SkeletonCard />
          <SkeletonCard />
        </div>
      ) : summary.isError ? (
        <ErrorState onRetry={() => void summary.refetch()} retrying={summary.isFetching} />
      ) : floats.length === 0 ? (
        <NoPredictionState onRetry={() => void summary.refetch()} />
      ) : (
        <div className={FLOAT_GRID}>
          {floats.map((f) => (
            <FloatStockoutCard key={f.float_type} float={f} />
          ))}
        </div>
      )}
    </div>
  );
}

// Phones: stacked. Desktop: the float cards side by side.
const FLOAT_GRID = "space-y-4 lg:grid lg:grid-cols-2 lg:items-start lg:gap-6 lg:space-y-0";

function FloatStockoutCard({ float }: { float: FloatSummary }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { lang, digits } = useLocale();
  const flag = stockoutFlag(float);
  const name = t(`float.${float.float_type}`);
  const stroke = RISK_STYLE[float.level].stroke;
  const confidence = formatPercent(float.confidence, digits);

  return (
    <section
      aria-label={name}
      data-testid={`stockout-${float.float_type}`}
      className="rounded-[var(--radius-card)] border bg-surface p-5 shadow-soft"
      style={{ borderColor: `color-mix(in srgb, ${stroke} 45%, transparent)` }}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="font-semibold">{name}</p>
        <RiskPill level={float.level} size="sm" />
      </div>
      <div className="mt-3 flex items-start justify-between gap-4">
        <div className="min-w-0">
          {flag ? (
            <>
              <p data-testid="stockout-time" className="num font-display text-h1 font-bold leading-tight">
                {t("stockout.around", { time: formatDateTime(new Date(flag.at), lang, digits) })}
              </p>
              <p className="num mt-1 text-small text-muted">{t("stockout.in", { duration: formatDuration(flag.hour, lang, digits) })}</p>
            </>
          ) : (
            <p className="font-display text-h2 font-bold leading-tight">{t("stockout.none")}</p>
          )}
          <p className="num mt-2 text-xs text-muted">
            {t(flag ? "stockout.confidence" : "stockout.noneConfidence", { value: confidence })} ·{" "}
            {t("stockout.balance", {
              balance: formatMoney(float.balance, digits, { lang }),
              capacity: formatMoney(float.capacity, digits, { lang, compact: true }),
            })}
          </p>
        </div>
        <ConfidenceRing value={float.confidence} stroke={stroke} className="shrink-0" />
      </div>
      <div className="mt-4">
        <HorizonLadder horizons={float.horizons} />
      </div>
      <LiquidButton
        variant="secondary"
        className="mt-4 w-full"
        icon={ChartLine}
        onClick={() => navigate(`/agent/forecast?float=${float.float_type}`)}
      >
        {t("stockout.seeForecast", { float: name })}
      </LiquidButton>
    </section>
  );
}

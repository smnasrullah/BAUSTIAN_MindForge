import { RotateCcw, RotateCw, ShieldCheck } from "lucide-react";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";

import { useRunway, useWhatIfQuery } from "../../../api/hooks/agents";
import type { FloatType, Runway, WhatIfOut } from "../../../api/types";
import { RunwayStrip } from "../../../components/signature/RunwayStrip";
import { VesselGauge } from "../../../components/signature/VesselGauge";
import { LiquidButton } from "../../../components/ui/LiquidButton";
import { RiskPill } from "../../../components/ui/RiskPill";
import { SkeletonGauge, SkeletonRunway } from "../../../components/ui/Skeleton";
import { EmptyState, ErrorState } from "../../../components/ui/StatePanel";
import { cn } from "../../../lib/cn";
import { formatDateTime, formatMoney } from "../../../lib/format";
import { useLocale } from "../../../lib/prefs";
import { useDebounced } from "../../../lib/useDebounced";
import { NoAgentState } from "../AgentPageStates";
import { FloatSwitch } from "../FloatSwitch";
import { isFloatType, stockoutFlag, toRunwayPoints } from "../runwayModel";
import { useMyAgentId } from "../useAgentData";
import { resultKind, sliderBounds, WHATIF_DEBOUNCE_MS, WHATIF_STEP } from "./whatIfModel";

/** What-if (F8): add or remove float and watch the vessel and runway react; the backend re-projects. */
export function WhatIfPage() {
  const { t } = useTranslation();
  const id = useMyAgentId();
  const [params, setParams] = useSearchParams();
  const raw = params.get("float");
  const floatType: FloatType = isFloatType(raw) ? raw : "cash";

  function choose(next: FloatType): void {
    const merged = new URLSearchParams(params);
    merged.set("float", next);
    setParams(merged, { replace: true });
  }

  return (
    <div className="space-y-4">
      <header className="space-y-3">
        <h1 className="font-display text-h1 font-bold">{t("whatif.title")}</h1>
        <p className="text-small text-muted">{t("whatif.lead")}</p>
        <FloatSwitch value={floatType} onChange={choose} />
      </header>
      {id === null ? (
        <NoAgentState />
      ) : (
        <div className={SIM_GRID}>
          <WhatIfBody key={floatType} agentId={id} floatType={floatType} />
        </div>
      )}
      <p className="flex items-center gap-1.5 text-xs text-muted">
        <ShieldCheck aria-hidden className="size-3.5" />
        {t("whatif.notice")}
      </p>
    </div>
  );
}

// Phones: stacked. Desktop: the slider (1st block) beside the live result sentence (3rd) on top, the
// vessel + runway (2nd) and the as-of line (4th) full width below. A lone block takes the full width.
const SIM_GRID = [
  "space-y-4",
  "lg:grid lg:grid-cols-2 lg:gap-x-6 lg:gap-y-4 lg:space-y-0",
  "lg:[&>:nth-child(2)]:col-span-2 lg:[&>:nth-child(2)]:row-start-2",
  "lg:[&>:nth-child(3)]:col-start-2 lg:[&>:nth-child(3)]:row-start-1",
  "lg:[&>:nth-child(4)]:col-span-2 lg:[&>:only-child]:col-span-2",
].join(" ");

/** What-if simulator for one agent's float (also used on the distributor agent detail). */
export function WhatIfBody({ agentId, floatType }: { agentId: number; floatType: FloatType }) {
  const { t } = useTranslation();
  const base = useRunway(agentId, floatType);

  if (base.isPending) {
    return (
      <>
        <SkeletonGauge />
        <SkeletonRunway className="h-56" />
      </>
    );
  }
  if (base.isError) return <ErrorState onRetry={() => void base.refetch()} retrying={base.isFetching} />;
  if (base.data.series.length === 0) {
    return (
      <EmptyState
        title={t("forecast.empty.title")}
        body={t("forecast.empty.body")}
        action={{ label: t("forecast.empty.action"), icon: RotateCw, onClick: () => void base.refetch() }}
      />
    );
  }
  return <Simulator agentId={agentId} floatType={floatType} base={base.data} />;
}

function Simulator({ agentId, floatType, base }: { agentId: number; floatType: FloatType; base: Runway }) {
  const { t } = useTranslation();
  const { lang, digits } = useLocale();
  const sliderId = useId();
  const [delta, setDelta] = useState(0);
  const settled = useDebounced(delta, WHATIF_DEBOUNCE_MS);
  const q = useWhatIfQuery(agentId, floatType, settled);
  const capacity = Math.max(base.capacity, base.balance);
  const { min, max } = sliderBounds(base.balance, base.capacity);
  // Delta 0 is the cached runway itself; otherwise the latest backend answer (kept while the next loads).
  const result = settled !== 0 && q.data && q.data.delta_amount !== 0 ? q.data : null;
  const after = result?.after ?? base;
  const updating = delta !== settled || q.isFetching;
  const change = formatMoney(delta, digits, { lang, signed: true });

  return (
    <>
      <section aria-labelledby={`${sliderId}-label`} className="ap-card p-5 shadow-soft">
        <div className="flex items-baseline justify-between gap-3">
          <label id={`${sliderId}-label`} htmlFor={sliderId} className="font-semibold">
            {t("whatif.slider", { float: t(`float.${floatType}`) })}
          </label>
          <output htmlFor={sliderId} data-testid="whatif-delta" className="num font-display text-h2 font-bold">
            {change}
          </output>
        </div>
        <input
          id={sliderId}
          type="range"
          min={min}
          max={max}
          step={WHATIF_STEP}
          value={delta}
          onChange={(e) => setDelta(Number(e.target.value))}
          aria-valuetext={change}
          className="mt-4 h-11 w-full cursor-pointer accent-[var(--color-pulse)]"
        />
        <div className="num flex justify-between text-xs text-muted">
          <span>{formatMoney(min, digits, { lang, signed: true, compact: true })}</span>
          <span>{formatMoney(max, digits, { lang, signed: true, compact: true })}</span>
        </div>
        <LiquidButton variant="ghost" size="sm" icon={RotateCcw} className="mt-2" disabled={delta === 0} onClick={() => setDelta(0)}>
          {t("whatif.reset")}
        </LiquidButton>
      </section>

      <div className="grid gap-4 md:grid-cols-[minmax(0,14rem)_minmax(0,1fr)]">
        <VesselGauge floatType={floatType} balance={base.balance + delta} capacity={capacity} level={after.level} />
        <div className={cn("transition-opacity", updating && "opacity-70")}>
          <RunwayStrip
            subtitle={t(`float.${floatType}`)}
            series={toRunwayPoints(after)}
            ghost={result ? toRunwayPoints(base) : null}
            capacity={capacity}
            stockout={stockoutFlag(after)}
          />
        </div>
      </div>

      <ResultSentence base={base} result={result} floatType={floatType} updating={updating} onRetry={q.isError ? () => void q.refetch() : null} />
      <p className="num text-xs text-muted">
        {t("forecast.asOf", { time: formatDateTime(new Date(base.as_of), lang, digits), model: (result ?? base).model_version })}
      </p>
    </>
  );
}

interface ResultSentenceProps {
  base: Runway;
  result: WhatIfOut | null;
  floatType: FloatType;
  updating: boolean;
  onRetry: (() => void) | null;
}

function ResultSentence({ base, result, floatType, updating, onRetry }: ResultSentenceProps) {
  const { t } = useTranslation();
  const { lang, digits } = useLocale();
  const at = (iso: string | null) => (iso ? formatDateTime(new Date(iso), lang, digits) : "");

  if (onRetry) return <ErrorState compact onRetry={onRetry} />;

  const text = result
    ? t(`whatif.result.${resultKind(result.before, result.after)}`, {
        change: formatMoney(result.delta_amount, digits, { lang, signed: true }),
        float: t(`float.${floatType}`),
        before: at(result.before.stockout_at),
        after: at(result.after.stockout_at),
      })
    : t("whatif.result.idle", { float: t(`float.${floatType}`) });
  const level = (result?.after ?? base).level;

  return (
    <section aria-live="polite" className="rounded-[var(--radius-card)] border border-line bg-surface-2 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-small font-semibold text-muted">{t("whatif.resultTitle")}</p>
        <RiskPill level={level} size="sm" />
      </div>
      <p data-testid="whatif-result" className="num mt-2 font-display text-h2 font-bold leading-snug">
        {text}
      </p>
      {updating ? <p className="mt-1 text-xs text-muted">{t("whatif.updating")}</p> : null}
    </section>
  );
}

import { ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { useAgentSummary } from "../../../api/hooks/agents";
import type { AgentSummary } from "../../../api/types";
import { CountdownCard } from "../../../components/signature/CountdownCard";
import { Skeleton, SkeletonCard, SkeletonGauge, SkeletonRunway, SkeletonText } from "../../../components/ui/Skeleton";
import { ErrorState } from "../../../components/ui/StatePanel";
import { NoAgentState, NoPredictionState } from "../AgentPageStates";
import { FLOATS, headlineFloat, stockoutFlag } from "../runwayModel";
import { useMyAgentId, useRunwayEvents } from "../useAgentData";
import { FloatGauge } from "./FloatGauge";
import { NextActionCard } from "./NextActionCard";
import { RunwaySection } from "./RunwaySection";
import { WhyPanel } from "./WhyPanel";

/** Agent home (390px first): countdown, two vessels, runway, why, then the one primary action.
 * From 1024px the same blocks sit in a control-room grid: summary row, wide runway + why, action side panel. */
export function AgentHomePage() {
  const { t } = useTranslation();
  const id = useMyAgentId();
  const summary = useAgentSummary(id);

  return (
    <div className="space-y-4">
      <h1 className="sr-only">{t("page.agentHome")}</h1>
      {id === null ? (
        <NoAgentState />
      ) : summary.isPending ? (
        <HomeSkeleton />
      ) : summary.isError ? (
        <ErrorState onRetry={() => void summary.refetch()} retrying={summary.isFetching} />
      ) : summary.data.floats.length === 0 ? (
        <NoPredictionState onRetry={() => void summary.refetch()} />
      ) : (
        <HomeBody agentId={id} summary={summary.data} />
      )}
    </div>
  );
}

function HomeBody({ agentId, summary }: { agentId: number; summary: AgentSummary }) {
  const { t } = useTranslation();
  const events = useRunwayEvents(summary);
  const lead = headlineFloat(summary.floats) ?? summary.floats[0];
  if (!lead) return null;
  const flag = stockoutFlag(lead);
  const floats = FLOATS.flatMap((ft) => summary.floats.filter((f) => f.float_type === ft));

  return (
    <div className={GRID}>
      <p className="truncate text-small text-muted lg:[grid-area:who]">
        {summary.agent.name} · <span className="num">{summary.agent.code}</span>
      </p>
      <CountdownCard
        floatType={lead.float_type}
        hoursToStockout={flag?.hour ?? null}
        confidence={lead.confidence}
        level={lead.level}
        className="lg:[grid-area:count]"
      />
      <Link
        to="/agent/stockout"
        className="-mt-1 flex min-h-11 items-center justify-end gap-1 text-small font-semibold text-pulse-fg hover:underline lg:mt-0 lg:[grid-area:link]"
      >
        {t("agent.stockoutLink")}
        <ChevronRight aria-hidden className="size-4" />
      </Link>

      <section aria-label={t("agent.floats")} className="grid grid-cols-2 gap-3 lg:[grid-area:floats] lg:self-start">
        {floats.map((f) => (
          <FloatGauge key={f.float_type} agentId={agentId} float={f} />
        ))}
      </section>

      <div className="min-w-0 lg:[grid-area:run]">
        <RunwaySection agentId={agentId} floatType={lead.float_type} events={events} />
      </div>
      <div className="min-w-0 lg:[grid-area:why]">
        <WhyPanel agentId={agentId} initialFloat={lead.float_type} />
      </div>
      <div className="lg:sticky lg:top-20 lg:self-start lg:[grid-area:act]">
        <NextActionCard agentId={agentId} />
      </div>
    </div>
  );
}

// Phones: one stacked column (space-y). Desktop: main column + a side panel as wide as the vessels row.
const GRID = [
  "space-y-4",
  "lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(20rem,26rem)] lg:gap-x-6 lg:gap-y-4 lg:space-y-0",
  "lg:[grid-template-areas:'who_who'_'count_floats'_'link_floats'_'run_act'_'why_act']",
  "lg:grid-rows-[auto_auto_auto_auto_1fr]",
].join(" ");

/** Same grid as the loaded page, so nothing moves when data lands. Desktop-only placeholders are hidden on phones. */
function HomeSkeleton() {
  return (
    <div className={GRID}>
      <Skeleton className="hidden h-5 w-56 lg:block lg:[grid-area:who]" />
      <SkeletonCard className="lg:[grid-area:count]" />
      <div aria-hidden className="hidden min-h-11 lg:block lg:[grid-area:link]" />
      <div className="grid grid-cols-2 gap-3 lg:self-start lg:[grid-area:floats]">
        <SkeletonGauge />
        <SkeletonGauge />
      </div>
      {/* The runway stays the last visible block on phones (no trailing gap). */}
      <SkeletonRunway className="max-lg:mb-0 lg:[grid-area:run]" />
      <div className="hidden lg:block lg:[grid-area:why]">
        <div className="ap-card p-4">
          <SkeletonText lines={4} />
        </div>
      </div>
      <SkeletonCard className="hidden lg:block lg:self-start lg:[grid-area:act]" />
    </div>
  );
}

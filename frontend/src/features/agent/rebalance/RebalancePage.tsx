import { ChartLine, ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { useRecommendation } from "../../../api/hooks/agents";
import { useRequests } from "../../../api/hooks/requests";
import { PageHeader } from "../../../components/ui/PageHeader";
import { SkeletonCard } from "../../../components/ui/Skeleton";
import { EmptyState, ErrorState } from "../../../components/ui/StatePanel";
import { NoAgentState } from "../AgentPageStates";
import { useMyAgentId } from "../useAgentData";
import { RecommendationCard } from "./RecommendationCard";
import { requestFor, sortRecommendations } from "./requestStatus";
import { SwapOffers } from "./SwapOffers";

/** Rebalance (F4, F5): what to add and by when, the request status, and nearby swap offers. */
export function RebalancePage() {
  const { t } = useTranslation();
  const id = useMyAgentId();

  return (
    <div className="space-y-6">
      <PageHeader title={t("rebalance.title")} description={t("rebalance.lead")} />
      {id === null ? (
        <NoAgentState />
      ) : (
        // Desktop: what to add on the left, nearby swap offers on the right.
        <div className="space-y-6 lg:grid lg:grid-cols-2 lg:items-start lg:gap-6 lg:space-y-0">
          <Recommendations agentId={id} />
          <SwapOffers agentId={id} />
        </div>
      )}
      <p className="flex items-center gap-1.5 text-xs text-muted">
        <ShieldCheck aria-hidden className="size-3.5" />
        {t("common.advisory")}
      </p>
    </div>
  );
}

function Recommendations({ agentId }: { agentId: number }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const rec = useRecommendation(agentId);
  // Status is decoration on top of the card: without it the card still works.
  const requests = useRequests({ page_size: 100 });
  const all = requests.data?.items ?? [];

  if (rec.isPending) return <SkeletonCard />;
  if (rec.isError) return <ErrorState compact onRetry={() => void rec.refetch()} retrying={rec.isFetching} />;
  const items = sortRecommendations(rec.data.items);
  if (items.length === 0) {
    return (
      <EmptyState
        compact
        illustration="quiet-pulse"
        title={t("action.clear.title")}
        body={t("action.clear.body")}
        action={{ label: t("action.clear.action"), icon: ChartLine, onClick: () => navigate("/agent/forecast") }}
      />
    );
  }

  return (
    <section aria-label={t("rebalance.recommendations")} className="space-y-3">
      {requests.isError ? (
        <ErrorState compact title={t("rebalance.statusFailed")} onRetry={() => void requests.refetch()} retrying={requests.isFetching} />
      ) : null}
      {items.map((item) => (
        <RecommendationCard key={item.id} agentId={agentId} item={item} request={requestFor(item.id, all)} />
      ))}
    </section>
  );
}

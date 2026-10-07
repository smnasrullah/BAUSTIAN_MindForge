import { RotateCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useSwaps } from "../../../api/hooks/swaps";
import type { SwapItem } from "../../../api/types";
import { SkeletonCard } from "../../../components/ui/Skeleton";
import { StaggerItem, StaggerList } from "../../../components/ui/Stagger";
import { EmptyState, ErrorState } from "../../../components/ui/StatePanel";
import { SwapOfferCard } from "./SwapOfferCard";

interface SwapOffersProps {
  agentId: number;
  /** Swap page: every status, split into what you receive and what you give. Rebalance: pending only. */
  grouped?: boolean;
}

/** Agent-to-agent swaps (F5) the signed-in agent is part of: accept or decline, the distributor decides. */
export function SwapOffers({ agentId, grouped = false }: SwapOffersProps) {
  const { t } = useTranslation();
  const q = useSwaps(grouped ? { page_size: 100 } : { status: "pending" });
  const items = q.data?.items ?? [];

  return (
    <section aria-labelledby="swap-offers" className="space-y-3">
      <h2 id="swap-offers" className="font-display text-h2 font-bold">
        {t("rebalance.swaps.title")}
      </h2>
      {q.isPending ? (
        <SkeletonCard />
      ) : q.isError ? (
        <ErrorState compact onRetry={() => void q.refetch()} retrying={q.isFetching} />
      ) : items.length === 0 ? (
        <EmptyState
          compact
          illustration="quiet-pulse"
          title={t("rebalance.swaps.empty.title")}
          body={t("rebalance.swaps.empty.body")}
          action={{ label: t("rebalance.swaps.empty.action"), icon: RotateCw, onClick: () => void q.refetch() }}
        />
      ) : grouped ? (
        // Desktop: what you receive and what you give side by side.
        <div className="space-y-3 lg:grid lg:grid-cols-2 lg:items-start lg:gap-6 lg:space-y-0">
          <SwapGroup testId="swaps-incoming" title={t("rebalance.swaps.incoming")} items={items.filter((s) => s.receiver.agent_id === agentId)} agentId={agentId} />
          <SwapGroup testId="swaps-outgoing" title={t("rebalance.swaps.outgoing")} items={items.filter((s) => s.donor.agent_id === agentId)} agentId={agentId} />
        </div>
      ) : (
        <SwapCards items={items} agentId={agentId} />
      )}
    </section>
  );
}

function SwapCards({ items, agentId }: { items: SwapItem[]; agentId: number }) {
  return (
    <StaggerList className="space-y-3">
      {items.map((s) => (
        <StaggerItem key={s.id}>
          <SwapOfferCard swap={s} agentId={agentId} />
        </StaggerItem>
      ))}
    </StaggerList>
  );
}

function SwapGroup({ title, items, agentId, testId }: { title: string; items: SwapItem[]; agentId: number; testId: string }) {
  const { t } = useTranslation();
  return (
    <div data-testid={testId} className="space-y-2">
      <h3 className="text-small font-semibold text-muted">{title}</h3>
      {items.length === 0 ? <p className="text-small text-muted">{t("rebalance.swaps.groupEmpty")}</p> : <SwapCards items={items} agentId={agentId} />}
    </div>
  );
}

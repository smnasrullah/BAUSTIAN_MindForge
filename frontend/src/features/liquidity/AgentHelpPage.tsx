import { HandHeart, ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useHelpInboxPages, useMyHelpRequests } from "../../api/hooks/helpRequests";
import { EmptyState, ErrorState } from "../../components/ui/StatePanel";
import { PageHeader } from "../../components/ui/PageHeader";
import { SkeletonPanel } from "../../components/ui/Skeleton";
import { useNow } from "../../lib/useNow";
import { helpNeededFor, isActive } from "./helpModel";
import { HelpNeededCard } from "./HelpNeededCard";
import { LoadMore } from "./HelpParts";
import { MyHelpRequestCard } from "./MyHelpRequestCard";

/** /agent/help: requests that need my answer, and my own request while it is still open or claimed. */
export function AgentHelpPage() {
  const { t } = useTranslation();
  const now = useNow(15_000);
  const inbox = useHelpInboxPages({ page_size: 25 });
  const mine = useMyHelpRequests({ page_size: 20 });
  const needed = inbox.data ? helpNeededFor(inbox.data.pages.flatMap((p) => p.items)) : [];
  const active = mine.data ? mine.data.items.filter((item) => isActive(item.status)) : [];

  return (
    <div className="space-y-8">
      <PageHeader title={t("liquidity.agent.title")} description={t("liquidity.agent.lead")} />

      <section aria-labelledby="help-needed-title" className="space-y-3">
        <h2 id="help-needed-title" className="flex items-center gap-2 font-display text-h2 font-bold">
          <HandHeart aria-hidden className="size-5 text-act-fg" />
          {t("liquidity.agent.needed.title")}
        </h2>
        {inbox.isPending ? (
          <SkeletonPanel rows={2} />
        ) : inbox.isError ? (
          <ErrorState onRetry={() => void inbox.refetch()} retrying={inbox.isFetching} />
        ) : needed.length === 0 && !inbox.hasNextPage ? (
          <div data-testid="help-needed-empty">
            <EmptyState
              illustration="quiet-pulse"
              title={t("liquidity.agent.needed.empty.title")}
              body={t("liquidity.agent.needed.empty.body")}
              action={{ label: t("liquidity.agent.needed.check"), onClick: () => void inbox.refetch() }}
            />
          </div>
        ) : (
          <>
            <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
              {needed.map((item) => (
                <HelpNeededCard key={item.id} item={item} now={now} />
              ))}
            </div>
            <LoadMore hasMore={inbox.hasNextPage} loading={inbox.isFetchingNextPage} onMore={() => void inbox.fetchNextPage()} />
          </>
        )}
      </section>

      <section aria-labelledby="my-help-title" className="space-y-3">
        <h2 id="my-help-title" className="font-display text-h2 font-bold">
          {t("liquidity.agent.mine.title")}
        </h2>
        {mine.isPending ? (
          <SkeletonPanel rows={2} />
        ) : mine.isError ? (
          <ErrorState onRetry={() => void mine.refetch()} retrying={mine.isFetching} />
        ) : active.length === 0 ? (
          <EmptyState
            illustration="quiet-pulse"
            title={t("liquidity.agent.mine.empty.title")}
            body={t("liquidity.agent.mine.empty.body")}
            action={{ label: t("liquidity.agent.mine.check"), onClick: () => void mine.refetch() }}
          />
        ) : (
          <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
            {active.map((item) => (
              <MyHelpRequestCard key={item.id} item={item} now={now} />
            ))}
          </div>
        )}
      </section>

      <p className="flex items-center gap-1.5 text-xs text-muted">
        <ShieldCheck aria-hidden className="size-3.5" />
        {t("common.advisory")}
      </p>
    </div>
  );
}

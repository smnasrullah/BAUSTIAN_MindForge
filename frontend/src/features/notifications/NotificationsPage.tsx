import { CheckCheck, ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";

import { useMarkAllNotificationsRead, useNotifications } from "../../api/hooks/notifications";
import type { NotificationItem } from "../../api/types";
import { LiquidButton } from "../../components/ui/LiquidButton";
import { PageHeader } from "../../components/ui/PageHeader";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { SkeletonRows } from "../../components/ui/Skeleton";
import { ErrorState } from "../../components/ui/StatePanel";
import { toast } from "../../components/ui/toastStore";
import { formatNumber } from "../../lib/format";
import { useLocale } from "../../lib/prefs";
import { InboxEmpty } from "./InboxEmpty";
import { NotificationList } from "./NotificationList";
import { useSingleFlight } from "../../lib/useSingleFlight";

const PAGE_SIZE = 20;
type Status = "all" | "unread" | "read";
type Severity = "any" | NotificationItem["severity"];
const STATUSES: Status[] = ["all", "unread", "read"];
const SEVERITIES: Severity[] = ["any", "info", "warning", "critical"];

function pick<T extends string>(value: string | null, allowed: readonly T[], fallback: T): T {
  return allowed.find((a) => a === value) ?? fallback;
}

export function NotificationsPage() {
  const { t } = useTranslation();
  const { digits } = useLocale();
  const [params, setParams] = useSearchParams();
  const status = pick(params.get("status"), STATUSES, "all");
  const severity = pick(params.get("severity"), SEVERITIES, "any");
  const page = Math.max(1, Number(params.get("page")) || 1);
  const q = useNotifications({ page, page_size: PAGE_SIZE, unread: status === "all" ? undefined : status === "unread" });
  const markAll = useMarkAllNotificationsRead();
  const once = useSingleFlight();

  function update(next: Record<string, string | null>): void {
    const merged = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      if (v === null) merged.delete(k);
      else merged.set(k, v);
    }
    setParams(merged, { replace: true });
  }

  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / PAGE_SIZE)) : 1;
  const items = (q.data?.items ?? []).filter((n) => severity === "any" || n.severity === severity);

  return (
    <section className="mx-auto max-w-3xl space-y-5">
      <PageHeader
        eyebrow={`${t("inbox.unread")}: ${formatNumber(q.data?.unread_count ?? 0, digits)}`}
        title={t("inbox.title")}
        actions={
          <LiquidButton
            variant="secondary"
            icon={CheckCheck}
            disabled={!q.data || q.data.unread_count === 0}
            loading={markAll.isPending}
            onClick={() =>
              once((done) =>
                markAll.mutate(undefined, {
                  onSuccess: () => toast({ tone: "success", title: t("inbox.markedAll") }),
                  onError: () => toast({ tone: "error", title: t("inbox.failed") }),
                  onSettled: done,
                }),
              )
            }
          >
            {t("inbox.markAll")}
          </LiquidButton>
        }
      />

      <div className="flex flex-wrap gap-3">
        <SegmentedControl
          label={t("inbox.filter.status")}
          value={status}
          onChange={(v) => update({ status: v === "all" ? null : v, page: null })}
          options={STATUSES.map((s) => ({ value: s, label: t(`inbox.filter.${s}`) }))}
        />
        <SegmentedControl
          label={t("inbox.filter.severity")}
          value={severity}
          onChange={(v) => update({ severity: v === "any" ? null : v })}
          options={SEVERITIES.map((s) => ({ value: s, label: s === "any" ? t("inbox.filter.anySeverity") : t(`inbox.severity.${s}`) }))}
        />
      </div>

      <div className="ap-card p-2">
        {q.isPending ? (
          <div className="p-3">
            <SkeletonRows rows={6} cols={1} />
          </div>
        ) : q.isError ? (
          <ErrorState onRetry={() => void q.refetch()} retrying={q.isFetching} />
        ) : items.length === 0 ? (
          <InboxEmpty />
        ) : (
          <NotificationList items={items} />
        )}
      </div>

      {pages > 1 ? (
        <nav className="flex items-center justify-between gap-3 text-small" aria-label={t("inbox.pageOf", { page, pages })}>
          <LiquidButton variant="ghost" icon={ChevronLeft} disabled={page <= 1} onClick={() => update({ page: String(page - 1) })}>
            {t("inbox.prev")}
          </LiquidButton>
          <span className="num text-muted">
            {t("inbox.pageOf", { page: formatNumber(page, digits), pages: formatNumber(pages, digits) })}
          </span>
          <LiquidButton variant="ghost" icon={ChevronRight} disabled={page >= pages} onClick={() => update({ page: String(page + 1) })}>
            {t("inbox.next")}
          </LiquidButton>
        </nav>
      ) : null}
    </section>
  );
}

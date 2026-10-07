import * as Popover from "@radix-ui/react-popover";
import { Bell, CheckCheck } from "lucide-react";
import { AnimatePresence, motion, useAnimationControls } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { useHelpUnread, useMarkAllNotificationsRead, useNotifications } from "../../api/hooks/notifications";
import { SkeletonRows } from "../../components/ui/Skeleton";
import { ErrorState } from "../../components/ui/StatePanel";
import { toast } from "../../components/ui/toastStore";
import { formatNumber } from "../../lib/format";
import { useReducedMotionPref } from "../../lib/motionPrefs";
import { useLocale } from "../../lib/prefs";
import { DUR, SPRING } from "../../styles/motion";
import { InboxEmpty } from "./InboxEmpty";
import { NotificationList } from "./NotificationList";
import { notificationText } from "./notificationModel";
import { useSingleFlight } from "../../lib/useSingleFlight";

const PANEL_SIZE = 20;
const SHAKE = { rotate: [0, -14, 12, -8, 6, 0], transition: { duration: DUR.reveal } };

/** Bell with unread badge: shakes once when new ones arrive; the panel slides in. */
export function NotificationBell() {
  const { t } = useTranslation();
  const { lang, digits } = useLocale();
  const reduced = useReducedMotionPref();
  const [open, setOpen] = useState(false);
  const q = useNotifications({ page_size: PANEL_SIZE });
  useHelpUnread(); // fast help poll: a new help request refreshes this list at once
  const markAll = useMarkAllNotificationsRead();
  const once = useSingleFlight();
  const controls = useAnimationControls();
  const seen = useRef<number | null>(null);
  // Help request ids already announced; the first load only records them, so old ones stay quiet.
  const announced = useRef<Set<number> | null>(null);
  const unread = q.data?.unread_count ?? 0;

  useEffect(() => {
    if (q.data === undefined) return;
    if (seen.current !== null && unread > seen.current && !reduced) void controls.start(SHAKE);
    seen.current = unread;
  }, [q.data, unread, reduced, controls]);

  useEffect(() => {
    if (q.data === undefined) return;
    const help = q.data.items.filter((item) => item.entity_type === "liquidity_request");
    if (announced.current === null) {
      announced.current = new Set(help.map((item) => item.id));
      return;
    }
    for (const item of help) {
      if (announced.current.has(item.id)) continue;
      announced.current.add(item.id);
      toast({ tone: "info", title: notificationText(item, lang, digits), duration: 8000 });
    }
  }, [q.data, lang, digits]);

  function readAll(): void {
    once((done) =>
      markAll.mutate(undefined, {
        onSuccess: () => toast({ tone: "success", title: t("inbox.markedAll") }),
        onError: () => toast({ tone: "error", title: t("inbox.failed") }),
        onSettled: done,
      }),
    );
  }

  const badge = unread > 99 ? `${formatNumber(99, digits)}+` : formatNumber(unread, digits);
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger
        aria-label={unread ? t("inbox.open", { count: unread }) : t("inbox.title")}
        data-testid="notification-bell"
        data-tour="bell"
        className="relative grid size-11 place-items-center rounded-full border border-line bg-surface hover:bg-surface-2"
      >
        <motion.span animate={controls} className="grid place-items-center" style={{ transformOrigin: "50% 10%" }}>
          <Bell aria-hidden className="size-5" />
        </motion.span>
        <AnimatePresence>
          {unread > 0 ? (
            <motion.span
              key="badge"
              data-testid="notification-badge"
              initial={reduced ? { opacity: 0 } : { scale: 0 }}
              animate={reduced ? { opacity: 1 } : { scale: 1 }}
              exit={reduced ? { opacity: 0 } : { scale: 0 }}
              transition={SPRING.bounce}
              className="num absolute -right-1 -top-1 grid min-w-5 place-items-center rounded-full bg-act px-1 text-[11px] font-semibold leading-5 text-ink-950"
            >
              {badge}
            </motion.span>
          ) : null}
        </AnimatePresence>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={8}
          collisionPadding={12}
          aria-label={t("inbox.title")}
          className="ap-sheet z-(--z-overlay) flex max-h-[min(80vh,36rem)] w-[min(92vw,24rem)] flex-col ap-card text-fg shadow-lift"
        >
          <div className="flex items-center justify-between gap-2 border-b border-line px-4 py-3">
            <h2 className="font-display text-h2 font-bold">{t("inbox.title")}</h2>
            <button
              type="button"
              onClick={readAll}
              disabled={unread === 0 || markAll.isPending}
              className="ap-press inline-flex min-h-9 items-center gap-1.5 rounded-full px-3 text-small font-semibold text-pulse-fg hover:bg-surface-2 disabled:opacity-50"
            >
              <CheckCheck aria-hidden className="size-4" />
              {t("inbox.markAll")}
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {q.isPending ? (
              <div className="p-2">
                <SkeletonRows rows={4} cols={1} />
              </div>
            ) : q.isError ? (
              <ErrorState compact onRetry={() => void q.refetch()} retrying={q.isFetching} />
            ) : q.data.items.length === 0 ? (
              <InboxEmpty compact onAction={() => setOpen(false)} />
            ) : (
              <NotificationList items={q.data.items} onOpen={() => setOpen(false)} />
            )}
          </div>
          <Link
            to="/notifications"
            onClick={() => setOpen(false)}
            className="block border-t border-line px-4 py-3 text-center text-small font-semibold text-pulse-fg hover:bg-surface-2"
          >
            {t("inbox.viewAll")}
          </Link>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

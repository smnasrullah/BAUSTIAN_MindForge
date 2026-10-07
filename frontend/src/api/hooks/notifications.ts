import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { qk } from "../keys";
import { listNotifications, markAllNotificationsRead, markNotificationRead } from "../services/notifications";
import type { NotificationListQuery } from "../types";

// TanStack pauses both polls while the tab is hidden (refetchIntervalInBackground is off).
// Everything else: once a minute. Help requests need a fast answer: their unread count every 12 s
// (one row, entity_type filter), and a new one refreshes the full lists at once.
const POLL_MS = 60_000;
export const HELP_POLL_MS = 12_000;
const HELP_UNREAD: NotificationListQuery = { entity_type: "liquidity_request", unread: true, page_size: 1 };

export function useNotifications(q: NotificationListQuery = {}) {
  return useQuery({ queryKey: qk.notifications.list(q), queryFn: () => listNotifications(q), refetchInterval: POLL_MS });
}

/** Unread help-request notifications (the Help badge). A rise refreshes every notification list. */
export function useHelpUnread(): number {
  const client = useQueryClient();
  const q = useQuery({ queryKey: qk.notifications.list(HELP_UNREAD), queryFn: () => listNotifications(HELP_UNREAD), refetchInterval: HELP_POLL_MS });
  const loaded = q.data !== undefined;
  const count = q.data?.unread_count ?? 0;
  const seen = useRef<number | null>(null);
  useEffect(() => {
    // The first answer is the baseline, not a rise (it used to refetch every list on page load).
    if (!loaded) return;
    // Several components use this hook; cancelRefetch: false joins a refetch already in flight.
    if (seen.current !== null && count > seen.current) {
      void client.invalidateQueries({ queryKey: qk.notifications.all }, { cancelRefetch: false });
    }
    seen.current = count;
  }, [loaded, count, client]);
  return count;
}

export function useMarkNotificationRead() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => markNotificationRead(id),
    onSettled: () => client.invalidateQueries({ queryKey: qk.notifications.all }),
  });
}

export function useMarkAllNotificationsRead() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: markAllNotificationsRead,
    onSettled: () => client.invalidateQueries({ queryKey: qk.notifications.all }),
  });
}

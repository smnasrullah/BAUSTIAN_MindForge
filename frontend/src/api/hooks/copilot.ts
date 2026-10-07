import { useQuery } from "@tanstack/react-query";

import { qk } from "../keys";
import { copilotConversationMessages, copilotConversations, copilotSuggestions } from "../services/copilot";
import type { Lang } from "../types";

/** Suggested questions: the only ones with recorded replay wording (exact text). */
export function useCopilotSuggestions(lang: Lang) {
  return useQuery({
    queryKey: qk.copilotSuggestions(lang),
    queryFn: ({ signal }) => copilotSuggestions(lang, signal),
    staleTime: Infinity,
  });
}

/** The signed-in user's own copilot conversations, most recent first. */
export function useCopilotConversations() {
  return useQuery({
    queryKey: qk.copilotConversations(),
    queryFn: ({ signal }) => copilotConversations(signal),
  });
}

/** Stored messages of one conversation (oldest first); idle when `id` is null. */
export function useCopilotMessages(id: number | null) {
  return useQuery({
    queryKey: qk.copilotMessages(id ?? 0),
    queryFn: ({ signal }) => copilotConversationMessages(id ?? 0, signal),
    enabled: id !== null,
  });
}

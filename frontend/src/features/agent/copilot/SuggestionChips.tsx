import { MessageCircleQuestion } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useCopilotSuggestions } from "../../../api/hooks/copilot";
import { Skeleton } from "../../../components/ui/Skeleton";
import { useLocale } from "../../../lib/prefs";

// Placeholder chips about as wide as the served questions (Bangla ones run ~50-90 characters),
// so the chat sheet below does not jump when they arrive.
const PLACEHOLDER_WIDTHS = {
  bn: ["w-80", "w-72", "w-80", "w-72", "w-full"],
  en: ["w-52", "w-44", "w-56", "w-52", "w-80"],
} as const;

/**
 * Suggested questions for the current language. Quiet by design: chip-shaped placeholders while
 * loading, nothing when the call fails. `onPick` gets the suggestion text exactly as served (replay matches
 * exact text only), never trimmed or translated.
 */
export function SuggestionChips({ onPick, disabled = false }: { onPick: (question: string) => void; disabled?: boolean }) {
  const { t } = useTranslation();
  const { lang } = useLocale();
  const q = useCopilotSuggestions(lang);
  const items = q.data?.items ?? [];
  if (q.isPending) {
    return (
      <div role="status" aria-busy="true" aria-label={t("common.loading")} className="flex flex-wrap gap-2 lg:flex-col">
        {PLACEHOLDER_WIDTHS[lang].map((w, i) => (
          <Skeleton key={i} className={`h-9 max-w-full rounded-full lg:h-11 lg:w-full lg:rounded-xl ${w}`} />
        ))}
      </div>
    );
  }
  if (q.isError || items.length === 0) return null;

  return (
    <div role="group" aria-label={t("copilot.suggestions")} data-testid="copilot-suggestions" className="flex flex-wrap gap-2 lg:flex-col">
      {items.map((item) => (
        <button
          key={item}
          type="button"
          disabled={disabled}
          onClick={() => onPick(item)}
          className="ap-press inline-flex min-h-9 items-center gap-1.5 rounded-full border border-line bg-surface-2 px-3 text-left text-small font-semibold text-fg hover:bg-surface-3 disabled:opacity-50 lg:min-h-11 lg:w-full lg:items-start lg:gap-2 lg:rounded-xl lg:py-2.5"
        >
          <MessageCircleQuestion aria-hidden className="size-4 shrink-0 text-pulse-fg lg:mt-0.5" />
          {item}
        </button>
      ))}
    </div>
  );
}

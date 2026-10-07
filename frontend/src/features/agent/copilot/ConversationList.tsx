import { MessageSquarePlus } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useCopilotConversations } from "../../../api/hooks/copilot";
import { LiquidButton } from "../../../components/ui/LiquidButton";
import { Skeleton } from "../../../components/ui/Skeleton";
import { ErrorState } from "../../../components/ui/StatePanel";
import { cn } from "../../../lib/cn";

interface Props {
  activeId: number | null;
  disabled: boolean;
  onSelect: (id: number) => void;
  onNew: () => void;
}

/** The user's saved copilot chats: start a new one or reopen an old one. */
export function ConversationList({ activeId, disabled, onSelect, onNew }: Props) {
  const { t } = useTranslation();
  const q = useCopilotConversations();

  return (
    <section aria-labelledby="copilot-history-title" className="space-y-2" data-testid="copilot-history">
      <div className="flex items-center justify-between gap-2">
        <h2 id="copilot-history-title" className="text-small font-semibold">
          {t("copilot.history.title")}
        </h2>
        <LiquidButton variant="secondary" icon={MessageSquarePlus} onClick={onNew} disabled={disabled} data-testid="copilot-new-chat">
          {t("copilot.history.new")}
        </LiquidButton>
      </div>
      {q.isPending ? (
        <div className="space-y-2" aria-busy="true">
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-full" />
        </div>
      ) : q.isError ? (
        <ErrorState compact body={t("copilot.history.error")} onRetry={() => void q.refetch()} retrying={q.isFetching} />
      ) : q.data.length === 0 ? (
        <p className="text-small text-muted">{t("copilot.history.empty")}</p>
      ) : (
        <ul className="max-h-60 space-y-1 overflow-y-auto">
          {q.data.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                disabled={disabled}
                aria-current={c.id === activeId ? "true" : undefined}
                onClick={() => onSelect(c.id)}
                className={cn(
                  "min-h-9 w-full truncate rounded-[var(--radius-input)] px-3 text-left text-small transition-colors hover:bg-brand/10 disabled:opacity-60",
                  c.id === activeId && "bg-brand/15 font-semibold",
                )}
              >
                {c.title || t("copilot.history.untitled")}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

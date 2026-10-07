import { FileText, Sparkles } from "lucide-react";
import { motion } from "motion/react";
import { useTranslation } from "react-i18next";

import type { CopilotMeta } from "../../../api/services/copilot";
import type { GeneratedBy, LlmText } from "../../../api/types";
import { LangText } from "../../../components/ui/LangText";
import { Skeleton } from "../../../components/ui/Skeleton";
import { cn } from "../../../lib/cn";
import { useReducedMotionPref } from "../../../lib/motionPrefs";
import { wordingKey } from "../../../lib/wording";
import { DUR, tween } from "../../../styles/motion";
import { MiniCard } from "./MiniCards";

export interface Turn {
  id: number;
  question: string;
  meta: CopilotMeta | null;
  /** Deterministic template answer (shown first). */
  draft: string;
  /** Final answer as it streams in. */
  streamed: string;
  final: LlmText | null;
  state: "pending" | "done" | "failed";
}

interface AnswerCardProps {
  turn: Turn;
  onRetry: () => void;
  retryDisabled: boolean;
}

/** One Copilot answer as a mini-card: typing shimmer, template text, then the final wording fades in. */
export function AnswerCard({ turn, onRetry, retryDisabled }: AnswerCardProps) {
  const { t } = useTranslation();
  const reduced = useReducedMotionPref();
  const text = turn.final?.text ?? (turn.streamed || turn.draft);
  const phase = turn.final || turn.streamed ? "final" : "draft";

  return (
    <div data-testid="copilot-answer" className="max-w-[92%] ap-card px-4 py-3 shadow-soft">
      {turn.state === "failed" ? (
        <p role="alert" className="text-small text-act-fg">
          {t("copilot.failed")}{" "}
          <button type="button" onClick={onRetry} disabled={retryDisabled} className="font-semibold underline disabled:opacity-50">
            {t("common.retry")}
          </button>
        </p>
      ) : text ? (
        <motion.p
          key={phase}
          initial={phase === "draft" ? false : { opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={tween(reduced ? DUR.fast : DUR.slow)}
          className={cn("whitespace-pre-line text-body", turn.state === "pending" && phase === "draft" && "text-muted")}
        >
          <LangText text={text} />
        </motion.p>
      ) : (
        <TypingShimmer />
      )}
      {turn.state === "pending" && text ? <TypingShimmer compact /> : null}
      {turn.final ? <WordingLabel by={turn.final.generated_by} noApiKey={turn.final.no_api_key} /> : null}
      {turn.state === "done" && turn.meta ? <MiniCard meta={turn.meta} /> : null}
    </div>
  );
}

function TypingShimmer({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation();
  return (
    <div role="status" data-testid="copilot-typing" className={cn("space-y-2", compact ? "mt-2" : "py-1")}>
      {compact ? null : <Skeleton className="h-3.5 w-11/12" />}
      <Skeleton className={cn("h-3.5", compact ? "w-16" : "w-2/3")} />
      <span className="sr-only">{t("copilot.typing")}</span>
    </div>
  );
}

function WordingLabel({ by, noApiKey }: { by: GeneratedBy; noApiKey: boolean }) {
  const { t } = useTranslation();
  const Icon = by === "template" ? FileText : Sparkles;
  return (
    <span
      data-generated-by={by}
      className={cn(
        "mt-2 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold",
        by === "template" ? "bg-surface-2 text-muted" : "bg-brand/20 text-fg",
      )}
    >
      <Icon aria-hidden className="size-3.5" />
      {t(wordingKey(by, noApiKey))}
    </span>
  );
}

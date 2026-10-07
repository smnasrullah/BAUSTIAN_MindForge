import { FileText, Sparkles } from "lucide-react";
import { motion } from "motion/react";
import { useTranslation } from "react-i18next";

import type { GeneratedBy, LlmText } from "../../../api/types";
import { PulseLine } from "../../../components/signature/PulseLine";
import { LangText } from "../../../components/ui/LangText";
import { cn } from "../../../lib/cn";
import { useReducedMotionPref } from "../../../lib/motionPrefs";
import { wordingKey } from "../../../lib/wording";
import { DUR, tween } from "../../../styles/motion";

interface WordingBlockProps {
  /** Deterministic sentence shown at once. */
  templateText: string;
  narration: LlmText | undefined;
  pending: boolean;
}

/** Template text first; LLM wording fades in over it with its own "AI-generated wording" chip. */
export function WordingBlock({ templateText, narration, pending }: WordingBlockProps) {
  const { t } = useTranslation();
  const reduced = useReducedMotionPref();
  const ai = narration && narration.generated_by !== "template" ? narration : null;
  const by: GeneratedBy = ai ? ai.generated_by : "template";
  const text = ai?.text ?? (narration?.template_text || templateText);
  const Icon = ai ? Sparkles : FileText;

  return (
    <div className="ap-card p-4 shadow-soft">
      <div aria-live="polite">
        {/* Keyed: the new wording replaces the template at once and fades in over it. */}
        <motion.div
          key={`${by}-${text}`}
          initial={by === "template" ? false : { opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={tween(reduced ? DUR.fast : DUR.reveal)}
        >
          <p className="text-body leading-relaxed">
            <LangText text={text} />
          </p>
          <span
            data-testid="wording-chip"
            data-generated-by={by}
            className={cn(
              "mt-3 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold",
              ai ? "bg-brand/20 text-fg" : "bg-surface-2 text-muted",
            )}
          >
            <Icon aria-hidden className="size-3.5" />
            {t(wordingKey(by, narration?.no_api_key))}
          </span>
        </motion.div>
      </div>
      {pending && !narration ? (
        <p className="mt-3 flex items-center gap-2 text-xs text-muted">
          <span className="block h-4 w-10 shrink-0 overflow-hidden">
            <PulseLine className="-mt-2" />
          </span>
          {t("why.writing")}
        </p>
      ) : null}
    </div>
  );
}

import { Cpu, FileText, Sparkles, TrendingDown, TrendingUp } from "lucide-react";
import { motion } from "motion/react";
import { useRef } from "react";
import { useTranslation } from "react-i18next";

import type { GeneratedBy, Reason } from "../../api/types";
import { cn } from "../../lib/cn";
import { LangText } from "../ui/LangText";
import { formatPercent } from "../../lib/format";
import { useOnScreen, useReducedMotionPref } from "../../lib/motionPrefs";
import { wordingKey } from "../../lib/wording";
import { useLocale } from "../../lib/prefs";
import { DUR, listStagger, revealVariants, STAGGER, tween } from "../../styles/motion";
import { MoneyText } from "../ui/MoneyText";

interface WhyStonesProps {
  reasons: Reason[];
  /** Who wrote the sentences: kept visually apart from the model chip. */
  generatedBy: GeneratedBy;
  /** Template wording is served because no API key is set (from the narration response). */
  noApiKey?: boolean;
  modelVersion: string;
  className?: string;
}

const STONE_SHAPES = ["22px 16px 24px 18px", "16px 24px 18px 22px", "24px 18px 16px 24px"];

/** Reasons as stacked "because" stones with SHAP bars growing in. */
export function WhyStones({ reasons, generatedBy, noApiKey, modelVersion, className }: WhyStonesProps) {
  const { t } = useTranslation();
  const { digits } = useLocale();
  const reduced = useReducedMotionPref();
  const ref = useRef<HTMLDivElement>(null);
  const seen = useOnScreen(ref, true);
  const WordingIcon = generatedBy === "template" ? FileText : Sparkles;

  return (
    <div ref={ref} className={cn("ap-card p-4 shadow-soft", className)}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-display text-h2 font-bold">{t("why.title")}</p>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-pulse/12 px-2.5 py-1 text-xs font-semibold text-pulse-fg">
          <Cpu aria-hidden className="size-3.5" />
          {t("why.model")}
          <span className="num font-normal">{modelVersion}</span>
        </span>
      </div>

      <motion.ol variants={listStagger} initial="hidden" animate={seen ? "show" : "hidden"} className="mt-4 space-y-2.5">
        {reasons.map((r, i) => {
          const up = r.direction === "up";
          const Icon = up ? TrendingUp : TrendingDown;
          return (
            <motion.li
              key={r.factor}
              variants={revealVariants(reduced)}
              className="border border-line bg-surface-2 p-3.5"
              style={{
                borderRadius: STONE_SHAPES[i % STONE_SHAPES.length],
                marginLeft: reduced ? 0 : (i % 2) * 8,
                marginRight: reduced ? 0 : ((i + 1) % 2) * 8,
              }}
            >
              <p className="text-body">
                <LangText text={r.sentence} />
              </p>
              <div className="mt-2.5 flex items-center gap-3">
                <Icon aria-hidden className={cn("size-4 shrink-0", up ? "text-watch-fg" : "text-safe-fg")} />
                <span className="sr-only">{t(up ? "why.up" : "why.down")}</span>
                <span className="relative h-2 flex-1 overflow-hidden rounded-full bg-line" aria-hidden>
                  <motion.span
                    className={cn("absolute inset-y-0 left-0 w-full origin-left rounded-full", up ? "bg-watch" : "bg-safe")}
                    initial={{ scaleX: 0 }}
                    animate={{ scaleX: seen ? Math.min(1, Math.max(0.02, r.share)) : 0 }}
                    transition={reduced ? { duration: 0 } : tween(DUR.reveal, DUR.base + i * STAGGER)}
                  />
                </span>
                <MoneyText value={r.impact} signed compact className="text-xs font-semibold" />
                <span className="num w-10 text-right text-xs text-muted" title={t("why.share", { share: formatPercent(r.share, digits) })}>
                  {formatPercent(r.share, digits)}
                </span>
              </div>
            </motion.li>
          );
        })}
      </motion.ol>

      <div className="mt-4 border-t border-dashed border-line pt-3">
        <span
          data-generated-by={generatedBy}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold",
            generatedBy === "template" ? "bg-surface-2 text-muted" : "bg-brand/20 text-fg",
          )}
        >
          <WordingIcon aria-hidden className="size-3.5" />
          {t(wordingKey(generatedBy, noApiKey))}
        </span>
      </div>
    </div>
  );
}

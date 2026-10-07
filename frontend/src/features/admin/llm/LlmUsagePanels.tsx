import { motion } from "motion/react";
import { useTranslation } from "react-i18next";

import { useLlmStatus } from "../../../api/hooks/system";
import type { LlmUsage } from "../../../api/types";
import { SkeletonText } from "../../../components/ui/Skeleton";
import { StatChip } from "../../../components/ui/StatChip";
import { ErrorState } from "../../../components/ui/StatePanel";
import { TimeText } from "../../../components/ui/TimeText";
import { cn } from "../../../lib/cn";
import { formatNumber, formatPercent, localizeDigits } from "../../../lib/format";
import { useReducedMotionPref } from "../../../lib/motionPrefs";
import { useLocale } from "../../../lib/prefs";
import { DUR, STAGGER, tween } from "../../../styles/motion";
import { Badge, Facts, Panel } from "../shared/ui";
import { capShare, dayBars, SERIES, type Series } from "./usageModel";

const SERIES_TONE: Record<Series, string> = { live: "bg-pulse", cache: "bg-emoney", replay: "bg-cash", template: "bg-ink-600" };

export function ProviderPanel() {
  const { t } = useTranslation();
  const { digits } = useLocale();
  const q = useLlmStatus();
  return (
    <Panel title={t("admin.llm.status.title")} aside={q.data ? <Badge tone={q.data.live ? "good" : "neutral"}>{t(`llmMode.${q.data.mode}`)}</Badge> : null} testId="llm-provider">
      {q.isPending ? (
        <SkeletonText lines={5} />
      ) : q.isError ? (
        <ErrorState compact onRetry={() => void q.refetch()} retrying={q.isFetching} />
      ) : (
        <Facts
          rows={[
            [t("admin.llm.status.configured"), <span key="c" className="font-mono text-xs">{q.data.configured}</span>],
            [t("admin.llm.status.mode"), t(`llmMode.${q.data.mode}`)],
            [t("admin.llm.status.model"), <span key="m" className="font-mono text-xs">{q.data.model ?? "—"}</span>],
            [t("admin.llm.status.key"), <Badge key="k" tone={q.data.key_configured ? "good" : "neutral"}>{t(q.data.key_configured ? "admin.llm.status.keySet" : "admin.llm.status.keyMissing")}</Badge>],
            [
              t("admin.llm.status.replay"),
              <span key="r" data-testid="replay-row">
                {formatNumber(q.data.replay_entries, digits)}
                {q.data.replay_skipped ? <span className="mt-1 block text-xs text-muted">{t("admin.llm.status.replaySkipped")}</span> : null}
              </span>,
            ],
            [t("admin.llm.status.perUser"), t("admin.llm.status.perUserValue", { count: q.data.user_calls_per_min })],
            [
              t("admin.llm.status.lastError"),
              q.data.last_error ? (
                <span key="e" className="text-xs">
                  <span className="font-mono text-act-fg">{q.data.last_error}</span>
                  {q.data.last_error_at ? (
                    <>
                      {" · "}
                      <TimeText at={q.data.last_error_at} mode="relative" />
                    </>
                  ) : null}
                </span>
              ) : (
                t("admin.common.none")
              ),
            ],
          ]}
        />
      )}
    </Panel>
  );
}

export function CapPanel({ u }: { u: LlmUsage }) {
  const { t } = useTranslation();
  const { digits } = useLocale();
  const reduced = useReducedMotionPref();
  const share = capShare(u);
  const tone = share >= 1 ? "bg-act" : share >= 0.8 ? "bg-watch" : "bg-safe";
  return (
    <Panel
      title={t("admin.llm.cap.title")}
      aside={<Badge tone={share >= 1 ? "bad" : share >= 0.8 ? "warn" : "good"}>{formatPercent(Math.min(share, 1), digits)}</Badge>}
      testId="llm-cap"
    >
      <p className="num text-small">{t("admin.llm.cap.body", { used: formatNumber(u.calls_today, digits), cap: formatNumber(u.daily_cap, digits) })}</p>
      <div
        role="meter"
        aria-label={t("admin.llm.cap.title")}
        aria-valuemin={0}
        aria-valuemax={u.daily_cap}
        aria-valuenow={Math.min(u.calls_today, u.daily_cap)}
        className="mt-3 h-3 overflow-hidden rounded-full bg-surface-2"
      >
        <motion.span
          className={cn("block h-full origin-left rounded-full", tone)}
          initial={{ scaleX: reduced ? Math.min(share, 1) : 0 }}
          animate={{ scaleX: Math.min(share, 1) }}
          transition={reduced ? { duration: 0 } : tween(DUR.reveal)}
        />
      </div>
      <p className="mt-2 text-xs text-muted">{t("admin.llm.cap.hint")}</p>
    </Panel>
  );
}

export function UsagePanel({ u }: { u: LlmUsage }) {
  const { t } = useTranslation();
  const { digits } = useLocale();
  const reduced = useReducedMotionPref();
  const bars = dayBars(u);
  const max = Math.max(1, ...bars.map((b) => b.total));
  const ms = (v: number | null) => (v === null ? "—" : t("admin.llm.usage.ms", { value: formatNumber(v, digits) }));
  return (
    <Panel title={t("admin.llm.usage.title")} testId="llm-usage">
      <div className="flex flex-wrap gap-2">
        <StatChip label={t("admin.llm.usage.calls")} value={formatNumber(u.total_calls, digits)} />
        <StatChip label={t("admin.llm.usage.cacheHit")} value={u.cache_hit_rate === null ? "—" : formatPercent(u.cache_hit_rate, digits)} />
        <StatChip label={t("admin.llm.usage.latency")} value={ms(u.avg_latency_ms)} />
        <StatChip label={t("admin.llm.usage.p95")} value={ms(u.p95_latency_ms)} />
        <StatChip label={t("admin.llm.usage.guardFails")} value={formatNumber(u.guard_failures, digits)} />
      </div>
      <figure className="mt-4">
        <figcaption className="sr-only">{t("admin.llm.usage.chart")}</figcaption>
        <ol className="flex h-36 items-end gap-2" data-testid="usage-bars">
          {bars.map((b, i) => (
            <li key={b.day} className="flex h-full flex-1 flex-col items-center justify-end gap-1" data-total={b.total}>
              <span className="num text-[11px] text-muted">{formatNumber(b.total, digits)}</span>
              <motion.span
                className="flex w-full max-w-10 flex-col-reverse overflow-hidden rounded-md bg-surface-2"
                style={{ height: `${(b.total / max) * 100}%`, minHeight: 2, originY: 1 }}
                initial={{ scaleY: reduced ? 1 : 0 }}
                animate={{ scaleY: 1 }}
                transition={reduced ? { duration: 0 } : tween(DUR.reveal, i * STAGGER)}
              >
                {SERIES.map((s) =>
                  b.parts[s] > 0 ? <span key={s} className={SERIES_TONE[s]} style={{ height: `${(b.parts[s] / b.total) * 100}%` }} title={`${t(`admin.llm.series.${s}`)}: ${b.parts[s]}`} /> : null,
                )}
              </motion.span>
              <span className="num text-[11px] text-muted">{localizeDigits(b.day.slice(5), digits)}</span>
            </li>
          ))}
        </ol>
        <ul className="mt-3 flex flex-wrap gap-3 text-xs text-muted">
          {SERIES.map((s) => (
            <li key={s} className="inline-flex items-center gap-1.5">
              <span aria-hidden className={cn("size-2.5 rounded-sm", SERIES_TONE[s])} />
              {t(`admin.llm.series.${s}`)}
            </li>
          ))}
        </ul>
      </figure>
    </Panel>
  );
}

import { Play } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { useAdminClock, useRunTick } from "../../../api/hooks/admin";
import type { AdminClock } from "../../../api/types";
import { LiquidButton } from "../../../components/ui/LiquidButton";
import { SkeletonPanel } from "../../../components/ui/Skeleton";
import { ErrorState } from "../../../components/ui/StatePanel";
import { TimeText } from "../../../components/ui/TimeText";
import { toast } from "../../../components/ui/toastStore";
import { formatNumber, localizeDigits } from "../../../lib/format";
import { useLocale } from "../../../lib/prefs";
import { Badge, Panel } from "../shared/ui";

/** The daily impact backtest runs as its own job (live clock), not inside the hourly tick. */
function BacktestValue({ c }: { c: AdminClock }) {
  const { t } = useTranslation();
  const { digits } = useLocale();
  const job = c.backtest;
  if (!job) return <span data-testid="clock-backtest">{t("admin.clock.backtestNone")}</span>;
  const seconds = (job.duration_s ?? 0).toFixed(1);
  const text =
    job.state === "running"
      ? t("admin.clock.backtestRunning")
      : t(job.state === "ok" ? "admin.clock.backtestOk" : "admin.clock.backtestFailed", { seconds });
  return (
    <span className="num" data-testid="clock-backtest">
      {job.state === "failed" ? <Badge tone="warn">{localizeDigits(text, digits)}</Badge> : localizeDigits(text, digits)}
      {job.last_run_at && job.state !== "running" ? (
        <span className="block text-xs font-normal text-muted">
          <TimeText at={job.last_run_at} mode="relative" />
        </span>
      ) : null}
      {job.over_budget ? (
        <span className="ml-2">
          <Badge tone="warn">{localizeDigits(t("admin.clock.overBudget", { budget: job.budget_s }), digits)}</Badge>
        </span>
      ) : null}
    </span>
  );
}

function Rows({ c }: { c: AdminClock }) {
  const { t } = useTranslation();
  const { digits } = useLocale();
  const tick = c.last_tick;
  const catchup = c.catchup
    ? c.catchup.state === "regenerating"
      ? t("admin.clock.catchupRegen")
      : t("admin.clock.catchupRunning", { done: formatNumber(c.catchup.hours_done, digits) })
    : t("admin.clock.catchupIdle");
  const backtest: [string, ReactNode][] =
    c.clock.mode === "live" ? [[t("admin.clock.backtest"), <BacktestValue key="bt" c={c} />]] : [];
  const rows: [string, ReactNode][] = [
    [t("admin.clock.now"), <TimeText key="now" at={c.clock.now} mode="datetime" />],
    [t("admin.clock.dataHour"), <TimeText key="dh" at={c.clock.data_hour} mode="datetime" />],
    [
      t("admin.clock.lastCompute"),
      c.clock.last_compute_at ? <TimeText key="lc" at={c.clock.last_compute_at} mode="relative" /> : "—",
    ],
    [
      t("admin.clock.lastTick"),
      tick ? (
        <span key="lt" className="num">
          {localizeDigits(t("admin.clock.lastTickValue", { hours: tick.hours, seconds: tick.duration_s.toFixed(1) }), digits)}
          {c.over_budget ? (
            <span className="ml-2">
              <Badge tone="warn">{localizeDigits(t("admin.clock.overBudget", { budget: c.budget_s }), digits)}</Badge>
            </span>
          ) : null}
        </span>
      ) : (
        t("admin.clock.noTick")
      ),
    ],
    [t("admin.clock.nextTick"), c.next_tick_at ? <TimeText key="nt" at={c.next_tick_at} mode="relative" /> : "—"],
    [t("admin.clock.catchup"), catchup],
    ...backtest,
    [
      t("admin.clock.story"),
      c.demo_story ? (
        <span key="st">
          {t("admin.clock.storyValue", { agent: c.demo_story.agent_code })} <TimeText at={c.demo_story.stockout_at} mode="datetime" />
          {c.demo_story.demo_event ? <span className="block text-xs font-normal text-muted">{t("admin.clock.demoEvent")}</span> : null}
        </span>
      ) : (
        t("admin.clock.noStory")
      ),
    ],
  ];
  return (
    <dl className="space-y-1 text-small">
      {rows.map(([k, v]) => (
        <div key={k} className="flex min-h-9 items-center justify-between gap-3 border-b border-line">
          <dt className="text-muted">{k}</dt>
          <dd className="text-right font-semibold">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Admin overview: which clock the data follows, the last and next tick, and "Run tick now". */
export function DataClockPanel() {
  const { t } = useTranslation();
  const { digits } = useLocale();
  const q = useAdminClock();
  const run = useRunTick();
  if (q.isPending) return <SkeletonPanel rows={6} />;
  if (q.isError) return <ErrorState compact onRetry={() => void q.refetch()} retrying={q.isFetching} />;
  const c = q.data;
  const live = c.clock.mode === "live";
  const requested = Boolean(c.tick_requested_at);
  const onRun = () =>
    run.mutate(undefined, {
      onSuccess: () => toast({ tone: "success", title: t("admin.clock.requested") }),
      onError: () => toast({ tone: "error", title: t("admin.clock.runFailed") }),
    });
  return (
    <Panel
      title={t("admin.clock.title")}
      aside={
        <Badge tone={live ? "good" : "neutral"} testId="clock-mode">
          {t(live ? "admin.clock.live" : "admin.clock.fixed")}
        </Badge>
      }
      testId="data-clock-panel"
    >
      <p className="mb-2 text-xs text-muted">{t(live ? "freshness.mode.live" : "admin.clock.fixedNote")}</p>
      <Rows c={c} />
      {c.skipped_ticks ? (
        <p className="mt-2 text-xs text-muted" role="status">
          {localizeDigits(t("admin.clock.skipped", { count: c.skipped_ticks }), digits)}
        </p>
      ) : null}
      {c.last_error ? (
        <p className="mt-2 text-xs text-act-fg" role="status">
          {t("admin.clock.error")}: <span className="font-mono">{c.last_error}</span>
        </p>
      ) : null}
      {live ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <LiquidButton variant="secondary" size="sm" icon={Play} loading={run.isPending} onClick={onRun} data-testid="run-tick">
            {t("admin.clock.runTick")}
          </LiquidButton>
          {requested ? <span className="text-xs text-muted">{t("admin.clock.pending")}</span> : null}
        </div>
      ) : null}
    </Panel>
  );
}

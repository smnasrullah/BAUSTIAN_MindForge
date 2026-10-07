import { Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useJobs, useStartJob } from "../../../api/hooks/admin";
import type { JobKind, JobOut, JobStatus } from "../../../api/types";
import { ConfirmDialog } from "../../../components/ui/ConfirmDialog";
import { LiquidButton } from "../../../components/ui/LiquidButton";
import { SkeletonText } from "../../../components/ui/Skeleton";
import { ErrorState } from "../../../components/ui/StatePanel";
import { TimeText } from "../../../components/ui/TimeText";
import { toast } from "../../../components/ui/toastStore";
import { formatPercent } from "../../../lib/format";
import { useLocale } from "../../../lib/prefs";
import { errorCode } from "../../../lib/apiError";
import { stepParts } from "./jobModel";
import { Badge, type Tone } from "./ui";
import { useSingleFlight } from "../../../lib/useSingleFlight";

export interface JobAction {
  kind: JobKind;
  label: string;
  confirmTitle: string;
  confirmBody: string;
  confirmLabel: string;
}

const STATUS_TONE: Record<JobStatus, Tone> = { queued: "neutral", running: "warn", succeeded: "good", failed: "bad" };

export function JobStatusBadge({ status }: { status: JobStatus }) {
  const { t } = useTranslation();
  return (
    <Badge tone={STATUS_TONE[status]} testId="job-status">
      {t(`admin.jobs.status.${status}`)}
    </Badge>
  );
}

function StepText({ step }: { step: string }) {
  const { t } = useTranslation();
  const { key, detail } = stepParts(step);
  return (
    <span>
      {key ? t(`admin.jobs.step.${key}`) : step}
      {detail ? <span className="num ml-1 text-muted">{detail}</span> : null}
    </span>
  );
}

function JobCard({ job }: { job: JobOut }) {
  const { t } = useTranslation();
  const { digits } = useLocale();
  const active = job.status === "queued" || job.status === "running";
  return (
    <div className="rounded-2xl border border-line bg-surface-2/60 p-4 text-small" data-testid="job-card" data-status={job.status}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-semibold">{t(`admin.jobs.kind.${job.kind}`)}</p>
        <JobStatusBadge status={job.status} />
      </div>
      {active ? (
        <div className="mt-3">
          <div className="flex items-center justify-between gap-2 text-xs">
            <StepText step={job.step} />
            <span className="num font-semibold">{formatPercent(job.progress / 100, digits)}</span>
          </div>
          <div
            role="progressbar"
            aria-label={t("admin.jobs.progress")}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={job.progress}
            className="mt-1.5 h-2.5 overflow-hidden rounded-full bg-surface-3"
          >
            <span
              className="block h-full origin-left rounded-full bg-pulse transition-transform duration-300 ease-[cubic-bezier(.2,.8,.2,1)]"
              style={{ transform: `scaleX(${job.progress / 100})` }}
            />
          </div>
        </div>
      ) : null}
      {job.status === "failed" ? (
        <p role="alert" className="mt-2 break-words text-xs text-act-fg">
          {job.error === "interrupted" ? t("admin.jobs.interrupted") : job.error}
        </p>
      ) : null}
      {job.status === "succeeded" && job.result.length > 0 ? (
        <dl className="mt-2 grid gap-x-4 gap-y-0.5 text-xs sm:grid-cols-2">
          {job.result.map((r) => (
            <div key={r.key} className="flex justify-between gap-2 border-b border-line py-1">
              <dt className="font-mono text-muted">{r.key}</dt>
              <dd className="num break-all text-right font-semibold">{r.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      <p className="mt-2 text-xs text-muted">
        {job.started_by_email ? t("admin.jobs.startedBy", { email: job.started_by_email }) : null}
        {" · "}
        <TimeText at={job.finished_at ?? job.updated_at} mode="datetime" />
      </p>
    </div>
  );
}

/** Start buttons (confirm first) plus the running or latest job of these kinds, polled live. */
export function JobPanel({ actions }: { actions: JobAction[] }) {
  const { t } = useTranslation();
  const jobs = useJobs();
  const start = useStartJob();
  const [pending, setPending] = useState<JobAction | null>(null);
  const kinds = actions.map((a) => a.kind);
  const running = jobs.data?.running ?? null;
  const shown = running ?? jobs.data?.items.find((j) => kinds.includes(j.kind)) ?? null;

  // Toast once when the job this page watched finishes.
  const watched = useRef<number | null>(null);
  useEffect(() => {
    if (running) {
      watched.current = running.id;
      return;
    }
    const id = watched.current;
    if (id === null) return;
    watched.current = null;
    const done = jobs.data?.items.find((j) => j.id === id);
    if (!done) return;
    const kind = t(`admin.jobs.kind.${done.kind}`);
    if (done.status === "succeeded") toast({ tone: "success", title: t("admin.jobs.succeeded", { kind }) });
    if (done.status === "failed") toast({ tone: "error", title: t("admin.jobs.failed", { kind }), body: done.error ?? undefined });
  }, [running, jobs.data, t]);

  const once = useSingleFlight();
  function confirm() {
    if (!pending) return;
    const kind = pending.kind;
    once((done) =>
      start.mutate(kind, {
        onSuccess: () => toast({ tone: "info", title: t("admin.jobs.started") }),
        onError: (err) => toast({ tone: "error", title: t(errorCode(err) === "job_running" ? "admin.jobs.busy" : "admin.jobs.startFailed") }),
        onSettled: () => {
          setPending(null);
          done();
        },
      }),
    );
  }

  return (
    <div className="space-y-3" data-testid="job-panel">
      <div className="flex flex-wrap gap-2">
        {actions.map((a) => (
          <LiquidButton
            key={a.kind}
            variant="secondary"
            size="sm"
            icon={Play}
            disabled={running !== null || jobs.isPending}
            onClick={() => setPending(a)}
            data-testid={`start-${a.kind}`}
          >
            {a.label}
          </LiquidButton>
        ))}
      </div>
      {running && !kinds.includes(running.kind) ? <p className="text-xs text-muted">{t("admin.jobs.busy")}</p> : null}
      {jobs.isPending ? (
        <SkeletonText lines={2} />
      ) : jobs.isError ? (
        <ErrorState compact onRetry={() => void jobs.refetch()} retrying={jobs.isFetching} />
      ) : shown ? (
        <JobCard job={shown} />
      ) : (
        <p className="text-small text-muted">{t("admin.jobs.none")}</p>
      )}
      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => (open ? undefined : setPending(null))}
        title={pending?.confirmTitle ?? ""}
        description={pending?.confirmBody ?? ""}
        confirmLabel={pending?.confirmLabel ?? ""}
        pending={start.isPending}
        onConfirm={confirm}
      />
    </div>
  );
}

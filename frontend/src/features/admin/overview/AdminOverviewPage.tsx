import { ArrowLeftRight, Bot, Boxes, Database, HandCoins, ScanSearch, ScrollText, Users } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { useAdminOverview } from "../../../api/hooks/admin";
import { useSystemStatus } from "../../../api/hooks/system";
import type { AdminOverview, SystemStatus } from "../../../api/types";
import { BentoTile } from "../../../components/signature/BentoTile";
import { SkeletonCard, SkeletonPanel } from "../../../components/ui/Skeleton";
import { StaggerGroup, StaggerItem, StaggerList } from "../../../components/ui/Stagger";
import { EmptyState, ErrorState } from "../../../components/ui/StatePanel";
import { TimeText } from "../../../components/ui/TimeText";
import { formatNumber, localizeDigits } from "../../../lib/format";
import { useLocale } from "../../../lib/prefs";
import { JobStatusBadge } from "../shared/JobPanel";
import { knownModel } from "../shared/jobModel";
import { AdminHeader, Badge, Panel } from "../shared/ui";
import { DataClockPanel } from "./DataClockPanel";

const LINK = "inline-flex min-h-11 items-center gap-1.5 text-small font-semibold text-pulse-fg hover:underline";

function HealthPanel({ s }: { s: SystemStatus }) {
  const { t } = useTranslation();
  const { digits } = useLocale();
  const ok = (good: boolean) => <Badge tone={good ? "good" : "bad"}>{t(good ? "admin.overview.ok" : "admin.overview.problem")}</Badge>;
  const migrated = s.migration_current !== null && s.migration_current === s.migration_head;
  const rows: [string, ReactNode][] = [
    [t("admin.overview.db"), ok(s.db)],
    [
      t("admin.overview.migrations"),
      <span key="m" className="inline-flex items-center gap-2">
        <span className="num text-xs text-muted">
          {localizeDigits(t("admin.overview.migrationsValue", { current: s.migration_current ?? "—", head: s.migration_head ?? "—" }), digits)}
        </span>
        {ok(migrated)}
      </span>,
    ],
    [t("admin.overview.artifacts"), ok(s.artifacts_ok)],
    [t("admin.overview.bootstrap"), <span key="b" className="font-mono text-xs">{s.bootstrap_state}</span>],
    [t("admin.overview.llmMode"), t(`llmMode.${s.llm_mode}`)],
    [t("admin.overview.demoMode"), <Badge key="d" tone="neutral">{t(s.demo_mode ? "admin.overview.on" : "admin.overview.off")}</Badge>],
  ];
  return (
    <Panel
      title={t("admin.overview.health")}
      aside={<Badge tone={s.ready ? "good" : "bad"} testId="system-ready">{t(s.ready ? "admin.overview.ready" : "admin.overview.notReady")}</Badge>}
      testId="health-panel"
    >
      <dl className="space-y-1 text-small">
        {rows.map(([k, v]) => (
          <div key={k} className="flex min-h-9 items-center justify-between gap-3 border-b border-line">
            <dt className="text-muted">{k}</dt>
            <dd className="text-right font-semibold">{v}</dd>
          </div>
        ))}
      </dl>
      {s.data_version ? (
        <p className="num mt-2 text-xs text-muted">{localizeDigits(t("admin.overview.dataVersion", { version: s.data_version, seed: s.seed ?? "—" }), digits)}</p>
      ) : null}
    </Panel>
  );
}

function Tiles({ o }: { o: AdminOverview }) {
  const { t } = useTranslation();
  const { digits } = useLocale();
  const active = o.users.reduce((n, r) => n + r.active, 0);
  return (
    <StaggerGroup className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" data-testid="overview-tiles">
      <BentoTile
        title={t("admin.overview.tile.users")}
        value={active}
        icon={Users}
        footer={
          <ul className="space-y-0.5 text-xs text-muted">
            {o.users.map((r) => (
              <li key={r.role} className="num">
                {t(`role.${r.role}`)}: {t("admin.overview.roleCount", { active: formatNumber(r.active, digits), total: formatNumber(r.total, digits) })}
              </li>
            ))}
          </ul>
        }
      />
      <BentoTile title={t("admin.overview.tile.agents")} value={o.agents} icon={Database} />
      <BentoTile title={t("admin.overview.tile.anomalies")} value={o.open_anomalies} icon={ScanSearch} tone={o.open_anomalies > 0 ? "amber" : undefined} />
      <BentoTile title={t("admin.overview.tile.swaps")} value={o.pending_swaps} icon={ArrowLeftRight} />
      <BentoTile title={t("admin.overview.tile.requests")} value={o.open_requests} icon={HandCoins} />
      <BentoTile
        title={t("admin.overview.tile.llm")}
        value={o.llm_calls_today}
        icon={Bot}
        tone={o.llm_calls_today >= o.llm_daily_cap ? "red" : undefined}
        footer={<p className="num text-xs text-muted">{t("admin.overview.llmCap", { cap: formatNumber(o.llm_daily_cap, digits) })}</p>}
      />
    </StaggerGroup>
  );
}

function ModelsAndJob({ o }: { o: AdminOverview }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const modelLabel = (name: string) => {
    const known = knownModel(name);
    return known ? t(`admin.models.name.${known}`) : name;
  };
  const job = o.latest_job;
  return (
    <Panel title={t("admin.overview.models")} testId="overview-models">
      {o.active_models.length === 0 ? (
        <EmptyState
          compact
          illustration="quiet-pulse"
          title={t("admin.overview.noModels")}
          action={{ label: t("admin.overview.openModels"), icon: Boxes, onClick: () => navigate("/admin/models") }}
        />
      ) : (
        <StaggerList className="space-y-2 text-small">
          {o.active_models.map((m) => (
            <StaggerItem key={m.model_name} className="flex flex-wrap items-center justify-between gap-2 border-b border-line pb-2">
              <span>
                <span className="block font-semibold">{modelLabel(m.model_name)}</span>
                <span className="num text-xs text-muted">{m.version}</span>
              </span>
              <span className="text-xs text-muted">
                {t("admin.overview.trainedAt")} <TimeText at={m.trained_at} mode="datetime" />
              </span>
            </StaggerItem>
          ))}
        </StaggerList>
      )}
      <h3 className="mt-4 text-small font-semibold">{t("admin.overview.latestJob")}</h3>
      {job ? (
        <p className="mt-1 flex flex-wrap items-center gap-2 text-small">
          {t(`admin.jobs.kind.${job.kind}`)}
          <JobStatusBadge status={job.status} />
          <TimeText at={job.finished_at ?? job.updated_at} mode="relative" className="text-xs text-muted" />
        </p>
      ) : (
        <p className="mt-1 text-small text-muted">{t("admin.overview.noJob")}</p>
      )}
      <Link to="/admin/data" className={LINK}>
        <Database aria-hidden className="size-4" />
        {t("admin.overview.openData")}
      </Link>
    </Panel>
  );
}

function RecentAudit({ o }: { o: AdminOverview }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  return (
    <Panel title={t("admin.overview.recent")} testId="overview-audit">
      {o.recent_audit.length === 0 ? (
        <EmptyState
          compact
          title={t("admin.overview.noAudit")}
          action={{ label: t("admin.overview.openAudit"), icon: ScrollText, onClick: () => navigate("/admin/audit-log") }}
        />
      ) : (
        <StaggerList className="divide-y divide-line text-small">
          {o.recent_audit.map((a) => (
            <StaggerItem key={a.id} className="flex flex-wrap items-baseline justify-between gap-2 py-2">
              <span className="min-w-0">
                <span className="font-mono text-xs">{a.action}</span>
                <span className="block truncate text-xs text-muted">{a.user_email ?? t("admin.audit.system")}</span>
              </span>
              <TimeText at={a.created_at} mode="relative" className="text-xs text-muted" />
            </StaggerItem>
          ))}
        </StaggerList>
      )}
      <Link to="/admin/audit-log" className={LINK}>
        <ScrollText aria-hidden className="size-4" />
        {t("admin.overview.openAudit")}
      </Link>
    </Panel>
  );
}

/** /admin: system health, work queues, active models, the latest job and recent decisions. */
export function AdminOverviewPage() {
  const { t } = useTranslation();
  const overview = useAdminOverview();
  const status = useSystemStatus();
  return (
    <div className="space-y-4" data-testid="admin-overview">
      <AdminHeader title={t("admin.overview.title")} lead={t("admin.overview.lead")} />
      {overview.isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-busy="true">
          {Array.from({ length: 6 }, (_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      ) : overview.isError ? (
        <ErrorState onRetry={() => void overview.refetch()} retrying={overview.isFetching} />
      ) : (
        <Tiles o={overview.data} />
      )}
      <div className="grid gap-4 lg:grid-cols-3">
        {status.isPending ? (
          <SkeletonPanel rows={6} />
        ) : status.isError ? (
          <ErrorState compact onRetry={() => void status.refetch()} retrying={status.isFetching} />
        ) : (
          <HealthPanel s={status.data} />
        )}
        {overview.data ? (
          <ModelsAndJob o={overview.data} />
        ) : overview.isPending ? (
          <SkeletonPanel rows={4} />
        ) : null}
        {overview.data ? (
          <RecentAudit o={overview.data} />
        ) : overview.isPending ? (
          <SkeletonPanel rows={4} />
        ) : null}
        <DataClockPanel />
      </div>
    </div>
  );
}

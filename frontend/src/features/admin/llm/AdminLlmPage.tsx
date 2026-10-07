import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";

import { useLlmLogs, useLlmUsage } from "../../../api/hooks/admin";
import type { GeneratedBy, GuardResult, LlmIntent, LlmLogItem, LlmLogQuery } from "../../../api/types";
import { DataTable, type Column } from "../../../components/ui/DataTable";
import { Pagination } from "../../../components/ui/Pagination";
import { SkeletonPanel } from "../../../components/ui/Skeleton";
import { ErrorState } from "../../../components/ui/StatePanel";
import { TimeText } from "../../../components/ui/TimeText";
import { formatNumber } from "../../../lib/format";
import { useLocale } from "../../../lib/prefs";
import { DriftPanel } from "../shared/DriftPanel";
import { AdminHeader, Badge, FilterSelect, Panel } from "../shared/ui";
import { CapPanel, ProviderPanel, UsagePanel } from "./LlmUsagePanels";

const PAGE_SIZE = 50;
const DAYS = 7;
// Filterable intents (each has a label in the main dictionary); van_narrative rows show a fallback
// label, its main-dictionary entry would grow the /login first load (docs/DECISIONS.md V21).
const INTENTS: Exclude<LlmIntent, "van_narrative">[] = ["copilot", "narrate", "agent_briefing", "distributor_briefing", "anomaly_narrative"];
const GENERATED: GeneratedBy[] = ["llm", "template", "replay"];
const GUARDS: GuardResult[] = ["pass", "numbers_fail", "injection", "schema_fail", "timeout", "error"];
const CACHE = ["all", "hit", "miss"] as const;
type CacheFilter = (typeof CACHE)[number];

function pick<T extends string>(raw: string | null, allowed: readonly T[]): T | "all" {
  return allowed.find((a) => a === raw) ?? "all";
}

function CallLog() {
  const { t } = useTranslation();
  const { digits } = useLocale();
  const [params, setParams] = useSearchParams();
  const intent = pick(params.get("intent"), INTENTS);
  const generatedBy = pick(params.get("generated_by"), GENERATED);
  const guard = pick(params.get("guard"), GUARDS);
  const cache: CacheFilter = CACHE.find((c) => c === params.get("cache")) ?? "all";
  const page = Math.max(1, Number(params.get("page")) || 1);
  const query: LlmLogQuery = {
    ...(intent === "all" ? {} : { intent }),
    ...(generatedBy === "all" ? {} : { generated_by: generatedBy }),
    ...(guard === "all" ? {} : { guard_result: guard }),
    ...(cache === "all" ? {} : { cache_hit: cache === "hit" }),
    page,
    page_size: PAGE_SIZE,
  };
  const q = useLlmLogs(query);

  function set(key: string, value: string) {
    const out = new URLSearchParams(params);
    if (value === "all") out.delete(key);
    else out.set(key, value);
    out.delete("page");
    setParams(out, { replace: true });
  }
  function setPage(p: number) {
    const out = new URLSearchParams(params);
    if (p > 1) out.set("page", String(p));
    else out.delete("page");
    setParams(out, { replace: true });
  }

  const tokens = (c: LlmLogItem) =>
    c.prompt_tokens === null && c.completion_tokens === null ? "—" : `${formatNumber(c.prompt_tokens ?? 0, digits)} / ${formatNumber(c.completion_tokens ?? 0, digits)}`;
  const columns: Column<LlmLogItem>[] = [
    { key: "when", header: t("admin.llm.log.col.when"), cell: (c) => <TimeText at={c.created_at} mode="datetime" className="text-xs" /> },
    { key: "intent", header: t("admin.llm.log.col.intent"), cell: (c) => t(`admin.llm.intent.${c.intent}`, { defaultValue: c.intent.replace(/_/g, " ") }) },
    {
      key: "provider",
      header: t("admin.llm.log.col.provider"),
      cell: (c) => (
        <span className="block font-mono text-xs">
          {c.provider}
          {c.model ? <span className="block text-muted">{c.model}</span> : null}
        </span>
      ),
    },
    {
      key: "generatedBy",
      header: t("admin.llm.log.col.generatedBy"),
      cell: (c) => <Badge tone={c.generated_by === "template" ? "neutral" : "good"}>{t(`admin.llm.generatedBy.${c.generated_by}`)}</Badge>,
    },
    {
      key: "guard",
      header: t("admin.llm.log.col.guard"),
      cell: (c) => (
        <span title={c.error ?? undefined}>
          <Badge tone={c.guard_result === "pass" ? "good" : c.guard_result === "injection" ? "bad" : "warn"}>{t(`admin.llm.guard.${c.guard_result}`)}</Badge>
        </span>
      ),
    },
    { key: "tokens", header: t("admin.llm.log.col.tokens"), align: "right", cell: (c) => <span className="num text-xs">{tokens(c)}</span> },
    {
      key: "latency",
      header: t("admin.llm.log.col.latency"),
      align: "right",
      cell: (c) => <span className="num text-xs">{t("admin.llm.usage.ms", { value: formatNumber(c.latency_ms, digits) })}</span>,
      sortValue: (c) => c.latency_ms,
    },
    { key: "cache", header: t("admin.llm.log.col.cache"), cell: (c) => (c.cache_hit ? <Badge tone="good">{t("admin.llm.log.hit")}</Badge> : <span className="text-muted">—</span>) },
    { key: "user", header: t("admin.llm.log.col.user"), cell: (c) => <span className="block max-w-40 truncate text-xs">{c.user_email ?? "—"}</span> },
  ];
  const filtered = intent !== "all" || generatedBy !== "all" || guard !== "all" || cache !== "all";

  return (
    <Panel title={t("admin.llm.log.title")} testId="llm-log">
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <FilterSelect<LlmIntent | "all">
          label={t("admin.llm.filter.intent")}
          value={intent}
          onChange={(v) => set("intent", v)}
          options={[{ value: "all", label: t("admin.common.all") }, ...INTENTS.map((i) => ({ value: i, label: t(`admin.llm.intent.${i}`) }))]}
        />
        <FilterSelect<GeneratedBy | "all">
          label={t("admin.llm.filter.generatedBy")}
          value={generatedBy}
          onChange={(v) => set("generated_by", v)}
          options={[{ value: "all", label: t("admin.common.all") }, ...GENERATED.map((g) => ({ value: g, label: t(`admin.llm.generatedBy.${g}`) }))]}
        />
        <FilterSelect<GuardResult | "all">
          label={t("admin.llm.filter.guard")}
          value={guard}
          onChange={(v) => set("guard", v)}
          options={[{ value: "all", label: t("admin.common.all") }, ...GUARDS.map((g) => ({ value: g, label: t(`admin.llm.guard.${g}`) }))]}
        />
        <FilterSelect<CacheFilter>
          label={t("admin.llm.filter.cache")}
          value={cache}
          onChange={(v) => set("cache", v)}
          options={[
            { value: "all", label: t("admin.common.all") },
            { value: "hit", label: t("admin.llm.filter.hit") },
            { value: "miss", label: t("admin.llm.filter.miss") },
          ]}
        />
      </div>
      <DataTable
        caption={t("admin.llm.log.title")}
        columns={columns}
        rows={q.data?.items}
        getRowId={(c) => c.id}
        loading={q.isPending}
        error={q.isError && !q.data}
        onRetry={() => void q.refetch()}
        empty={{
          title: t("admin.llm.empty.title"),
          body: t("admin.llm.empty.body"),
          action: filtered
            ? { label: t("admin.common.clearFilters"), onClick: () => setParams(new URLSearchParams(), { replace: true }) }
            : { label: t("admin.common.refresh"), onClick: () => void q.refetch() },
        }}
        maxHeight={560}
      />
      {q.data && q.data.total > 0 ? (
        <div className="mt-3">
          <Pagination page={page} pageSize={PAGE_SIZE} total={q.data.total} onPageChange={setPage} />
        </div>
      ) : null}
    </Panel>
  );
}

/** /admin/llm: provider status, daily cap, 7-day usage, call log and the forecast drift monitor. */
export function AdminLlmPage() {
  const { t } = useTranslation();
  const usage = useLlmUsage(DAYS);
  return (
    <div className="space-y-4" data-testid="admin-llm">
      <AdminHeader title={t("admin.llm.title")} lead={t("admin.llm.lead")} />
      <div className="grid gap-4 lg:grid-cols-3 [&>*]:min-w-0">
        <ProviderPanel />
        {usage.isPending ? (
          <>
            <SkeletonPanel rows={3} />
            <SkeletonPanel rows={5} />
          </>
        ) : usage.isError ? (
          <ErrorState className="lg:col-span-2" onRetry={() => void usage.refetch()} retrying={usage.isFetching} />
        ) : (
          <>
            <CapPanel u={usage.data} />
            <UsagePanel u={usage.data} />
          </>
        )}
      </div>
      <CallLog />
      <DriftPanel />
    </div>
  );
}

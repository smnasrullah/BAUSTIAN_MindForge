import { RotateCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";

import { useAgentSummary, useForecast, useRunway } from "../../../api/hooks/agents";
import type { FloatType } from "../../../api/types";
import { SkeletonRows, SkeletonRunway } from "../../../components/ui/Skeleton";
import { EmptyState, ErrorState } from "../../../components/ui/StatePanel";
import { formatDateTime } from "../../../lib/format";
import { useLocale } from "../../../lib/prefs";
import { NoAgentState } from "../AgentPageStates";
import { FloatSwitch } from "../FloatSwitch";
import { isFloatType, RUNWAY_HOURS, stockoutFlag, toRunwayPoints } from "../runwayModel";
import { useMyAgentId, useRunwayEvents } from "../useAgentData";
import { FanChart } from "./FanChart";
import { hourlyRows } from "./hourlyModel";
import { HourlyList } from "./HourlyList";

/** 72h forecast: big balance fan per float, event ribbons, hour-by-hour demand list. */
export function ForecastPage() {
  const { t } = useTranslation();
  const id = useMyAgentId();
  const [params, setParams] = useSearchParams();
  const raw = params.get("float");
  const floatType: FloatType = isFloatType(raw) ? raw : "cash";

  function choose(next: FloatType): void {
    const merged = new URLSearchParams(params);
    merged.set("float", next);
    setParams(merged, { replace: true });
  }

  return (
    <div className="space-y-4">
      <header className="space-y-3">
        <h1 className="font-display text-h1 font-bold">{t("page.agentForecast")}</h1>
        {id !== null ? <AsOfLine agentId={id} /> : null}
        <FloatSwitch value={floatType} onChange={choose} />
      </header>
      {id === null ? (
        <NoAgentState />
      ) : (
        // Desktop: the fan chart wide, the hour-by-hour list as a side panel.
        <div className="space-y-4 lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(20rem,26rem)] lg:items-start lg:gap-6 lg:space-y-0">
          <ForecastBody agentId={id} floatType={floatType} />
        </div>
      )}
    </div>
  );
}

function AsOfLine({ agentId }: { agentId: number }) {
  const { t } = useTranslation();
  const { lang, digits } = useLocale();
  const summary = useAgentSummary(agentId);
  if (!summary.data) return <p className="min-h-5 text-small text-muted" aria-hidden />;
  return (
    <p className="num text-small text-muted">
      {t("forecast.asOf", { time: formatDateTime(new Date(summary.data.as_of), lang, digits), model: summary.data.model_version })}
    </p>
  );
}

/** Fan chart + hourly list for one agent's float (also used on the distributor agent detail). */
export function ForecastBody({ agentId, floatType }: { agentId: number; floatType: FloatType }) {
  const { t } = useTranslation();
  const summary = useAgentSummary(agentId);
  const events = useRunwayEvents(summary.data);
  const runway = useRunway(agentId, floatType);
  const forecast = useForecast(agentId, { horizon_hours: RUNWAY_HOURS });
  const points = forecast.data?.floats.find((f) => f.float_type === floatType)?.points ?? [];
  const empty = (onRetry: () => void) => (
    <EmptyState
      compact
      title={t("forecast.empty.title")}
      body={t("forecast.empty.body")}
      action={{ label: t("forecast.empty.action"), icon: RotateCw, onClick: onRetry }}
    />
  );

  return (
    <>
      {runway.isPending ? (
        <SkeletonRunway className="h-[26rem]" />
      ) : runway.isError ? (
        <ErrorState compact onRetry={() => void runway.refetch()} retrying={runway.isFetching} />
      ) : runway.data.series.length === 0 ? (
        empty(() => void runway.refetch())
      ) : (
        <FanChart
          floatType={floatType}
          series={toRunwayPoints(runway.data)}
          capacity={Math.max(runway.data.capacity, runway.data.balance)}
          asOf={runway.data.as_of}
          stockout={stockoutFlag(runway.data)}
          events={events}
        />
      )}

      {forecast.isPending ? (
        <div className="ap-card p-4">
          <SkeletonRows rows={8} cols={3} />
        </div>
      ) : forecast.isError ? (
        <ErrorState compact onRetry={() => void forecast.refetch()} retrying={forecast.isFetching} />
      ) : points.length === 0 ? (
        empty(() => void forecast.refetch())
      ) : (
        <HourlyList
          floatType={floatType}
          rows={hourlyRows(points, runway.data?.series, runway.data?.hours_to_stockout ?? null, forecast.data.as_of)}
        />
      )}
    </>
  );
}

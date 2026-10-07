import { Clock, Radio, RotateCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useFreshness } from "../../api/hooks/system";
import { Skeleton } from "../../components/ui/Skeleton";
import { cn } from "../../lib/cn";
import { formatRelative, localizeDigits } from "../../lib/format";
import { useLocale } from "../../lib/prefs";
import { useNow } from "../../lib/useNow";

const CHIP = "inline-flex min-h-8 max-w-full items-center gap-1.5 rounded-full border border-line bg-surface px-3 text-xs";

/**
 * "Live simulation (synthetic data) · Updated 2 min ago · model v3" from GET /system/freshness.
 * "Updated" is the real time the forecasts were last computed; the mode says which clock the
 * synthetic data follows (live: today's date in Dhaka; fixed: the frozen reproducible timeline).
 */
export function FreshnessChip({ className }: { className?: string }) {
  const { t } = useTranslation();
  const { lang, digits } = useLocale();
  const now = useNow();
  const q = useFreshness();

  if (q.isPending) return <Skeleton className={cn("h-8 w-48 rounded-full", className)} />;
  if (q.isError) {
    return (
      <button type="button" onClick={() => void q.refetch()} className={cn(CHIP, "text-muted hover:text-fg", className)}>
        <RotateCw aria-hidden className="size-3.5" />
        {t("freshness.error")} · {t("common.retry")}
      </button>
    );
  }
  const model = q.data.model_version ? localizeDigits(q.data.model_version, digits) : t("freshness.unknown");
  const updated = q.data.last_forecast_at
    ? t("freshness.label", { ago: formatRelative(new Date(q.data.last_forecast_at), now, lang, digits), model })
    : t("freshness.noForecast", { model });
  const mode = q.data.clock?.mode;
  const text = mode ? `${t(`freshness.mode.${mode}`)} · ${updated}` : updated;
  const Icon = mode === "live" ? Radio : Clock;
  return (
    <span
      className={cn(CHIP, "text-muted", className)}
      title={`${t("freshness.title")}: ${text}`}
      data-testid="freshness-chip"
      data-clock-mode={mode ?? "unknown"}
    >
      <Icon aria-hidden className={cn("size-3.5 shrink-0", mode === "live" && "text-pulse-fg")} />
      {/* One line, as tall as its skeleton: wrapping on a phone pushed the page down. */}
      <span className="min-w-0 truncate">{text}</span>
    </span>
  );
}

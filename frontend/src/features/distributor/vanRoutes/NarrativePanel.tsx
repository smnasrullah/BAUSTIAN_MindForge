import { useTranslation } from "react-i18next";

import { useVanNarrative } from "../../../api/vanPlans";
import { LangText } from "../../../components/ui/LangText";
import { SourceChip } from "../../../components/ui/SourceChip";
import { SkeletonText } from "../../../components/ui/Skeleton";
import { ErrorState } from "../../../components/ui/StatePanel";
import { TimeText } from "../../../components/ui/TimeText";
import { useLocale } from "../../../lib/prefs";
import { VAN_NS } from "../../../i18n/vanRoutes";

/** "Why this order?": wording written from the plan's stored numbers (LLM, replay or template, labelled). */
export function NarrativePanel({ planId }: { planId: number }) {
  const { t } = useTranslation();
  const { t: tv } = useTranslation(VAN_NS);
  const { lang } = useLocale();
  const q = useVanNarrative(planId, lang);

  return (
    <section aria-labelledby="why-title" className="ap-card space-y-3 p-4" data-testid="narrative-panel">
      <div>
        <h2 id="why-title" className="font-display text-h3 font-bold">
          {tv("why.title")}
        </h2>
        <p className="text-small text-muted">{tv("why.lead")}</p>
      </div>

      {q.isPending ? (
        <SkeletonText lines={4} />
      ) : q.isError ? (
        <ErrorState compact title={tv("why.failed")} onRetry={() => void q.refetch()} retrying={q.isFetching} />
      ) : (
        <div className="space-y-2" data-testid="narrative" data-generated-by={q.data.generated_by}>
          <p className="max-w-(--prose-max) whitespace-pre-wrap text-body">
            <LangText text={q.data.text} />
          </p>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
            <SourceChip source="model" />
            {q.data.generated_by === "template" ? <span>{t("why.template")}</span> : <SourceChip source="ai" />}
            <span>
              <TimeText at={q.data.generated_at} mode="datetime" />
            </span>
            {q.data.model_version ? <span className="num">· {q.data.model_version}</span> : null}
          </div>
        </div>
      )}
    </section>
  );
}

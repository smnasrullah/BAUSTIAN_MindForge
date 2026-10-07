import { ChartLine } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { useExplanations, useNarration } from "../../../api/hooks/agents";
import type { FloatType } from "../../../api/types";
import { WhyStones } from "../../../components/signature/WhyStones";
import { SkeletonText } from "../../../components/ui/Skeleton";
import { EmptyState, ErrorState } from "../../../components/ui/StatePanel";
import { useLocale } from "../../../lib/prefs";
import { FloatSwitch } from "../FloatSwitch";
import { WordingBlock } from "./WordingBlock";

interface WhyPanelProps {
  agentId: number;
  initialFloat: FloatType;
  /** Where the empty state's "see forecast" goes (default: the agent's own forecast page). */
  forecastPath?: string;
}

/** "Why?": model reasons (SHAP, template sentences) first, then the LLM's plain-words summary. */
export function WhyPanel({ agentId, initialFloat, forecastPath = "/agent/forecast" }: WhyPanelProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { lang } = useLocale();
  const [target, setTarget] = useState<FloatType>(initialFloat);
  const ex = useExplanations(agentId, { target, lang });
  const reasons = ex.data?.reasons ?? [];
  const narration = useNarration(agentId, target, lang, ex.isSuccess && reasons.length > 0);

  return (
    <section aria-labelledby="why-heading" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="why-heading" className="sr-only">
          {t("why.title")}
        </h2>
        <FloatSwitch value={target} onChange={setTarget} label={t("why.float")} size="sm" />
      </div>

      {ex.isPending ? (
        <div className="ap-card p-4">
          <SkeletonText lines={4} />
        </div>
      ) : ex.isError ? (
        <ErrorState compact onRetry={() => void ex.refetch()} retrying={ex.isFetching} />
      ) : reasons.length === 0 ? (
        <EmptyState
          compact
          illustration="quiet-pulse"
          title={t("why.empty.title")}
          body={t("why.empty.body")}
          action={{ label: t("why.empty.action"), icon: ChartLine, onClick: () => navigate(`${forecastPath}?float=${target}`) }}
        />
      ) : (
        <>
          <WordingBlock templateText={reasons[0]?.sentence ?? ""} narration={narration.data} pending={narration.isFetching} />
          <WhyStones reasons={reasons} generatedBy={ex.data.generated_by} noApiKey={narration.data?.no_api_key} modelVersion={ex.data.model_version} />
        </>
      )}
    </section>
  );
}

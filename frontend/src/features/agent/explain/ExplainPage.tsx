import { Cpu, ShieldCheck, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";

import type { FloatType } from "../../../api/types";
import { PageHeader } from "../../../components/ui/PageHeader";
import { NoAgentState } from "../AgentPageStates";
import { WhyPanel } from "../home/WhyPanel";
import { isFloatType } from "../runwayModel";
import { useMyAgentId } from "../useAgentData";

/** "Why?" (F7): SHAP reasons as WhyStones, the model chip kept apart from the AI wording chip. */
export function ExplainPage() {
  const { t } = useTranslation();
  const id = useMyAgentId();
  const [params] = useSearchParams();
  const raw = params.get("float");
  const initial: FloatType = isFloatType(raw) ? raw : "cash";

  return (
    <div className="space-y-4">
      <PageHeader title={t("explain.title")} description={t("explain.lead")} />

      <div className="space-y-4 lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(18rem,24rem)] lg:items-start lg:gap-6 lg:space-y-0">
        <dl className="grid gap-2 text-small sm:grid-cols-2 lg:col-start-2 lg:row-start-1 lg:grid-cols-1">
          <div className="rounded-xl border border-line bg-surface p-3">
            <dt className="inline-flex items-center gap-1.5 rounded-full bg-pulse/12 px-2.5 py-1 text-xs font-semibold text-pulse-fg">
              <Cpu aria-hidden className="size-3.5" />
              {t("why.model")}
            </dt>
            <dd className="mt-2 text-muted">{t("explain.modelChip")}</dd>
          </div>
          <div className="rounded-xl border border-line bg-surface p-3">
            <dt className="inline-flex items-center gap-1.5 rounded-full bg-brand/20 px-2.5 py-1 text-xs font-semibold text-fg">
              <Sparkles aria-hidden className="size-3.5" />
              {t("why.llm")}
            </dt>
            <dd className="mt-2 text-muted">{t("explain.aiChip")}</dd>
          </div>
        </dl>

        <div className="min-w-0 lg:col-start-1 lg:row-start-1">
          {id === null ? <NoAgentState /> : <WhyPanel key={initial} agentId={id} initialFloat={initial} />}
        </div>
      </div>

      <p className="flex items-center gap-1.5 text-xs text-muted">
        <ShieldCheck aria-hidden className="size-3.5" />
        {t("common.advisory")}
      </p>
    </div>
  );
}

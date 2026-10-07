import { CircleAlert, CircleCheck, Circle, LoaderCircle } from "lucide-react";

import { useTranslation } from "react-i18next";

import type { BootstrapState } from "../../lib/systemStatus";

const STEPS = ["waiting_for_db", "migrating", "seeding", "training", "precomputing", "finalizing"] as const;

function stepIndex(state: BootstrapState): number {
  if (state === "ready") return STEPS.length;
  return STEPS.findIndex((s) => s === state);
}

export function PreparingScreen({ state }: { state: BootstrapState }) {
  const { t } = useTranslation();
  const failed = state === "failed";
  const current = stepIndex(state);

  return (
    <main className="grid min-h-screen place-items-center bg-bg px-6 text-fg">
      <section
        className="w-full max-w-md ap-card p-8 shadow-[0_8px_30px_rgba(10,15,31,0.08)]"
        aria-live="polite"
      >
        <p className="ap-eyebrow">AgentPulse AI</p>
        <h1 className="mt-2 flex items-center gap-2 font-display text-3xl font-bold">
          {failed && <CircleAlert aria-hidden className="size-7 text-risk-red" />}
          {failed ? t("boot.failedTitle") : t("boot.title")}
        </h1>
        <p className="mt-2 text-sm text-muted">
          {failed ? t("boot.failedLead") : t("boot.lead")}
        </p>

        <ol className="mt-6 space-y-3">
          {STEPS.map((step, i) => {
            const done = !failed && current > i;
            const active = !failed && current === i;
            const Icon = done ? CircleCheck : active ? LoaderCircle : Circle;
            const tone = done ? "text-risk-green" : active ? "animate-spin text-pulse" : "text-muted";
            return (
              <li key={step} className="flex items-center gap-3 text-sm">
                <Icon aria-hidden className={`size-5 shrink-0 ${tone}`} />
                <span className={active ? "font-semibold" : done ? "" : "text-muted"}>
                  {t(`boot.step.${step}`)}
                </span>
              </li>
            );
          })}
        </ol>

        <p className="mt-8 border-t border-line pt-4 text-xs text-muted">
          {t("boot.footer")}
        </p>
      </section>
    </main>
  );
}

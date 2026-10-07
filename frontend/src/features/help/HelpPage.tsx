import { ChevronDown, ChartLine, CircleHelp, Gauge, Hourglass, Mail, Route, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { ShortcutList } from "../../app/shell/ShortcutList";
import { useShellStore } from "../../app/shell/shellStore";
import { LiquidButton } from "../../components/ui/LiquidButton";
import { PageHeader } from "../../components/ui/PageHeader";
import { Section } from "../account/Section";
import { useAuthStore } from "../auth/authStore";

const FAQ = ["1", "2", "3", "4", "5", "6"] as const;
const READ = [
  { key: "gauge", icon: Gauge },
  { key: "runway", icon: ChartLine },
  { key: "countdown", icon: Hourglass },
  { key: "why", icon: Sparkles },
] as const;

export function HelpPage() {
  const { t } = useTranslation();
  const role = useAuthStore((s) => s.user?.role);

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <PageHeader eyebrow={t("help.eyebrow")} title={t("page.help")} />

      <Section title={t("help.faqTitle")}>
        <div className="divide-y divide-line">
          {FAQ.map((n) => (
            <details key={n} className="group py-1">
              <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 rounded-xl px-1 font-semibold [&::-webkit-details-marker]:hidden">
                <span className="flex items-center gap-2">
                  <CircleHelp aria-hidden className="size-4 shrink-0 text-muted" />
                  {t(`help.faq.q${n}`)}
                </span>
                <ChevronDown aria-hidden className="size-4 shrink-0 text-muted transition-transform group-open:rotate-180" />
              </summary>
              <p className="pb-3 pl-7 pr-2 text-small text-muted">{t(`help.faq.a${n}`)}</p>
            </details>
          ))}
        </div>
      </Section>

      <Section title={t("help.readTitle")}>
        <div className="grid gap-4 sm:grid-cols-2">
          {READ.map(({ key, icon: Icon }) => (
            <div key={key} className="rounded-2xl border border-line bg-bg p-4">
              <p className="flex items-center gap-2 font-semibold">
                <Icon aria-hidden className="size-4 text-pulse-fg" />
                {t(`help.read.${key}Title`)}
              </p>
              <p className="mt-1 text-small text-muted">{t(`help.read.${key}Body`)}</p>
            </div>
          ))}
        </div>
        <Link to="/about" className="mt-4 inline-block text-small font-semibold text-pulse-fg underline underline-offset-2">
          {t("help.methodLink")}
        </Link>
        <Link to="/distributor/discovery" className="mt-4 ml-4 inline-block text-small font-semibold text-pulse-fg underline underline-offset-2">
          {t("help.discoveryLink")}
        </Link>
      </Section>

      <Section title={t("shortcuts.title")} id="shortcuts">
        <ShortcutList includeSidebar={role !== "agent"} />
      </Section>

      <div className="grid gap-5 md:grid-cols-2">
        <Section title={t("help.tourTitle")}>
          <p className="text-small text-muted">{t("help.tourBody")}</p>
          <LiquidButton className="mt-4" icon={Route} onClick={() => useShellStore.getState().setTourReplay(true)}>
            {t("help.tourButton")}
          </LiquidButton>
        </Section>
        <Section title={t("help.contactTitle")}>
          <p className="flex gap-2 text-small text-muted">
            <Mail aria-hidden className="mt-0.5 size-4 shrink-0" />
            {t("help.contactBody")}
          </p>
        </Section>
      </div>
    </div>
  );
}

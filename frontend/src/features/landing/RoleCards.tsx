import { ArrowRight, Map as MapIcon, Settings2, Smartphone, type LucideIcon } from "lucide-react";
import { motion } from "motion/react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { cn } from "../../lib/cn";
import { useReducedMotionPref } from "../../lib/motionPrefs";
import { listStagger, revealVariants } from "../../styles/motion";
import type { Role } from "../auth/types";
import { useDemoMode } from "../auth/useDemoLogin";

interface CardDef {
  role: Role;
  icon: LucideIcon;
  body: "landing.roles.agentBody" | "landing.roles.distributorBody" | "landing.roles.adminBody";
  /** Daylight (agent) vs Control Room (distributor/admin) personality. */
  tone: "day" | "night";
}

const CARDS: CardDef[] = [
  { role: "agent", icon: Smartphone, body: "landing.roles.agentBody", tone: "day" },
  { role: "distributor", icon: MapIcon, body: "landing.roles.distributorBody", tone: "night" },
  { role: "admin", icon: Settings2, body: "landing.roles.adminBody", tone: "night" },
];

/** Role cards link to /login; nothing here signs anyone in (Judge demo lives on the sign-in page). */
export function RoleCards() {
  const { t } = useTranslation();
  const reduced = useReducedMotionPref();
  const demoMode = useDemoMode();

  return (
    <section aria-labelledby="roles-title" className="px-4 py-16 md:px-8 md:py-20">
      <div className="mx-auto max-w-6xl">
        <h2 id="roles-title" className="font-display text-h1 font-bold md:text-display">
          {t("landing.roles.title")}
        </h2>
        <p className="mt-3 text-body text-muted">{t(demoMode ? "landing.roles.demoNote" : "landing.roles.loginNote")}</p>
        <motion.ul
          variants={listStagger}
          initial="hidden"
          whileInView="show"
          viewport={{ once: true, amount: 0.2 }}
          className="mt-8 grid gap-4 md:grid-cols-2 lg:grid-cols-[1.2fr_1.2fr_1fr]"
        >
          {CARDS.map(({ role, icon: Icon, body, tone }) => {
            const name = t(`role.${role}`);
            return (
              <motion.li
                key={role}
                variants={revealVariants(reduced)}
                data-theme={tone === "night" ? "dark" : undefined}
                className={cn(
                  "relative flex flex-col overflow-hidden rounded-[var(--radius-card)] border p-6",
                  tone === "day" ? "border-line bg-paper text-ink-950 shadow-soft" : "border-white/10 bg-ink-900 text-fg shadow-glow",
                  role === "admin" && "md:col-span-2 lg:col-span-1",
                )}
              >
                <span
                  aria-hidden
                  className={cn(
                    "grid size-12 place-items-center rounded-2xl",
                    tone === "day" ? "bg-brand text-ink-950" : "bg-pulse/20 text-pulse-fg",
                  )}
                >
                  <Icon className="size-6" />
                </span>
                <h3 className="mt-5 font-display text-h2 font-bold">{t(`landing.roles.${role}Name`)}</h3>
                <p className={cn("mt-2 flex-1 text-body", tone === "day" ? "text-ink-600" : "text-muted")}>{t(body)}</p>
                <div className="mt-6">
                  <Link
                    to="/login"
                    data-testid={`role-card-${role}`}
                    className={cn(
                      "inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-[var(--radius-input)] font-semibold",
                      tone === "day" ? "bg-brand text-ink-950" : "border border-line-strong",
                    )}
                  >
                    <ArrowRight aria-hidden className="size-4" />
                    {t("landing.roles.signIn", { role: name })}
                  </Link>
                </div>
              </motion.li>
            );
          })}
        </motion.ul>
      </div>
    </section>
  );
}

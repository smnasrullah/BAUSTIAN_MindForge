import { motion } from "motion/react";
import { useTranslation } from "react-i18next";
import { NavLink } from "react-router-dom";

import { useHelpUnread } from "../../api/hooks/notifications";
import { cn } from "../../lib/cn";
import { formatNumber } from "../../lib/format";
import { useLocale } from "../../lib/prefs";
import { useReducedMotionPref } from "../../lib/motionPrefs";
import { SPRING } from "../../styles/motion";
import { AGENT_NAV } from "./nav";

/** Agent bottom nav (one thumb, at most 5 tabs): a sliding pill follows the active tab. Help
 * carries the unread help-request count. */
export function BottomNav() {
  const { t } = useTranslation();
  const { digits } = useLocale();
  const reduced = useReducedMotionPref();
  const helpUnread = useHelpUnread();
  return (
    <nav
      aria-label={t("shell.mainNav")}
      data-tour="nav"
      data-testid="bottom-nav"
      className="sticky bottom-0 z-30 grid grid-cols-5 gap-1 border-t border-line bg-surface/95 px-2 pb-[max(env(safe-area-inset-bottom),0.5rem)] pt-2 backdrop-blur"
    >
      {AGENT_NAV.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={({ isActive }) =>
            cn(
              "relative isolate flex min-h-14 flex-col items-center justify-center gap-1 rounded-2xl px-1 text-center text-xs leading-tight transition-colors",
              isActive ? "font-semibold text-fg" : "text-muted",
            )
          }
        >
          {({ isActive }) => (
            <>
              {isActive ? (
                <motion.span
                  layoutId="bottom-nav-pill"
                  transition={reduced ? { duration: 0 } : SPRING.snappy}
                  className="absolute inset-0 -z-10 rounded-2xl bg-brand/25"
                />
              ) : null}
              <motion.span animate={isActive && !reduced ? { y: -2 } : { y: 0 }} transition={SPRING.snappy} className="relative">
                <Icon aria-hidden className="size-5" />
                {to === "/agent/help" && helpUnread > 0 ? (
                  <span data-testid="help-nav-badge" className="num absolute -right-2.5 -top-1.5 min-w-4 rounded-full bg-act-solid px-1 text-[10px] font-bold leading-4 text-white">
                    {formatNumber(Math.min(helpUnread, 99), digits)}
                  </span>
                ) : null}
              </motion.span>
              {t(label)}
              {to === "/agent/help" && helpUnread > 0 ? <span className="sr-only">{t("nav.helpUnread", { n: formatNumber(helpUnread, digits) })}</span> : null}
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );
}

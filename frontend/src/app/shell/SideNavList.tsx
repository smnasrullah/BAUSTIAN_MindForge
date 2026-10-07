import * as Tooltip from "@radix-ui/react-tooltip";
import { motion } from "motion/react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, useMatch, useResolvedPath } from "react-router-dom";

import { cn } from "../../lib/cn";
import { useReducedMotionPref } from "../../lib/motionPrefs";
import { SPRING } from "../../styles/motion";
import type { NavBadge, NavItem } from "./nav";

export function Tip({ label, enabled, children }: { label: string; enabled: boolean; children: ReactNode }) {
  if (!enabled) return <>{children}</>;
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content side="right" sideOffset={10} className="ap-sheet z-(--z-overlay) rounded-lg bg-ink-900 px-2.5 py-1.5 text-xs font-semibold text-paper shadow-lift">
          {label}
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

interface SideLinkProps {
  item: NavItem;
  collapsed: boolean;
  /** Distinct per list so the rail and the phone drawer do not animate into each other. */
  layoutId: string;
  /** Optional count on one link (agent sidebar only). */
  badge?: NavBadge;
}

/**
 * className must be a plain string: Radix Tooltip.Trigger asChild (Slot) joins classNames as strings,
 * so NavLink's className function became its source text, the link lost `relative`, and the active
 * pill (absolute inset-0) covered the whole rail, toggle included.
 */
function SideLink({ item, collapsed, layoutId, badge }: SideLinkProps) {
  const { t } = useTranslation();
  const reduced = useReducedMotionPref();
  const { pathname } = useResolvedPath(item.to);
  const active = useMatch({ path: pathname, end: item.end ?? false }) !== null;
  const Icon = item.icon;
  const label = item.label ? t(item.label) : t(`page.${item.page}`);
  const count = badge?.to === item.to ? badge : undefined;
  return (
    <Tip label={label} enabled={collapsed}>
      <NavLink
        to={item.to}
        end={item.end}
        aria-label={collapsed ? (count ? `${label} ${count.label}` : label) : undefined}
        className={cn(
          "relative isolate flex min-h-11 items-center gap-3 rounded-xl px-3 text-small font-medium transition-colors",
          collapsed && "justify-center px-0",
          active ? "font-semibold text-pulse-fg" : "text-muted hover:bg-surface-2 hover:text-fg",
        )}
      >
        {active ? (
          <motion.span
            layoutId={layoutId}
            transition={reduced ? { duration: 0 } : SPRING.snappy}
            className="pointer-events-none absolute inset-0 -z-10 rounded-xl bg-pulse/10 ring-1 ring-inset ring-pulse/15"
          >
            <span className="absolute inset-y-2.5 left-0 w-[3px] rounded-full bg-pulse" />
          </motion.span>
        ) : null}
        {count && collapsed ? (
          <span className="relative shrink-0">
            <Icon aria-hidden className="size-5" />
            <CountPill text={count.text} className="absolute -right-2.5 -top-1.5" />
          </span>
        ) : (
          <Icon aria-hidden className="size-5 shrink-0" />
        )}
        {collapsed ? null : <span className="truncate">{label}</span>}
        {count && !collapsed ? (
          <>
            <CountPill text={count.text} className="ml-auto" />
            <span className="sr-only">{count.label}</span>
          </>
        ) : null}
      </NavLink>
    </Tip>
  );
}

function CountPill({ text, className }: { text: string; className: string }) {
  return (
    <span data-testid="help-nav-badge" className={cn("num min-w-4 rounded-full bg-act-solid px-1 text-center text-[10px] font-bold leading-4 text-white", className)}>
      {text}
    </span>
  );
}

interface SideNavListProps extends Omit<SideLinkProps, "item"> {
  items: NavItem[];
  /** The rail carries the onboarding-tour anchor; the phone drawer does not. */
  tour?: boolean;
}

export function SideNavList({ items, collapsed, layoutId, tour, badge }: SideNavListProps) {
  const { t } = useTranslation();
  return (
    <nav aria-label={t("shell.mainNav")} data-tour={tour ? "nav" : undefined} className="flex flex-col gap-1 px-3 pb-4">
      {items.map((item) => (
        <SideLink key={item.to} item={item} collapsed={collapsed} layoutId={layoutId} badge={badge} />
      ))}
    </nav>
  );
}

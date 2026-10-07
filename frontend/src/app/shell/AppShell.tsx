import * as Tooltip from "@radix-ui/react-tooltip";
import { motion } from "motion/react";
import { useTranslation } from "react-i18next";
import { Outlet, useLocation } from "react-router-dom";

import { PageBackdrop } from "../../components/backdrop/Backdrop";
import { useAuthStore } from "../../features/auth/authStore";
import { ROLE_HOME } from "../../features/auth/types";
import { Notices } from "../../features/shared/Notices";
import { cn } from "../../lib/cn";
import { useMediaQuery } from "../../lib/useMediaQuery";
import { usePageTitle } from "../../lib/usePageTitle";
import { pageVariants } from "../../styles/motion";
import { AgentSidebar } from "./AgentSidebar";
import { BottomNav } from "./BottomNav";
import { Breadcrumbs } from "./Breadcrumbs";
import { CommandPalette } from "./CommandPalette";
import { FreshnessChip } from "./FreshnessChip";
import { crumbsFor, pageFor, SIDE_NAV } from "./nav";
import { OfflineBanner } from "./OfflineBanner";
import { ServerBanner } from "./ServerBanner";
import { OnboardingTour } from "./OnboardingTour";
import { RouteErrorBoundary } from "./RouteErrorBoundary";
import { DESKTOP_QUERY } from "./shellStore";
import { ShortcutHelp } from "./ShortcutHelp";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { useGlobalShortcuts } from "./useGlobalShortcuts";

/**
 * Every signed-in page: top bar, role navigation (agent bottom nav below 1024px / control-room sidebar),
 * breadcrumbs + freshness, per-route error boundary, palette, shortcuts, tour, footer notices.
 */
export function AppShell() {
  const { t } = useTranslation();
  const user = useAuthStore((s) => s.user);
  const { pathname } = useLocation();
  const role = user?.role ?? "agent";
  const home = ROLE_HOME[role];
  const agent = role === "agent";
  // Agents get the control-room sidebar shell from 1024px; below that, the phone layout (bottom nav).
  const desktop = useMediaQuery(DESKTOP_QUERY);
  const sideShell = !agent || desktop;
  const meta = pageFor(pathname);
  const crumbs = crumbsFor(pathname, role);
  usePageTitle(meta ? t(`page.${meta.page}`) : null);
  useGlobalShortcuts(home, sideShell);

  const subRow =
    crumbs.length > 1 || meta?.prediction ? (
      // A single crumb is not rendered at all: kept invisible, it still took width and made the
      // loaded freshness chip (wider than its skeleton) wrap to a second row: a layout shift.
      <div className={cn("flex flex-wrap items-center gap-2", crumbs.length > 1 ? "justify-between" : "justify-end", sideShell && "lg:justify-end")}>
        {crumbs.length > 1 ? <Breadcrumbs crumbs={crumbs} className={cn(sideShell && "lg:hidden")} /> : null}
        {meta?.prediction ? <FreshnessChip /> : null}
      </div>
    ) : null;

  const page = (
    // While a block is still loading (aria-busy) the page reserves a full screen, so the footer
    // starts below the fold instead of being shoved off-screen when the data lands (CLS 0.69).
    <main
      id="main"
      tabIndex={-1}
      className={cn("flex-1 outline-none has-[[aria-busy=true]]:min-h-dvh", sideShell ? "px-4 py-5 md:px-6 md:py-6 xl:px-8" : "px-4 pb-8 pt-4")}
    >
      {/* Agent pages without their own desktop grid keep a readable column instead of stretching. */}
      <div className={cn("mx-auto w-full", sideShell && (agent && !meta?.wide && pathname.startsWith("/agent") ? "max-w-4xl" : "max-w-(--page-max)"))}>
        {subRow ? <div className="mb-4">{subRow}</div> : null}
        <RouteErrorBoundary resetKey={pathname}>
          <motion.div key={pathname} variants={pageVariants} initial="initial" animate="enter">
            <Outlet />
          </motion.div>
        </RouteErrorBoundary>
      </div>
    </main>
  );

  return (
    <Tooltip.Provider delayDuration={300}>
      <a href="#main" className="sr-only z-(--z-skip) rounded-xl bg-brand px-4 py-2 font-semibold text-on-brand focus:not-sr-only focus:fixed focus:left-3 focus:top-3">
        {t("shell.skip")}
      </a>
      <div data-testid="app-shell" data-role={role} className="relative isolate min-h-screen bg-bg text-fg">
        <PageBackdrop />
        <OfflineBanner />
        <ServerBanner />
        {!sideShell ? (
          <div className="mx-auto flex min-h-screen max-w-md flex-col md:max-w-2xl">
            <TopBar home={home} crumbs={crumbs} compact />
            {page}
            <Notices />
            <BottomNav />
          </div>
        ) : (
          <div className="flex min-h-screen">
            {role === "agent" ? <AgentSidebar /> : <Sidebar items={SIDE_NAV[role]} area={t(`role.${role}`)} />}
            <div className="flex min-w-0 flex-1 flex-col">
              <TopBar home={home} crumbs={crumbs} compact={false} />
              {page}
              <Notices />
            </div>
          </div>
        )}
      </div>
      <CommandPalette />
      <ShortcutHelp includeSidebar={sideShell} />
      <OnboardingTour />
    </Tooltip.Provider>
  );
}

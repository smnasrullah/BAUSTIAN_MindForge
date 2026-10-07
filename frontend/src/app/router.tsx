import type { ComponentType, ReactNode } from "react";
import { createBrowserRouter, Outlet, type RouteObject } from "react-router-dom";

import { HomeRedirect } from "../features/auth/HomeRedirect";
import { RoleGuard } from "../features/auth/RoleGuard";
import { SessionRoot } from "../features/auth/SessionRoot";
import { ALL_ROLES, type Role } from "../features/auth/types";
import { DevKitRoute } from "../features/devkit/DevKitRoute";
import { PlaceholderPage } from "../features/shared/PlaceholderPage";
import { RootErrorPage } from "../features/shared/RootErrorPage";
import { ForbiddenPage, NotFoundPage, ServerErrorPage } from "../features/shared/StatusPages";
import { PublicLayout } from "./layouts/PublicLayout";
import {
  adminPages,
  agentPages,
  distributorPages,
  forgotPasswordPage,
  loginPage,
  resetPasswordPage,
  responsibleAiPage,
  signupPage,
  type PageDef,
} from "./routes";

/** Design kit: dev server always; production bundle only when built with VITE_DEV_KIT=true (e2e). */
const DEV_KIT = import.meta.env.DEV || import.meta.env.VITE_DEV_KIT === "true";

type Lazy = NonNullable<RouteObject["lazy"]>;

/** Route-split page: its chunk loads on first visit (PulseLine route progress shows meanwhile). */
function page(load: () => Promise<ComponentType>): Lazy {
  return async () => ({ Component: await load() });
}

// Login is split too: its form stack (react-hook-form, zod) stays out of the initial bundle.
// The signed-in shell (nav, command palette, menus, tour) is its own chunk: not on landing or login.
const shell = page(() => import("./shell/AppShell").then((m) => m.AppShell));
const login = page(() => import("../features/auth/LoginPage").then((m) => m.LoginPage));
const signup = page(() => import("../features/auth/SignupPage").then((m) => m.SignupPage));
const forgotPassword = page(() => import("../features/auth/ForgotPasswordPage").then((m) => m.ForgotPasswordPage));
const resetPassword = page(() => import("../features/auth/ResetPasswordPage").then((m) => m.ResetPasswordPage));
const settings = page(() => import("../features/account/SettingsPage").then((m) => m.SettingsPage));
const profile = page(() => import("../features/account/ProfilePage").then((m) => m.ProfilePage));
const help = page(() => import("../features/help/HelpPage").then((m) => m.HelpPage));
const about = page(() => import("../features/about/AboutPage").then((m) => m.AboutPage));
const notifications = page(() => import("../features/notifications/NotificationsPage").then((m) => m.NotificationsPage));

const agentHome = page(() => import("../features/agent/home/AgentHomePage").then((m) => m.AgentHomePage));
const agentForecast = page(() => import("../features/agent/forecast/ForecastPage").then((m) => m.ForecastPage));
const agentStockout = page(() => import("../features/agent/stockout/StockoutPage").then((m) => m.StockoutPage));
const agentRebalance = page(() => import("../features/agent/rebalance/RebalancePage").then((m) => m.RebalancePage));
const agentWhatIf = page(() => import("../features/agent/whatif/WhatIfPage").then((m) => m.WhatIfPage));
const agentExplain = page(() => import("../features/agent/explain/ExplainPage").then((m) => m.ExplainPage));
const agentCopilot = page(() => import("../features/agent/copilot/CopilotPage").then((m) => m.CopilotPage));
const agentSwap = page(() => import("../features/agent/swap/AgentSwapPage").then((m) => m.AgentSwapPage));

const controlRoom = page(() => import("../features/distributor/controlRoom/ControlRoomPage").then((m) => m.ControlRoomPage));
const agentsTable = page(() => import("../features/distributor/agents/AgentsPage").then((m) => m.AgentsPage));
const agentDetail = page(() => import("../features/distributor/detail/AgentDetailPage").then((m) => m.AgentDetailPage));
const swapQueue = page(() => import("../features/distributor/swaps/SwapsPage").then((m) => m.SwapsPage));
const anomalies = page(() => import("../features/distributor/anomalies/AnomaliesPage").then((m) => m.AnomaliesPage));
const impact = page(() => import("../features/distributor/impact/ImpactPage").then((m) => m.ImpactPage));
const discovery = page(() => import("../features/distributor/discovery/DiscoveryPage").then((m) => m.DiscoveryPage));
const briefing = page(() => import("../features/distributor/briefing/BriefingPage").then((m) => m.BriefingPage));
const adminOverview = page(() => import("../features/admin/overview/AdminOverviewPage").then((m) => m.AdminOverviewPage));
const adminEvents = page(() => import("../features/admin/events/AdminEventsPage").then((m) => m.AdminEventsPage));
const adminData = page(() => import("../features/admin/data/AdminDataPage").then((m) => m.AdminDataPage));
const adminModels = page(() => import("../features/admin/models/AdminModelsPage").then((m) => m.AdminModelsPage));
const adminUsers = page(() => import("../features/admin/users/AdminUsersPage").then((m) => m.AdminUsersPage));
const adminAudit = page(() => import("../features/admin/audit/AuditLogPage").then((m) => m.AuditLogPage));
const adminLlm = page(() => import("../features/admin/llm/AdminLlmPage").then((m) => m.AdminLlmPage));
const agentHelp = page(() => import("../features/liquidity/AgentHelpPage").then((m) => m.AgentHelpPage));
const distributorHelp = page(() => import("../features/liquidity/distributor/DistributorHelpPage").then((m) => m.DistributorHelpPage));
const adminHelpSettings = page(() => import("../features/liquidity/admin/AdminHelpSettingsPage").then((m) => m.AdminHelpSettingsPage));

const responsibleAi = page(() => import("../features/responsibleAi/ResponsibleAiPage").then((m) => m.ResponsibleAiPage));

/** Pages built so far, keyed by role-relative path; the rest render a placeholder. */
const BUILT: Record<string, Lazy> = { settings };
const AGENT_BUILT: Record<string, Lazy> = {
  "": agentHome,
  forecast: agentForecast,
  stockout: agentStockout,
  rebalance: agentRebalance,
  "what-if": agentWhatIf,
  explain: agentExplain,
  // Was missing: the bottom-nav "Swap" tab and "See swap offers" rendered the placeholder page.
  swap: agentSwap,
  copilot: agentCopilot,
  help: agentHelp,
  settings,
};
const DISTRIBUTOR_BUILT: Record<string, Lazy> = {
  "": controlRoom,
  agents: agentsTable,
  "agents/:id": agentDetail,
  swaps: swapQueue,
  "van-routes": page(() => import("../features/distributor/vanRoutes/VanRoutesPage").then((m) => m.VanRoutesPage)),
  anomalies,
  "anomalies/:id": anomalies,
  impact,
  discovery,
  briefing,
  "help-requests": distributorHelp,
  "help-requests/:id": distributorHelp,
};

const ADMIN_BUILT: Record<string, Lazy> = {
  "": adminOverview,
  events: adminEvents,
  data: adminData,
  models: adminModels,
  users: adminUsers,
  "audit-log": adminAudit,
  audit: adminAudit,
  llm: adminLlm,
  "help-settings": adminHelpSettings,
};

function children(pages: PageDef[], built: Record<string, Lazy> = BUILT): RouteObject[] {
  return pages.map((p) => {
    const lazy = built[p.path];
    const content = lazy ? { lazy } : { element: <PlaceholderPage page={p} /> };
    return p.path === "" ? { index: true, ...content } : { path: p.path, ...content };
  });
}

function guarded(roles: readonly Role[], element: ReactNode): ReactNode {
  return <RoleGuard roles={roles}>{element}</RoleGuard>;
}

const appRoutes: RouteObject[] = [
  // Signed out: lazy landing; signed in: role home.
  { path: "/", element: <HomeRedirect /> },
  { element: <PublicLayout width="wide" />, children: [{ path: loginPage.path, lazy: login }] },
  {
    element: <PublicLayout />,
    children: [
      { path: "/403", element: <ForbiddenPage /> },
      { path: "/404", element: <NotFoundPage /> },
      { path: "/500", element: <ServerErrorPage /> },
      { path: signupPage.path, lazy: signup },
      { path: forgotPasswordPage.path, lazy: forgotPassword },
      { path: resetPasswordPage.path, lazy: resetPassword },
    ],
  },
  {
    // Every signed-in page shares the shell; each role area adds its own guard.
    element: guarded(ALL_ROLES, <Outlet />),
    children: [
      {
        lazy: shell,
        children: [
          { path: "/agent", element: guarded(["agent"], <Outlet />), children: children(agentPages, AGENT_BUILT) },
          { path: "/distributor", element: guarded(["distributor"], <Outlet />), children: children(distributorPages, DISTRIBUTOR_BUILT) },
          { path: "/admin", element: guarded(["admin"], <Outlet />), children: children(adminPages, ADMIN_BUILT) },
          { path: responsibleAiPage.path, lazy: responsibleAi },
          { path: "/settings", lazy: settings },
          { path: "/profile", lazy: profile },
          { path: "/help", lazy: help },
          { path: "/about", lazy: about },
          { path: "/notifications", lazy: notifications },
        ],
      },
    ],
  },
  ...(DEV_KIT ? [{ path: "/dev/kit", element: <DevKitRoute /> }] : []),
  { element: <PublicLayout />, children: [{ path: "*", element: <NotFoundPage /> }] },
];

export const routes: RouteObject[] = [{ element: <SessionRoot />, errorElement: <RootErrorPage />, children: appRoutes }];

export const router = createBrowserRouter(routes);

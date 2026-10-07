import {
  Activity,
  ArrowLeftRight,
  Bot,
  Boxes,
  CalendarDays,
  ChartLine,
  Database,
  HandHeart,
  House,
  Map as MapIcon,
  MessageCircle,
  Newspaper,
  ScanSearch,
  ScrollText,
  ShieldCheck,
  TrendingUp,
  Truck,
  Users,
  type LucideIcon,
} from "lucide-react";
import { matchPath } from "react-router-dom";

import type en from "../../i18n/en.json";
import { ROLE_HOME, type Role } from "../../features/auth/types";

export type PageKey = keyof (typeof en)["page"];

export interface NavItem {
  to: string;
  page: PageKey;
  icon: LucideIcon;
  end?: boolean;
  /** i18n key shown instead of the page title (the agent sidebar reuses the bottom-nav labels). */
  label?: (typeof AGENT_NAV)[number]["label"];
}

/** A count shown on one sidebar link (the agent's unread help requests). */
export interface NavBadge {
  to: string;
  /** Already formatted for the current digits. */
  text: string;
  /** Screen-reader text, e.g. "3 unread". */
  label: string;
}

export const SIDE_NAV: Record<Exclude<Role, "agent">, NavItem[]> = {
  distributor: [
    { to: "/distributor", page: "controlRoom", icon: MapIcon, end: true },
    { to: "/distributor/agents", page: "agents", icon: Users },
    { to: "/distributor/swaps", page: "swapQueue", icon: ArrowLeftRight },
    { to: "/distributor/van-routes", page: "vanRoutes", icon: Truck },
    { to: "/distributor/help-requests", page: "helpRequests", icon: HandHeart },
    { to: "/distributor/anomalies", page: "anomalies", icon: ScanSearch },
    { to: "/distributor/impact", page: "impact", icon: TrendingUp },
    { to: "/distributor/briefing", page: "briefing", icon: Newspaper },
    { to: "/responsible-ai", page: "responsibleAi", icon: ShieldCheck },
  ],
  admin: [
    { to: "/admin", page: "systemStatus", icon: Activity, end: true },
    { to: "/admin/events", page: "adminEvents", icon: CalendarDays },
    { to: "/admin/data", page: "syntheticData", icon: Database },
    { to: "/admin/models", page: "models", icon: Boxes },
    { to: "/admin/users", page: "users", icon: Users },
    { to: "/admin/help-settings", page: "helpSettings", icon: HandHeart },
    { to: "/admin/audit-log", page: "auditLog", icon: ScrollText },
    { to: "/admin/llm", page: "llmLog", icon: Bot },
    { to: "/responsible-ai", page: "responsibleAi", icon: ShieldCheck },
  ],
};

export const AGENT_NAV = [
  { to: "/agent", label: "nav.home", icon: House, end: true },
  { to: "/agent/forecast", label: "nav.forecast", icon: ChartLine, end: false },
  { to: "/agent/help", label: "nav.help", icon: HandHeart, end: false },
  { to: "/agent/swap", label: "nav.swap", icon: ArrowLeftRight, end: false },
  { to: "/agent/copilot", label: "nav.ask", icon: MessageCircle, end: false },
] as const;

/** Nav entries for the palette's empty state. */
export function navFor(role: Role): NavItem[] {
  if (role !== "agent") return SIDE_NAV[role];
  const pages: PageKey[] = ["agentHome", "agentForecast", "agentHelp", "agentSwap", "agentCopilot"];
  return AGENT_NAV.map((item, i) => ({ to: item.to, page: pages[i] ?? "agentHome", icon: item.icon, end: item.end }));
}

/** Agent desktop sidebar: the bottom-nav destinations, same order, routes and labels. */
export const AGENT_SIDE_NAV: NavItem[] = navFor("agent").map((item, i) => ({ ...item, label: AGENT_NAV[i]?.label }));

const HOME = "~home";

interface PageMeta {
  pattern: string;
  page: PageKey;
  parent?: string;
  /** Prediction pages show the data freshness chip. */
  prediction?: boolean;
  /** Agent desktop: the page has its own dashboard grid and uses the full page width. */
  wide?: boolean;
}

const PAGES: PageMeta[] = [
  { pattern: "/agent", page: "agentHome", prediction: true, wide: true },
  { pattern: "/agent/forecast", page: "agentForecast", parent: "/agent", prediction: true, wide: true },
  { pattern: "/agent/stockout", page: "agentStockout", parent: "/agent", prediction: true, wide: true },
  { pattern: "/agent/rebalance", page: "agentRebalance", parent: "/agent", prediction: true, wide: true },
  { pattern: "/agent/what-if", page: "agentWhatIf", parent: "/agent/forecast", prediction: true, wide: true },
  { pattern: "/agent/explain", page: "agentExplain", parent: "/agent", prediction: true, wide: true },
  { pattern: "/agent/swap", page: "agentSwap", parent: "/agent", prediction: true, wide: true },
  { pattern: "/agent/copilot", page: "agentCopilot", parent: "/agent", wide: true },
  { pattern: "/agent/help", page: "agentHelp", parent: "/agent", wide: true },
  { pattern: "/agent/settings", page: "settings", parent: "/agent" },
  // The control room shows freshness in its own bottom stripe.
  { pattern: "/distributor", page: "controlRoom" },
  { pattern: "/distributor/agents", page: "agents", parent: "/distributor", prediction: true },
  { pattern: "/distributor/agents/:id", page: "agentDetail", parent: "/distributor/agents", prediction: true },
  { pattern: "/distributor/swaps", page: "swapQueue", parent: "/distributor", prediction: true },
  { pattern: "/distributor/van-routes", page: "vanRoutes", parent: "/distributor" },
  { pattern: "/distributor/help-requests", page: "helpRequests", parent: "/distributor" },
  { pattern: "/distributor/help-requests/:id", page: "helpRequest", parent: "/distributor/help-requests" },
  { pattern: "/distributor/anomalies", page: "anomalies", parent: "/distributor" },
  { pattern: "/distributor/anomalies/:id", page: "investigation", parent: "/distributor/anomalies" },
  { pattern: "/distributor/impact", page: "impact", parent: "/distributor", prediction: true },
  { pattern: "/distributor/discovery", page: "discovery", parent: "/distributor" },
  { pattern: "/distributor/briefing", page: "briefing", parent: "/distributor", prediction: true },
  { pattern: "/admin", page: "systemStatus" },
  { pattern: "/admin/events", page: "adminEvents", parent: "/admin" },
  { pattern: "/admin/data", page: "syntheticData", parent: "/admin" },
  { pattern: "/admin/users", page: "users", parent: "/admin" },
  { pattern: "/admin/help-settings", page: "helpSettings", parent: "/admin" },
  { pattern: "/admin/models", page: "models", parent: "/admin" },
  { pattern: "/admin/llm", page: "llmLog", parent: "/admin" },
  { pattern: "/admin/audit-log", page: "auditLog", parent: "/admin" },
  { pattern: "/admin/audit", page: "auditLog", parent: "/admin" },
  { pattern: "/settings", page: "settings", parent: HOME },
  { pattern: "/profile", page: "profile", parent: HOME },
  { pattern: "/help", page: "help", parent: HOME },
  { pattern: "/about", page: "about", parent: HOME },
  { pattern: "/notifications", page: "notifications", parent: HOME },
  { pattern: "/responsible-ai", page: "responsibleAi", parent: HOME },
];

export interface Crumb {
  to: string;
  page: PageKey;
  /** Route param shown after the title ("#12"). */
  id?: string;
}

function find(pathname: string): { meta: PageMeta; id?: string } | null {
  for (const meta of PAGES) {
    const hit = matchPath({ path: meta.pattern, end: true }, pathname);
    if (hit) return { meta, id: hit.params.id };
  }
  return null;
}

export function pageFor(pathname: string): PageMeta | null {
  return find(pathname)?.meta ?? null;
}

/** Home first, current page last. */
export function crumbsFor(pathname: string, role: Role): Crumb[] {
  const out: Crumb[] = [];
  let path: string | undefined = pathname;
  for (let guard = 0; path && guard < 5; guard++) {
    const found = find(path);
    if (!found) break;
    out.unshift({ to: path, page: found.meta.page, id: found.id });
    path = found.meta.parent === HOME ? ROLE_HOME[role] : found.meta.parent;
  }
  return out;
}

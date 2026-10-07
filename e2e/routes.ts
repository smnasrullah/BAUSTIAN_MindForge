// Every frontend route the app serves. Each later prompt that adds a route APPENDS it here.
// `as`: the demo role the smoke test signs in with, or "public" to visit signed out.
// Params (":id") use a concrete sample value.

export type Role = "agent" | "distributor" | "admin";

export interface E2ERoute {
  path: string;
  as: Role | "public";
}

export const ROUTES: E2ERoute[] = [
  // Public
  { path: "/", as: "public" },
  { path: "/login", as: "public" },
  { path: "/signup", as: "public" },
  { path: "/forgot-password", as: "public" },
  { path: "/reset-password", as: "public" },
  { path: "/403", as: "public" },

  // Shared (any signed-in role)
  { path: "/settings", as: "agent" },
  { path: "/settings", as: "distributor" },
  { path: "/settings", as: "admin" },
  { path: "/responsible-ai", as: "distributor" },

  // Agent
  { path: "/agent", as: "agent" },
  { path: "/agent/forecast", as: "agent" },
  { path: "/agent/swap", as: "agent" },
  { path: "/agent/copilot", as: "agent" },
  { path: "/agent/settings", as: "agent" },

  // Distributor
  { path: "/distributor", as: "distributor" },
  { path: "/distributor/agents/1", as: "distributor" },
  { path: "/distributor/swaps", as: "distributor" },
  { path: "/distributor/anomalies", as: "distributor" },
  { path: "/distributor/anomalies/1", as: "distributor" },
  { path: "/distributor/impact", as: "distributor" },
  { path: "/distributor/discovery", as: "distributor" },
  { path: "/distributor/briefing", as: "distributor" },
  { path: "/distributor/van-routes", as: "distributor" },

  // Admin
  { path: "/admin", as: "admin" },
  { path: "/admin/users", as: "admin" },
  { path: "/admin/models", as: "admin" },
  { path: "/admin/llm", as: "admin" },
  { path: "/admin/audit", as: "admin" },

  // Dev only (built into the e2e bundle via VITE_DEV_KIT)
  { path: "/dev/kit", as: "public" },

  // App shell + platform pages
  { path: "/404", as: "public" },
  { path: "/500", as: "public" },
  { path: "/profile", as: "agent" },
  { path: "/profile", as: "distributor" },
  { path: "/profile", as: "admin" },
  { path: "/notifications", as: "agent" },
  { path: "/notifications", as: "distributor" },
  { path: "/help", as: "agent" },
  { path: "/help", as: "admin" },
  { path: "/about", as: "distributor" },
  { path: "/about", as: "agent" },

  // Agent stockout time (/agent and /agent/forecast are listed above)
  { path: "/agent/stockout", as: "agent" },

  // Agent actions and copilot (/agent/copilot is listed above)
  { path: "/agent/rebalance", as: "agent" },
  { path: "/agent/what-if", as: "agent" },
  { path: "/agent/explain", as: "agent" },

  // Distributor control room: /distributor is listed above (Distributor); no new paths.

  // Distributor pages (agent detail, swaps, anomalies, impact, briefing are listed above)
  { path: "/distributor/agents", as: "distributor" },
  { path: "/responsible-ai", as: "admin" },
  { path: "/responsible-ai", as: "agent" },

  // Admin console (/admin, /admin/users, /admin/models, /admin/llm, /admin/audit are listed above)
  { path: "/admin/events", as: "admin" },
  { path: "/admin/data", as: "admin" },
  { path: "/admin/audit-log", as: "admin" },

  // Liquidity help requests (agent /agent/help, distributor list and detail, admin settings)
  { path: "/agent/help", as: "agent" },
  { path: "/distributor/help-requests", as: "distributor" },
  { path: "/distributor/help-requests/1", as: "distributor" },
  { path: "/admin/help-settings", as: "admin" },
];

// Sitemap from docs/ARCHITECTURE.md §1. Paths are relative to the role base.

export interface PageDef {
  path: string;
  title: string;
  summary: string;
  features: string;
}

export const agentPages: PageDef[] = [
  { path: "", title: "Home", summary: "Cash and e-money runway, countdown, reasons and the next action.", features: "F1–F4, F7" },
  { path: "forecast", title: "72h forecast", summary: "Runway strip with event ribbons and the what-if slider.", features: "F1, F2, F6, F8" },
  { path: "stockout", title: "Stockout time", summary: "When each float could run out, with confidence and 6/24/72h risk.", features: "F2, F3" },
  { path: "rebalance", title: "Rebalance", summary: "What to add and by when, your request status and swap offers.", features: "F4, F5" },
  { path: "what-if", title: "What if", summary: "Add or remove float and watch the runway react.", features: "F8" },
  { path: "explain", title: "Why?", summary: "Reasons behind the forecast, model and AI wording kept apart.", features: "F7, LLM" },
  { path: "swap", title: "Swap offers", summary: "Nearby agent swap offers and recommendation status. Your distributor approves.", features: "F4, F5" },
  { path: "help", title: "Help requests", summary: "Nearby shops that need your answer, and your own open request.", features: "Help" },
  { path: "copilot", title: "Ask", summary: "Bangla/English chat and voice, grounded in your own data.", features: "LLM" },
  { path: "settings", title: "Settings", summary: "Language, digits and theme.", features: "—" },
];

export const distributorPages: PageDef[] = [
  { path: "", title: "Control room", summary: "Map of agents by risk, swap droplets and the inspector.", features: "F3, F10" },
  { path: "agents", title: "Agents", summary: "Every agent with risk, URL-synced filters, column chooser and CSV export.", features: "F3" },
  { path: "agents/:id", title: "Agent detail", summary: "Forecast, risk, reasons and recommendation for one agent.", features: "F1–F4, F7" },
  { path: "swaps", title: "Swap queue", summary: "Approve or reject proposed swaps with a note.", features: "F5" },
  { path: "van-routes", title: "Van routes", summary: "Cash-van routes and approval.", features: "F14" },
  { path: "anomalies", title: "Anomalies", summary: "Isolation Forest flags for human review.", features: "F9" },
  { path: "anomalies/:id", title: "Investigation", summary: "Evidence, AI-written narrative and your review.", features: "F9, LLM" },
  { path: "discovery", title: "Pain-point discovery", summary: "Liquidity pain points by source (field, literature, simulated) and the feature each maps to.", features: "Evidence" },
  { path: "impact", title: "Impact", summary: "Model versus fixed-threshold baseline: stockout hours, BDT saved, van trips.", features: "F11" },
  { path: "help-requests", title: "Help requests", summary: "Shortage requests from your agents: who claimed them, status and attention flags.", features: "Help" },
  { path: "help-requests/:id", title: "Help request", summary: "One request: timeline, who was asked and their answers.", features: "Help" },
  { path: "briefing", title: "Daily briefing", summary: "Briefing written from today's evidence pack.", features: "LLM" },
];

export const adminPages: PageDef[] = [
  { path: "", title: "System overview", summary: "Database, migrations, data version, models, LLM mode and open work.", features: "—" },
  { path: "events", title: "Events", summary: "Salary, Eid, hat-bazar, weather and holiday calendar (create, edit, delete).", features: "F6" },
  { path: "data", title: "Synthetic data", summary: "Dataset summary, regeneration from the fixed seed and the assumptions document.", features: "—" },
  { path: "models", title: "Models", summary: "Model registry, holdout metrics, retraining jobs and drift.", features: "—" },
  { path: "users", title: "Users", summary: "Create users, set roles, link to an agent or distributor, disable.", features: "—" },
  { path: "audit-log", title: "Audit log", summary: "Every human decision with user and note; filters and CSV export.", features: "—" },
  // Older link to the audit log; same page.
  { path: "audit", title: "Audit log", summary: "Every human decision with user and note; filters and CSV export.", features: "—" },
  { path: "help-settings", title: "Help request settings", summary: "Safety switches, thresholds, dry-run preview and the demo shortage simulator.", features: "Help" },
  { path: "llm", title: "LLM layer", summary: "Provider status, call log, daily cap usage and forecast-error drift.", features: "LLM" },
];

export const responsibleAiPage: PageDef = {
  path: "/responsible-ai",
  title: "Responsible AI",
  summary: "Model cards, fairness by group, limitations and the synthetic data notice.",
  features: "F12",
};

export const settingsPage: PageDef = {
  path: "/settings",
  title: "Settings",
  summary: "Account settings and password change.",
  features: "—",
};

export const loginPage: PageDef = {
  path: "/login",
  title: "Sign in",
  summary: "Email and password; Judge demo accounts only when the server runs with DEMO_MODE.",
  features: "—",
};

export const signupPage: PageDef = {
  path: "/signup",
  title: "Create an account",
  summary: "Self-signup; the account waits for admin approval.",
  features: "—",
};

export const forgotPasswordPage: PageDef = {
  path: "/forgot-password",
  title: "Forgot password",
  summary: "Request a single-use reset link.",
  features: "—",
};

export const resetPasswordPage: PageDef = {
  path: "/reset-password",
  title: "Reset password",
  summary: "Set a new password from a reset link.",
  features: "—",
};

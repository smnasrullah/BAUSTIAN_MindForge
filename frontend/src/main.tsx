// Fonts: self-hosted, latin + bengali subsets only, font-display: swap (fontsource default).
import "@fontsource/inter/latin-400.css";
import "@fontsource/inter/latin-500.css";
import "@fontsource/inter/latin-600.css";
import "@fontsource/inter/latin-700.css";
import "@fontsource/hind-siliguri/bengali-400.css";
import "@fontsource/hind-siliguri/bengali-500.css";
import "@fontsource/hind-siliguri/bengali-600.css";
import "@fontsource/hind-siliguri/bengali-700.css";
import "@fontsource/hind-siliguri/latin-400.css";
import "@fontsource/hind-siliguri/latin-600.css";
import "@fontsource/jetbrains-mono/latin-400.css";
import "@fontsource/jetbrains-mono/latin-500.css";
import "./index.css";
import { initI18n } from "./i18n";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { installPrefsSync } from "./features/account/prefsSync";
import { useAuthStore } from "./features/auth/authStore";
import { refreshAccessToken } from "./lib/api";
import { queryClient } from "./lib/queryClient";
import { fetchSystemStatus, systemStatusKey } from "./lib/systemStatus";
import { installThemeSync } from "./lib/theme";
import { App } from "./app/App";

installThemeSync();
installPrefsSync();

// Boot requests run alongside the language chunk instead of after the first render: on a slow
// network each one was a serial round trip before any content. The silent session refresh waits
// for readiness, so a backend that is still starting cannot end a valid session.
void queryClient
  .fetchQuery({ queryKey: systemStatusKey, queryFn: fetchSystemStatus, retry: false })
  .then((status) => {
    if (status.ready && useAuthStore.getState().status === "checking") void refreshAccessToken();
  })
  .catch(() => undefined); // BootstrapGate shows the starting screen and keeps polling

const root = document.getElementById("root");
if (!root) throw new Error("#root element missing");

// The active language's dictionary is its own chunk; render once it is in.
void initI18n().finally(() =>
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  ),
);

import "@testing-library/jest-dom/vitest";
import { act, cleanup, configure } from "@testing-library/react";
import { MotionGlobalConfig } from "motion/react";
import { afterEach, beforeEach, vi } from "vitest";

import { addLanguage } from "../i18n";
import bn from "../i18n/bn.json";
import en from "../i18n/en.json";
import { usePrefsStore } from "../lib/prefs";
import { queryClient } from "../lib/queryClient";
import { clearAppStorage, resetAllStores } from "../lib/storeRegistry";

// findBy* / waitFor allow 3 s (default 1 s): role queries on a big page are slow while vitest
// runs many files in parallel, which made HelpOptOut flaky (about 1 full run in 2). Assertions
// are unchanged; only how long a passing condition may take to appear.
configure({ asyncUtilTimeout: 3000 });

// Animations finish instantly: exit transitions (AnimatePresence) must not keep nodes mounted
// for a frame-rate-dependent time, which made assertions flaky on a loaded CPU.
MotionGlobalConfig.skipAnimations = true;

// The app fetches one dictionary per language on demand; tests switch synchronously.
addLanguage("en", en);
addLanguage("bn", bn);

// jsdom gaps that Radix popovers/menus and cmdk touch.
class NoopResizeObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
if (typeof window.ResizeObserver === "undefined") {
  window.ResizeObserver = NoopResizeObserver as unknown as typeof ResizeObserver;
}
if (typeof Element.prototype.scrollIntoView !== "function") {
  Element.prototype.scrollIntoView = () => undefined;
}

// Tests read English with English digits unless they switch explicitly.
beforeEach(() => {
  act(() => usePrefsStore.setState({ lang: "en", digits: "en", theme: "light" }));
});

// No state leaks between tests: DOM, zustand stores, storage, the app QueryClient, mocks, timers.
afterEach(() => {
  cleanup();
  act(() => resetAllStores());
  clearAppStorage();
  queryClient.clear();
  vi.clearAllMocks();
  vi.useRealTimers();
});

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import { registerStoreReset, STORAGE_PREFIX } from "../../lib/storeRegistry";

/** Phone widths: the sidebar is an icon rail + overlay drawer, so the desktop width choice does not apply. */
export const PHONE_QUERY = "(max-width: 767px)";
/** From here the agent area uses the sidebar shell; below it keeps the phone layout (bottom nav). */
export const DESKTOP_QUERY = "(min-width: 1024px)";

interface ShellState {
  /** Persisted per browser: the sidebar width choice. */
  sidebarCollapsed: boolean;
  paletteOpen: boolean;
  shortcutsOpen: boolean;
  /** Replay requested from Help or Settings (first run is driven by the user's tour_done flag). */
  tourReplay: boolean;
  toggleSidebar: () => void;
  setPaletteOpen: (open: boolean) => void;
  setShortcutsOpen: (open: boolean) => void;
  setTourReplay: (on: boolean) => void;
}

const initial = { sidebarCollapsed: false, paletteOpen: false, shortcutsOpen: false, tourReplay: false };

export const useShellStore = create<ShellState>()(
  persist(
    (set) => ({
      ...initial,
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setPaletteOpen: (paletteOpen) => set({ paletteOpen }),
      setShortcutsOpen: (shortcutsOpen) => set({ shortcutsOpen }),
      setTourReplay: (tourReplay) => set({ tourReplay }),
    }),
    {
      name: `${STORAGE_PREFIX}-shell`,
      storage: createJSONStorage(() => window.localStorage),
      partialize: ({ sidebarCollapsed }) => ({ sidebarCollapsed }),
    },
  ),
);

registerStoreReset(() => useShellStore.setState({ ...initial }));

import axios from "axios";
import { create } from "zustand";

import { registerStoreReset } from "./storeRegistry";

/** Whether the API answered lately. Fed by the api client: a network error or a 502/503/504
 * (nginx while the backend restarts) marks it down; any answer marks it up again. */
interface ServerHealth {
  down: boolean;
  /** Just came back after being down (the banner says so for a moment). */
  back: boolean;
  markDown: () => void;
  markUp: () => void;
  clearBack: () => void;
}

export const useServerHealth = create<ServerHealth>()((set, get) => ({
  down: false,
  back: false,
  markDown: () => {
    if (!get().down) set({ down: true, back: false });
  },
  markUp: () => {
    if (get().down) set({ down: false, back: true });
  },
  clearBack: () => set({ back: false }),
}));

registerStoreReset(() => useServerHealth.setState({ down: false, back: false }));

const GATEWAY = new Set([502, 503, 504]);

/** The browser is online but the API did not answer (or nginx says the backend is gone). */
export function isServerUnreachable(error: unknown): boolean {
  if (!axios.isAxiosError(error)) return false;
  if (error.code === "ERR_CANCELED") return false;
  const status = error.response?.status;
  if (status === undefined) return typeof navigator === "undefined" || navigator.onLine !== false;
  return GATEWAY.has(status);
}

import { useCallback, useRef } from "react";

/**
 * One request at a time from a button or form. `isPending` reaches the button a tick late, so a
 * fast double-click sent the same create twice (found by e2e). The guard is a ref: it is set in
 * the same click that starts the request and cleared when `done` runs (pass it as onSettled).
 */
export function useSingleFlight(): (start: (done: () => void) => void) => void {
  const busy = useRef(false);
  return useCallback((start: (done: () => void) => void) => {
    if (busy.current) return;
    busy.current = true;
    start(() => {
      busy.current = false;
    });
  }, []);
}

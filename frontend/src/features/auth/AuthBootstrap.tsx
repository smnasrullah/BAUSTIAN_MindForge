import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Skeleton } from "../../components/ui/Skeleton";
import { refreshAccessToken } from "../../lib/api";
import { useAuthStore } from "./authStore";

/** Waits between session checks that could not reach the server: 1, 2, 4, 8, then 15 s. */
const RETRY_DELAYS_MS = [1000, 2000, 4000, 8000, 15000] as const;

/**
 * Silent refresh on load: the httpOnly cookie, if still valid, restores the session. Only a
 * rejection (401) means "signed out"; when the server cannot be reached the check is retried
 * (sooner when the browser comes back online), so a valid session survives a network blip.
 */
export function AuthBootstrap({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const checking = useAuthStore((s) => s.status === "checking");
  const [failures, setFailures] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer = 0;
    let tries = 0;
    const stillChecking = () => !cancelled && useAuthStore.getState().status === "checking";
    const attempt = async (): Promise<void> => {
      window.clearTimeout(timer);
      if (!stillChecking()) return;
      await refreshAccessToken();
      if (!stillChecking()) return;
      tries += 1;
      setFailures(tries);
      const delay = RETRY_DELAYS_MS[Math.min(tries, RETRY_DELAYS_MS.length) - 1] ?? 15000;
      timer = window.setTimeout(() => void attempt(), delay);
    };
    const onOnline = () => void attempt();
    window.addEventListener("online", onOnline);
    void attempt();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      window.removeEventListener("online", onOnline);
    };
  }, []);

  if (checking) {
    return (
      <div role="status" className="grid min-h-screen place-items-center bg-bg text-fg">
        <div className="w-64 space-y-3" aria-hidden>
          <Skeleton className="h-3 w-24 rounded-full" />
          <Skeleton className="h-8" />
        </div>
        {failures > 0 ? (
          <p className="text-small text-muted">{t("boot.retrying")}</p>
        ) : (
          <span className="sr-only">{t("boot.checking")}</span>
        )}
      </div>
    );
  }
  return <>{children}</>;
}

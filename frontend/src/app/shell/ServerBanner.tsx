import { useQueryClient } from "@tanstack/react-query";
import { PlugZap, RefreshCw } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../lib/api";
import { useReducedMotionPref } from "../../lib/motionPrefs";
import { useServerHealth } from "../../lib/serverHealth";
import { revealVariants } from "../../styles/motion";

const PING_MS = 3000;
const BACK_MS = 3000;

/**
 * The backend stopped answering while the browser is online (restart, deploy): say so, ping
 * /health until it answers, then refetch what is on screen. Offline is OfflineBanner's job.
 */
export function ServerBanner() {
  const { t } = useTranslation();
  const client = useQueryClient();
  const reduced = useReducedMotionPref();
  const down = useServerHealth((s) => s.down);
  const back = useServerHealth((s) => s.back);

  useEffect(() => {
    if (!down) return undefined;
    const id = window.setInterval(() => {
      if (navigator.onLine === false) return;
      api.get("/system/health").catch(() => undefined); // an answer marks the server up
    }, PING_MS);
    return () => window.clearInterval(id);
  }, [down]);

  useEffect(() => {
    if (!back) return undefined;
    void client.refetchQueries({ type: "active" });
    const timer = window.setTimeout(() => useServerHealth.getState().clearBack(), BACK_MS);
    return () => window.clearTimeout(timer);
  }, [back, client]);

  const show = down || back;
  return (
    <div role="status" aria-live="polite" data-testid="server-banner">
      <AnimatePresence>
        {show ? (
          <motion.div
            key={down ? "down" : "back"}
            variants={revealVariants(reduced)}
            initial="hidden"
            animate="show"
            exit="hidden"
            className={`flex items-center justify-center gap-2 px-4 py-2 text-small font-semibold ${down ? "bg-watch text-ink-950" : "border-b border-line bg-surface text-safe-fg"}`}
          >
            {down ? <PlugZap aria-hidden className="size-4" /> : <RefreshCw aria-hidden className="size-4" />}
            <span>{down ? t("shell.serverDown") : t("shell.serverBack")}</span>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

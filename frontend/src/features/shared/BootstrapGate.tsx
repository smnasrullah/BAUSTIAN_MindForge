import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { fetchSystemStatus, systemStatusKey } from "../../lib/systemStatus";
import { PreparingScreen } from "./PreparingScreen";

const POLL_MS = 2000;

export function BootstrapGate({ children }: { children: ReactNode }) {
  const { data, isError } = useQuery({
    queryKey: systemStatusKey,
    queryFn: fetchSystemStatus,
    retry: false,
    refetchInterval: (query) => (query.state.data?.ready ? false : POLL_MS),
  });

  if (data?.ready) return <>{children}</>;
  // The preparing screen is for a backend that is starting or unreachable. While the first status
  // answer is still on its way (every cold load), a blank page avoids flashing "first start".
  if (data === undefined && !isError) return <div className="min-h-screen bg-bg" aria-busy="true" />;
  return <PreparingScreen state={data?.bootstrap_state ?? "starting"} />;
}

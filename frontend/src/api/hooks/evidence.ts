import { useQuery } from "@tanstack/react-query";

import { qk } from "../keys";
import { getPainPoints } from "../services/evidence";

export function usePainPoints() {
  return useQuery({ queryKey: qk.painPoints, queryFn: getPainPoints });
}

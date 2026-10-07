import { api } from "../../lib/api";
import type { PainPoints } from "../types";

export async function getPainPoints(): Promise<PainPoints> {
  return (await api.get<PainPoints>("/evidence/pain-points")).data;
}

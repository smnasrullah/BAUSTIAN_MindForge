import type { GeneratedBy } from "../api/types";

export type WordingKey = "why.llm" | "why.replay" | "why.template" | "why.templateNoKey";

/** i18n key of the wording chip: template wording served because no API key is set says so. */
export function wordingKey(by: GeneratedBy, noApiKey: boolean | undefined): WordingKey {
  return by === "template" && noApiKey ? "why.templateNoKey" : `why.${by}`;
}

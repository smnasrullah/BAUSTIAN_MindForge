import { describe, expect, it } from "vitest";

import en from "../i18n/en.json";
import bn from "../i18n/bn.json";
import { wordingKey } from "./wording";

describe("wording chip key", () => {
  it("says 'no API key' only for template wording served without a key", () => {
    expect(wordingKey("template", true)).toBe("why.templateNoKey");
    expect(wordingKey("template", false)).toBe("why.template");
    expect(wordingKey("template", undefined)).toBe("why.template");
  });

  it("never relabels AI or recorded wording", () => {
    expect(wordingKey("llm", true)).toBe("why.llm");
    expect(wordingKey("replay", true)).toBe("why.replay");
  });

  it("has the label in both languages", () => {
    expect(en.why.templateNoKey).toBe("Template wording (no API key)");
    expect(bn.why.templateNoKey).toContain("টেমপ্লেট ভাষা");
  });
});

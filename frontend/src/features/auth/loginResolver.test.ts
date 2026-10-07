import { describe, expect, it } from "vitest";

import { loginResolver } from "./loginResolver";

const run = (email: string, password: string) =>
  loginResolver({ email, password }, undefined, { fields: {}, shouldUseNativeValidation: false });

describe("loginResolver", () => {
  it("flags empty fields with their message keys", async () => {
    const { errors } = await run("  ", "");
    expect(errors.email?.message).toBe("emailRequired");
    expect(errors.password?.message).toBe("passwordRequired");
  });

  it("flags a malformed email and trims a valid one", async () => {
    expect((await run("not-an-email", "x")).errors.email?.message).toBe("emailInvalid");
    const ok = await run(" a.b@example.com ", "x");
    expect(ok.errors).toEqual({});
    expect(ok.values).toEqual({ email: "a.b@example.com", password: "x" });
  });
});

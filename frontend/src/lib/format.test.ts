import { describe, expect, it } from "vitest";

import { dhakaParts, formatDateTime, formatMoney, formatNumber, groupLakh, localizeDigits, MINUS } from "./format";

describe("dates on the Dhaka clock", () => {
  it("uses the Dhaka date, not the UTC date, around midnight", () => {
    const at = new Date("2026-10-04T18:30:00Z"); // 00:30 on 5 Oct in Dhaka
    expect(dhakaParts(at)).toMatchObject({ year: 2026, month: 9, day: 5, hour: 0, minute: 30 });
    expect(formatDateTime(at, "en", "en")).toBe("5 Oct, 12:30 AM");
    expect(formatDateTime(at, "bn", "bn")).toBe("৫ অক্টো, রাত ১২:৩০");
  });

  it("formats any present day the same way (no fixed calendar)", () => {
    const today = new Date();
    const { day } = dhakaParts(today);
    expect(formatDateTime(today, "en", "en").startsWith(`${day} `)).toBe(true);
  });
});

describe("money and number formatting", () => {
  it("groups in lakh style and localizes digits", () => {
    expect(groupLakh("12345678")).toBe("1,23,45,678");
    expect(formatMoney(120000, "en")).toBe("৳1,20,000");
    expect(formatMoney(120000, "bn")).toBe("৳১,২০,০০০");
    expect(localizeDigits("2026-10-03", "bn")).toBe("২০২৬-১০-০৩");
  });

  it("never shows a minus or plus on a figure that rounds to zero", () => {
    expect(formatMoney(-0.3, "en")).toBe("৳0");
    expect(formatMoney(0.3, "en", { signed: true })).toBe("৳0");
    expect(formatMoney(-0.3, "en", { fraction: 2 })).toBe(`${MINUS}৳0.30`);
    expect(formatMoney(-2500, "en")).toBe(`${MINUS}৳2,500`);
    expect(formatNumber(-0.2, "en")).toBe("0");
  });

  it("moves to the next unit when rounding reaches 100 of the current one", () => {
    expect(formatMoney(99_940, "en", { compact: true })).toBe("৳99.9k");
    expect(formatMoney(99_950, "en", { compact: true })).toBe("৳1 lakh");
    expect(formatMoney(9_995_000, "en", { compact: true })).toBe("৳1 Cr");
    expect(formatMoney(9_995_000, "bn", { compact: true })).toBe("৳১ কোটি");
    expect(formatMoney(150_000, "en", { compact: true })).toBe("৳1.5 lakh");
    expect(formatMoney(-1_250_000_000, "en", { compact: true })).toBe(`${MINUS}৳125 Cr`);
  });
});

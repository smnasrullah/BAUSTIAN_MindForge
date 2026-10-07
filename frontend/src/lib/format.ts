// Number, money and time formatting: Bangladeshi (lakh) grouping, bn/en digits, Asia/Dhaka clock.
// Pure functions; components read lang/digits from the prefs store and pass them in.
import type { Lang } from "../features/auth/types";

export type Digits = Lang;

const BN_DIGITS = "০১২৩৪৫৬৭৮৯";
const DHAKA_OFFSET_MS = 6 * 60 * 60 * 1000; // UTC+6, no DST.
export const MINUS = "−";

export function localizeDigits(text: string, digits: Digits): string {
  if (digits === "en") return text;
  return text.replace(/[0-9]/g, (d) => BN_DIGITS[Number(d)] ?? d);
}

/** "120000" -> "1,20,000": last three digits, then groups of two. */
export function groupLakh(intDigits: string): string {
  if (intDigits.length <= 3) return intDigits;
  const head = intDigits.slice(0, -3);
  const tail = intDigits.slice(-3);
  return `${head.replace(/\B(?=(\d{2})+(?!\d))/g, ",")},${tail}`;
}

export interface NumberOptions {
  /** Decimal places (default 0). */
  fraction?: number;
  /** Prefix "+" on positive values. */
  signed?: boolean;
}

export function formatNumber(value: number, digits: Digits, opts: NumberOptions = {}): string {
  if (!Number.isFinite(value)) return "—";
  const fraction = opts.fraction ?? 0;
  const fixed = Math.abs(value).toFixed(fraction);
  const [int = "0", dec] = fixed.split(".");
  const isZero = Number(fixed) === 0;
  const sign = value < 0 && !isZero ? MINUS : opts.signed && value > 0 && !isZero ? "+" : "";
  const body = dec ? `${groupLakh(int)}.${dec}` : groupLakh(int);
  return localizeDigits(`${sign}${body}`, digits);
}

const COMPACT_UNITS: Record<Lang, { crore: string; lakh: string; thousand: string }> = {
  en: { crore: "Cr", lakh: "lakh", thousand: "k" },
  bn: { crore: "কোটি", lakh: "লাখ", thousand: "হাজার" },
};

export interface MoneyOptions extends NumberOptions {
  /** 1.2 lakh / ১.২ লাখ instead of the full figure. */
  compact?: boolean;
  /** Language of compact unit words (default: same as digits). */
  lang?: Lang;
  /** Show the ৳ symbol (default true). */
  symbol?: boolean;
}

export function formatMoney(value: number, digits: Digits, opts: MoneyOptions = {}): string {
  if (!Number.isFinite(value)) return "—";
  const symbol = opts.symbol === false ? "" : "৳";
  const abs = Math.abs(value);
  // The sign follows the displayed figure: -0.3 at 0 decimals is "৳0", not "−৳0".
  const shown = Number(abs.toFixed(opts.fraction ?? 0));
  const sign = value < 0 && shown !== 0 ? MINUS : opts.signed && value > 0 && shown !== 0 ? "+" : "";
  if (opts.compact && abs >= 1000) {
    const lang = opts.lang ?? digits;
    const units = COMPACT_UNITS[lang];
    // Tiers: thousand < 1e5 <= lakh < 1e7 <= crore. A figure that rounds up to 100 of a unit
    // moves to the next one (99,950 is "1 lakh", not "100k").
    const roundOf = (scaled: number) => (scaled >= 100 ? scaled.toFixed(0) : scaled.toFixed(1).replace(/\.0$/, ""));
    let size = abs >= 1e7 ? 1e7 : abs >= 1e5 ? 1e5 : 1e3;
    if (size === 1e3 && Number(roundOf(abs / 1e3)) >= 100) size = 1e5;
    if (size === 1e5 && Number(roundOf(abs / 1e5)) >= 100) size = 1e7;
    const unit = size === 1e7 ? units.crore : size === 1e5 ? units.lakh : units.thousand;
    const rounded = roundOf(abs / size);
    const space = lang === "en" && unit === units.thousand ? "" : " ";
    return localizeDigits(`${sign}${symbol}${rounded}${space}${unit}`, digits);
  }
  const body = formatNumber(abs, digits, { fraction: opts.fraction });
  return `${sign}${symbol}${body}`;
}

export function formatPercent(ratio: number, digits: Digits): string {
  return `${formatNumber(Math.round(ratio * 100), digits)}%`;
}

interface DhakaParts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
}

export function dhakaParts(at: Date): DhakaParts {
  const d = new Date(at.getTime() + DHAKA_OFFSET_MS);
  return {
    year: d.getUTCFullYear(),
    month: d.getUTCMonth(),
    day: d.getUTCDate(),
    hour: d.getUTCHours(),
    minute: d.getUTCMinutes(),
  };
}

/** Bangla day-part words used before a 12-hour clock ("বিকেল ৩:৪০"). */
function bnDayPart(hour: number): string {
  if (hour >= 4 && hour < 6) return "ভোর";
  if (hour >= 6 && hour < 12) return "সকাল";
  if (hour >= 12 && hour < 15) return "দুপুর";
  if (hour >= 15 && hour < 18) return "বিকেল";
  if (hour >= 18 && hour < 20) return "সন্ধ্যা";
  return "রাত";
}

export function formatClock(at: Date, lang: Lang, digits: Digits): string {
  const { hour, minute } = dhakaParts(at);
  const h12 = hour % 12 === 0 ? 12 : hour % 12;
  const hm = `${h12}:${String(minute).padStart(2, "0")}`;
  const text = lang === "bn" ? `${bnDayPart(hour)} ${hm}` : `${hm} ${hour < 12 ? "AM" : "PM"}`;
  return localizeDigits(text, digits);
}

const MONTHS: Record<Lang, string[]> = {
  en: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
  bn: ["জানু", "ফেব্রু", "মার্চ", "এপ্রি", "মে", "জুন", "জুলা", "আগ", "সেপ্টে", "অক্টো", "নভে", "ডিসে"],
};

export function formatDateTime(at: Date, lang: Lang, digits: Digits): string {
  const { day, month } = dhakaParts(at);
  const date = localizeDigits(`${day} ${MONTHS[lang][month] ?? ""}`, digits);
  return `${date}, ${formatClock(at, lang, digits)}`;
}

const UNITS: Record<Lang, { d: string; h: string; m: string; joiner: string }> = {
  en: { d: "d", h: "h", m: "m", joiner: "" },
  bn: { d: "দিন", h: "ঘণ্টা", m: "মিনিট", joiner: " " },
};

/** 5.333 -> "5h 20m" / "৫ ঘণ্টা ২০ মিনিট". Days appear from 48h. */
export function formatDuration(hours: number, lang: Lang, digits: Digits): string {
  const total = Math.max(0, Math.round(hours * 60));
  const u = UNITS[lang];
  const days = total >= 48 * 60 ? Math.floor(total / (24 * 60)) : 0;
  const h = Math.floor((total - days * 24 * 60) / 60);
  const m = total % 60;
  const part = (n: number, unit: string) => `${n}${u.joiner}${unit}`;
  const parts: string[] = [];
  if (days) parts.push(part(days, u.d));
  if (h || days) parts.push(part(h, u.h));
  if (!days) parts.push(part(m, u.m));
  return localizeDigits(parts.join(" "), digits);
}

export function formatRelative(at: Date, now: Date, lang: Lang, digits: Digits): string {
  const diffH = (at.getTime() - now.getTime()) / 3_600_000;
  const span = formatDuration(Math.abs(diffH), lang, digits);
  if (Math.abs(diffH) < 1 / 60) return lang === "bn" ? "এখন" : "now";
  if (lang === "bn") return `${span} ${diffH > 0 ? "পরে" : "আগে"}`;
  return diffH > 0 ? `in ${span}` : `${span} ago`;
}

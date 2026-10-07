// Synthetic demo day for the landing hero: one agent's cash float on a salary day.
// Illustrative numbers only (labelled "synthetic" on screen); the real forecast lives behind sign-in.
import type { RiskLevel } from "../../api/types";
import { dhakaParts } from "../../lib/format";

export const DAY_START_MIN = 8 * 60;
export const DAY_END_MIN = 22 * 60;
export const STEP_MIN = 10;
export const CAPACITY = 150_000;
export const CONFIDENCE = 0.82;
export const STOCKOUT_MIN = 15 * 60 + 40;
/** Latest swap that would have prevented the stockout (2h lead). */
export const SWAP_BY_MIN = STOCKOUT_MIN - 120;
export const SALARY = { startMin: 10 * 60, endMin: 15 * 60 } as const;
export const INTRO_END_MIN = 11 * 60 + 30;

/** Expected cash balance (BDT) at whole hours; zero from the stockout on. */
const KNOTS: ReadonlyArray<readonly [number, number]> = [
  [8 * 60, 120_000],
  [9 * 60, 112_000],
  [10 * 60, 99_000],
  [11 * 60, 84_000],
  [12 * 60, 68_000],
  [13 * 60, 50_000],
  [14 * 60, 33_000],
  [15 * 60, 14_000],
  [STOCKOUT_MIN, 0],
  [DAY_END_MIN, 0],
];

function clampMin(min: number): number {
  return Math.min(DAY_END_MIN, Math.max(DAY_START_MIN, min));
}

export function expectedAt(min: number): number {
  const m = clampMin(min);
  for (let i = 1; i < KNOTS.length; i++) {
    const [x1, y1] = KNOTS[i] ?? [0, 0];
    const [x0, y0] = KNOTS[i - 1] ?? [0, 0];
    if (m <= x1) return y0 + ((m - x0) / (x1 - x0)) * (y1 - y0);
  }
  return 0;
}

/** Fan band: the low quantile runs dry ~50 min earlier, the high one ~80 min later. */
export function bandAt(min: number): { low: number; high: number } {
  return { low: expectedAt(min + 50), high: expectedAt(min - 80) };
}

export function riskAt(min: number): RiskLevel {
  const hoursLeft = (STOCKOUT_MIN - min) / 60;
  if (hoursLeft > 6) return "green";
  if (hoursLeft > 2) return "amber";
  return "red";
}

/** Wall-clock Date for a Dhaka minute-of-day today (formatClock reads Dhaka time). */
export function dhakaDate(min: number, today: Date = new Date()): Date {
  const { year, month, day } = dhakaParts(today);
  return new Date(Date.UTC(year, month, day) + (min - 6 * 60) * 60_000);
}

/** 0..1 position of a minute on the day axis. */
export function dayPos(min: number): number {
  return (clampMin(min) - DAY_START_MIN) / (DAY_END_MIN - DAY_START_MIN);
}

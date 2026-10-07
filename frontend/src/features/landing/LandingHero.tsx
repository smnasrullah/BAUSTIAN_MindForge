import { ArrowDown, FlaskConical, LogIn } from "lucide-react";
import { animate, AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState, type PointerEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Aurora, Grain } from "../../components/backdrop/Backdrop";
import { LiquidVessel } from "../../components/signature/LiquidVessel";
import { MoneyText } from "../../components/ui/MoneyText";
import { RiskPill } from "../../components/ui/RiskPill";
import { formatClock, formatDuration, formatMoney, formatPercent } from "../../lib/format";
import { useReducedMotionPref } from "../../lib/motionPrefs";
import { useLocale } from "../../lib/prefs";
import { DUR, EASE, tween } from "../../styles/motion";
import {
  CAPACITY,
  CONFIDENCE,
  DAY_END_MIN,
  DAY_START_MIN,
  dhakaDate,
  expectedAt,
  INTRO_END_MIN,
  riskAt,
  STEP_MIN,
  STOCKOUT_MIN,
  SWAP_BY_MIN,
} from "./demoDay";
import { HeroRunway } from "./HeroRunway";

const snap = (min: number) => Math.round(min / STEP_MIN) * STEP_MIN;

/** Full-bleed aurora hero: pointer X scrubs the time of day, the vessel drains, the headline follows. */
export function LandingHero() {
  const { t } = useTranslation();
  const { lang, digits } = useLocale();
  const reduced = useReducedMotionPref();
  const [minute, setMinute] = useState(reduced ? INTRO_END_MIN : DAY_START_MIN);
  const intro = useRef<{ stop: () => void } | null>(null);
  const card = useRef<HTMLDivElement>(null);

  // One intro sweep from opening time; any pointer or key input takes over.
  useEffect(() => {
    if (reduced) return;
    intro.current = animate(DAY_START_MIN, INTRO_END_MIN, {
      duration: DUR.reveal * 3,
      ease: EASE,
      delay: DUR.slow,
      onUpdate: (v) => setMinute(snap(v)),
    });
    return () => intro.current?.stop();
  }, [reduced]);

  function scrub(min: number) {
    intro.current?.stop();
    setMinute(snap(Math.min(DAY_END_MIN, Math.max(DAY_START_MIN, min))));
  }

  function onPointerMove(e: PointerEvent<HTMLElement>) {
    if (e.pointerType !== "mouse") return;
    // Over the runway card the plot is the axis; elsewhere the whole hero width is the day.
    const plot = card.current?.querySelector("[data-plot]");
    const overCard = card.current?.contains(e.target as Node) ?? false;
    const box = (overCard && plot ? plot : e.currentTarget).getBoundingClientRect();
    const ratio = (e.clientX - box.left) / box.width;
    scrub(DAY_START_MIN + ratio * (DAY_END_MIN - DAY_START_MIN));
  }

  const balance = expectedAt(minute);
  const level = riskAt(minute);
  const dry = minute >= STOCKOUT_MIN;
  const clock = (m: number) => formatClock(dhakaDate(m), lang, digits);

  return (
    <section
      aria-labelledby="hero-title"
      onPointerMove={onPointerMove}
      className="relative isolate overflow-hidden px-4 pb-14 pt-8 md:px-8 md:pb-20 md:pt-14"
    >
      <Aurora className="-z-10" />
      <Grain className="-z-10" />
      <div className="mx-auto grid max-w-6xl items-center gap-10 lg:grid-cols-[1.05fr_1fr] lg:gap-14">
        <div>
          <p className="ap-eyebrow">{t("landing.eyebrow")}</p>
          <div className="mt-3 min-h-[7.5rem] md:min-h-[10.5rem] lg:min-h-[14rem] [:lang(bn)_&]:min-h-[10rem] lg:[:lang(bn)_&]:min-h-[18rem]">
            <AnimatePresence mode="wait" initial={false}>
              <motion.h1
                key={dry ? "dry" : "ahead"}
                id="hero-title"
                className="font-display text-[2.5rem] font-bold leading-[1.02] md:text-display lg:text-display-xl"
                initial={{ opacity: 0, y: reduced ? 0 : 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={tween(reduced ? DUR.fast : DUR.base)}
              >
                {t(dry ? "landing.headlineDry" : "landing.headline", { clock: clock(STOCKOUT_MIN) })}
              </motion.h1>
            </AnimatePresence>
          </div>
          {/* Phones: room for the line to wrap under the pill; the intro sweep changes its length. */}
          <div className="mt-4 flex min-h-[4.25rem] flex-wrap items-center gap-3 md:min-h-11">
            <RiskPill level={level} />
            <p className="num text-small font-semibold md:text-body">
              {dry
                ? t("landing.dryLine", { clock: clock(SWAP_BY_MIN) })
                : t("landing.leftLine", {
                    duration: formatDuration((STOCKOUT_MIN - minute) / 60, lang, digits),
                    confidence: formatPercent(CONFIDENCE, digits),
                  })}
            </p>
          </div>
          <p className="mt-5 max-w-xl text-body text-muted">{t("landing.lede")}</p>
          <div className="mt-7 flex flex-wrap gap-3">
            <Link
              to="/login"
              className="inline-flex min-h-12 items-center gap-2 rounded-[var(--radius-input)] bg-brand px-6 font-semibold text-on-brand shadow-soft transition-[filter] duration-200 hover:brightness-105"
            >
              <LogIn aria-hidden className="size-4" />
              {t("landing.ctaPrimary")}
            </Link>
            <a
              href="#how"
              className="inline-flex min-h-12 items-center gap-2 rounded-[var(--radius-input)] border border-line-strong bg-surface/80 px-6 font-semibold transition-colors duration-200 hover:bg-surface-2"
            >
              <ArrowDown aria-hidden className="size-4" />
              {t("landing.ctaSecondary")}
            </a>
          </div>
        </div>

        <div ref={card} className="glass rounded-[var(--radius-card)] border border-line p-4 md:p-6" data-testid="hero-runway">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-surface-2 px-2.5 py-1 font-semibold text-muted">
              <FlaskConical aria-hidden className="size-3.5" />
              {t("landing.demoTag")}
            </span>
            <span className="num font-semibold">{t("landing.now", { clock: clock(minute) })}</span>
          </div>
          <div className="mt-4 grid grid-cols-[6.5rem_1fr] items-center gap-5 md:grid-cols-[8.5rem_1fr]">
            <LiquidVessel fill={balance / CAPACITY} level={level} />
            <div>
              <p className="text-small text-muted">{t("float.cash")}</p>
              <MoneyText value={balance} className="font-display text-h1 font-bold md:text-display" />
              <p className="num mt-1 text-xs text-muted">
                {formatPercent(balance / CAPACITY, digits)} · {formatMoney(CAPACITY, digits, { lang, compact: true })}
              </p>
            </div>
          </div>
          <div className="mt-5">
            <HeroRunway minute={minute} onScrub={scrub} />
          </div>
          <p className="mt-2 text-xs text-muted">{t("landing.scrubHint")}</p>
        </div>
      </div>
    </section>
  );
}

import { Minus, Plus } from "lucide-react";
import { useId } from "react";
import { useTranslation } from "react-i18next";

import { formatMoney, formatNumber } from "../../../lib/format";
import { useLocale } from "../../../lib/prefs";
import { VAN_NS } from "../../../i18n/vanRoutes";
import { CONTROL_LIMITS, loadLimit, type Controls } from "./vanRoutesModel";

interface PlanControlsProps {
  value: Controls;
  onChange: (next: Controls) => void;
  /** A re-solve is running; the values stay editable. */
  busy: boolean;
}

const STEP_BUTTON =
  "grid size-11 place-items-center rounded-full border border-line-strong bg-surface text-fg shadow-xs hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-55";

interface AmountRangeProps {
  label: string;
  value: number;
  testId: string;
  onChange: (v: number) => void;
}

function AmountRange({ label, value, testId, onChange }: AmountRangeProps) {
  const { digits, lang } = useLocale();
  const id = useId();
  const { min, max, step } = CONTROL_LIMITS.amount;
  const text = formatMoney(value, digits, { compact: true, lang });
  return (
    <div className="min-w-0">
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={id} className="text-small font-semibold">
          {label}
        </label>
        <output htmlFor={id} className="num text-small font-semibold">
          {text}
        </output>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        aria-valuetext={text}
        onChange={(e) => onChange(Number(e.target.value))}
        data-testid={testId}
        className="mt-1 h-6 w-full cursor-pointer accent-[var(--pulse-blue)]"
      />
    </div>
  );
}

/** Vans, capacity and cash cap. The page solves again a moment after the last change. */
export function PlanControls({ value, onChange, busy }: PlanControlsProps) {
  const { t: tv } = useTranslation(VAN_NS);
  const { digits, lang } = useLocale();
  const uid = useId();
  const { min, max } = CONTROL_LIMITS.vehicles;

  return (
    <section aria-labelledby={`${uid}-title`} aria-busy={busy} className="ap-card p-4" data-testid="plan-controls">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id={`${uid}-title`} className="font-display text-h3 font-bold">
          {tv("controls.title")}
        </h2>
        <p className="text-small text-muted" role="status" data-testid="controls-status">
          {busy ? tv("controls.busy") : tv("controls.lead")}
        </p>
      </div>
      <div className="mt-3 grid gap-4 sm:grid-cols-[auto_minmax(0,1fr)_minmax(0,1fr)] sm:items-end">
        <div>
          <p id={`${uid}-vans`} className="text-small font-semibold">
            {tv("controls.vans")}
          </p>
          <div role="group" aria-labelledby={`${uid}-vans`} className="mt-1 flex items-center gap-3">
            <button
              type="button"
              className={STEP_BUTTON}
              aria-label={tv("controls.vansDec")}
              disabled={value.vehicles <= min}
              onClick={() => onChange({ ...value, vehicles: value.vehicles - 1 })}
              data-testid="vans-dec"
            >
              <Minus aria-hidden className="size-4" />
            </button>
            <output aria-live="polite" className="num min-w-6 text-center font-display text-h2 font-bold" data-testid="vans-count">
              {formatNumber(value.vehicles, digits)}
            </output>
            <button
              type="button"
              className={STEP_BUTTON}
              aria-label={tv("controls.vansInc")}
              disabled={value.vehicles >= max}
              onClick={() => onChange({ ...value, vehicles: value.vehicles + 1 })}
              data-testid="vans-inc"
            >
              <Plus aria-hidden className="size-4" />
            </button>
          </div>
        </div>
        <AmountRange
          label={tv("controls.capacity")}
          value={value.capacityBdt}
          testId="capacity-range"
          onChange={(v) => onChange({ ...value, capacityBdt: v })}
        />
        <AmountRange
          label={tv("controls.cashCap")}
          value={value.cashCapBdt}
          testId="cash-cap-range"
          onChange={(v) => onChange({ ...value, cashCapBdt: v })}
        />
      </div>
      <p className="mt-3 text-xs text-muted" data-testid="load-limit">
        {tv("controls.limit", { amount: formatMoney(loadLimit(value), digits, { compact: true, lang }) })}
      </p>
    </section>
  );
}

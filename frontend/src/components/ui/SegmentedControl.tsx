import * as ToggleGroup from "@radix-ui/react-toggle-group";
import type { LucideIcon } from "lucide-react";
import { motion } from "motion/react";
import { useId } from "react";

import { cn } from "../../lib/cn";
import { SPRING } from "../../styles/motion";

export interface SegmentOption<T extends string> {
  value: T;
  label: string;
  icon?: LucideIcon;
}

interface SegmentedControlProps<T extends string> {
  options: SegmentOption<T>[];
  value: T;
  onChange: (value: T) => void;
  label: string;
  size?: "sm" | "md";
  className?: string;
}

/** Single choice with a sliding pill. Never empties: clicking the active segment is ignored. */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  label,
  size = "md",
  className,
}: SegmentedControlProps<T>) {
  const layoutId = useId();
  return (
    <ToggleGroup.Root
      type="single"
      value={value}
      onValueChange={(next) => {
        const hit = options.find((o) => o.value === next);
        if (hit) onChange(hit.value);
      }}
      aria-label={label}
      className={cn("inline-flex max-w-full rounded-full border border-line bg-surface-2 p-1", className)}
    >
      {options.map(({ value: v, label: l, icon: Icon }) => (
        <ToggleGroup.Item
          key={v}
          value={v}
          className={cn(
            "relative isolate inline-flex items-center gap-1.5 rounded-full font-semibold transition-colors",
            size === "sm" ? "min-h-8 px-3 text-xs" : "min-h-10 px-4 text-small",
            v === value ? "text-fg" : "text-muted hover:text-fg",
          )}
        >
          {v === value ? (
            <motion.span
              layoutId={layoutId}
              transition={SPRING.snappy}
              className="absolute inset-0 -z-10 rounded-full bg-surface shadow-soft"
            />
          ) : null}
          {Icon ? <Icon aria-hidden className="size-4" /> : null}
          <span>{l}</span>
        </ToggleGroup.Item>
      ))}
    </ToggleGroup.Root>
  );
}

import { zodResolver } from "@hookform/resolvers/zod";
import { useMemo } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { useSaveTriggerSettings } from "../../../api/hooks/helpRequests";
import type { TriggerSettingsOut } from "../../../api/types";
import { LiquidButton } from "../../../components/ui/LiquidButton";
import { toast } from "../../../components/ui/toastStore";
import { NumberField } from "./NumberField";
import { triggerSchema, type TriggerForm as Form } from "./helpSettingsSchema";
import { HELP_ADMIN_NS } from "../../../i18n/helpAdmin";

/** When the automatic search fires: look-ahead, buffer, size limits, search radius, waves and timing. */
export function TriggerForm({ data }: { data: TriggerSettingsOut }) {
  const { t: th } = useTranslation(HELP_ADMIN_NS);
  const save = useSaveTriggerSettings();
  const schema = useMemo(
    () => triggerSchema({ number: th("number"), range: (min, max) => th("range", { min, max }) }),
    [th],
  );
  const form = useForm<Form>({ resolver: zodResolver(schema), values: { ...data } });
  const { register, handleSubmit, formState } = form;
  const e = formState.errors;
  const num = { valueAsNumber: true } as const;

  function onSubmit(values: Form): void {
    save.mutate(values, {
      onSuccess: () => toast({ tone: "success", title: th("saved") }),
      onError: () => toast({ tone: "error", title: th("saveFailed") }),
    });
  }

  return (
    <form onSubmit={(e) => void handleSubmit(onSubmit)(e)} noValidate className="ap-card space-y-5 p-5 shadow-soft" aria-labelledby="trigger-title">
      <h2 id="trigger-title" className="font-display text-h2 font-bold">
        {th("sections.trigger")}
      </h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <NumberField
          label={th("fields.horizon.label")}
          help={th("fields.horizon.help")}
          error={e.horizon_h?.message}
          step={1}
          {...register("horizon_h", num)}
        />
        <NumberField
          label={th("fields.buffer.label")}
          help={th("fields.buffer.help")}
          error={e.buffer_pct?.message}
          step="any"
          {...register("buffer_pct", num)}
        />
        <NumberField
          label={th("fields.minShortfall.label")}
          help={th("fields.minShortfall.help")}
          error={e.min_shortfall_bdt?.message}
          step="any"
          {...register("min_shortfall_bdt", num)}
        />
        <NumberField
          label={th("fields.maxRequest.label")}
          help={th("fields.maxRequest.help")}
          error={e.max_request_bdt?.message}
          step="any"
          {...register("max_request_bdt", num)}
        />
        <NumberField
          label={th("fields.leadMargin.label")}
          help={th("fields.leadMargin.help")}
          error={e.lead_margin_h?.message}
          step="any"
          {...register("lead_margin_h", num)}
        />
        <NumberField
          label={th("fields.recentAsk.label")}
          help={th("fields.recentAsk.help")}
          error={e.recent_ask_h?.message}
          step="any"
          {...register("recent_ask_h", num)}
        />
      </div>

      <h3 className="pt-2 font-semibold">{th("sections.waves")}</h3>
      <div className="grid gap-4 sm:grid-cols-2">
        <NumberField
          label={th("fields.radius.label")}
          help={th("fields.radius.help")}
          error={e.radius_km?.message}
          step="any"
          {...register("radius_km", num)}
        />
        <NumberField
          label={th("fields.maxWaves.label")}
          help={th("fields.maxWaves.help")}
          error={e.max_waves?.message}
          step={1}
          {...register("max_waves", num)}
        />
        <NumberField
          label={th("fields.waveTimeout.label")}
          help={th("fields.waveTimeout.help")}
          error={e.wave_timeout_min?.message}
          step={1}
          {...register("wave_timeout_min", num)}
        />
        <NumberField
          label={th("fields.deadlineFloor.label")}
          help={th("fields.deadlineFloor.help")}
          error={e.deadline_floor_min?.message}
          step={1}
          {...register("deadline_floor_min", num)}
        />
        <NumberField
          label={th("fields.urgentWave.label")}
          help={th("fields.urgentWave.help")}
          error={e.urgent_wave_multiplier?.message}
          step="any"
          {...register("urgent_wave_multiplier", num)}
        />
        <NumberField
          label={th("fields.perTick.label")}
          help={th("fields.perTick.help")}
          error={e.max_new_per_tick?.message}
          step={1}
          {...register("max_new_per_tick", num)}
        />
      </div>

      <div className="flex justify-end">
        <LiquidButton type="submit" loading={save.isPending} disabled={save.isPending}>
          {th("save")}
        </LiquidButton>
      </div>
    </form>
  );
}

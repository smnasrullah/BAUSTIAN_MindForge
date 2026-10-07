import { zodResolver } from "@hookform/resolvers/zod";
import { useMemo } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { useSaveHelpSettings } from "../../../api/hooks/helpRequests";
import type { HelpSettingsOut } from "../../../api/types";
import { LiquidButton } from "../../../components/ui/LiquidButton";
import { toast } from "../../../components/ui/toastStore";
import { NumberField } from "./NumberField";
import { policySchema, type PolicyForm as Form } from "./helpSettingsSchema";
import { HELP_ADMIN_NS } from "../../../i18n/helpAdmin";

/** Switches and limits: the kill switch, dry run, claim timeout, cooldown, daily cap and wave size. */
export function PolicyForm({ data }: { data: HelpSettingsOut }) {
  const { t: th } = useTranslation(HELP_ADMIN_NS);
  const save = useSaveHelpSettings();
  const schema = useMemo(
    () => policySchema({ number: th("number"), range: (min, max) => th("range", { min, max }) }),
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
    <form onSubmit={(e) => void handleSubmit(onSubmit)(e)} noValidate className="ap-card space-y-5 p-5 shadow-soft" aria-labelledby="policy-title">
      <h2 id="policy-title" className="font-display text-h2 font-bold">
        {th("sections.switches")}
      </h2>
      <label className="flex min-h-11 items-start gap-3">
        <input type="checkbox" className="mt-1 size-5 accent-(--color-pulse)" {...register("enabled")} />
        <span>
          <span className="block font-semibold">{th("fields.enabled.label")}</span>
          <span className="block text-xs text-muted">{th("fields.enabled.help")}</span>
        </span>
      </label>
      <label className="flex min-h-11 items-start gap-3">
        <input type="checkbox" className="mt-1 size-5 accent-(--color-pulse)" {...register("dry_run")} />
        <span>
          <span className="block font-semibold">{th("fields.dryRun.label")}</span>
          <span className="block text-xs text-muted">{th("fields.dryRun.help")}</span>
        </span>
      </label>

      <h3 className="pt-2 font-semibold">{th("sections.timing")}</h3>
      <div className="grid gap-4 sm:grid-cols-2">
        <NumberField
          label={th("fields.claimTimeout.label")}
          help={th("fields.claimTimeout.help")}
          error={e.claim_timeout_min?.message}
          step={1}
          {...register("claim_timeout_min", num)}
        />
        <NumberField
          label={th("fields.cooldown.label")}
          help={th("fields.cooldown.help")}
          error={e.cooldown_min?.message}
          step={1}
          {...register("cooldown_min", num)}
        />
        <NumberField
          label={th("fields.dailyCap.label")}
          help={th("fields.dailyCap.help")}
          error={e.daily_cap_per_agent?.message}
          step={1}
          {...register("daily_cap_per_agent", num)}
        />
        <NumberField
          label={th("fields.perWave.label")}
          help={th("fields.perWave.help")}
          error={e.max_recipients_per_wave?.message}
          step={1}
          {...register("max_recipients_per_wave", num)}
        />
        <NumberField
          label={th("fields.lateGrace.label")}
          help={th("fields.lateGrace.help")}
          error={e.late_confirm_grace_h?.message}
          step={1}
          {...register("late_confirm_grace_h", num)}
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

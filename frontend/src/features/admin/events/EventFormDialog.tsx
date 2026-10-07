import { zodResolver } from "@hookform/resolvers/zod";
import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useMemo } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { useSaveEvent } from "../../../api/hooks/events";
import type { EventItem } from "../../../api/types";
import { LiquidButton } from "../../../components/ui/LiquidButton";
import { toast } from "../../../components/ui/toastStore";
import { errorCode } from "../../../lib/apiError";
import { FIELD, LABEL } from "../shared/fields";
import { EVENT_TYPES, eventFromForm, eventSchema, formFromEvent, type EventForm } from "./eventForm";
import { useSingleFlight } from "../../../lib/useSingleFlight";

interface Props {
  /** null = closed; "new" = create; an event = edit. */
  target: EventItem | "new" | null;
  onClose: () => void;
}

function FieldError({ id, message }: { id: string; message?: string }) {
  return message ? (
    <p id={id} className="mt-1 text-xs text-act-fg">
      {message}
    </p>
  ) : null;
}

function EventFormBody({ event, onClose }: { event: EventItem | null; onClose: () => void }) {
  const { t } = useTranslation();
  const save = useSaveEvent();
  const schema = useMemo(
    () =>
      eventSchema({
        required: t("admin.common.required"),
        endAfterStart: t("admin.events.error.endAfterStart"),
        maxSpan: t("admin.events.error.maxSpan"),
        intensity: t("admin.events.error.intensity"),
      }),
    [t],
  );
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm<EventForm>({ resolver: zodResolver(schema), defaultValues: formFromEvent(event) });

  const once = useSingleFlight();
  const onSubmit = handleSubmit((values) => {
    once((done) => save.mutate(
      { id: event?.id ?? null, body: eventFromForm(values) },
      {
        onSettled: done,
        onSuccess: () => {
          toast({ tone: "success", title: t(event ? "admin.events.saved" : "admin.events.created") });
          onClose();
        },
        onError: (err) => {
          if (errorCode(err) === "unknown_district") setError("district", { message: t("admin.events.error.unknownDistrict") });
          else setError("root", { message: t("admin.events.error.save") });
        },
      },
    ));
  });

  const field = (name: keyof EventForm) => ({
    id: `event-${name}`,
    "aria-invalid": errors[name] ? true : undefined,
    "aria-describedby": errors[name] ? `event-${name}-error` : undefined,
  });

  return (
    <form onSubmit={(e) => void onSubmit(e)} noValidate className="mt-4 grid gap-4 sm:grid-cols-2" data-testid="event-form">
      <div>
        <label htmlFor="event-type" className={LABEL}>
          {t("admin.events.form.type")}
        </label>
        <select className={FIELD} {...field("type")} {...register("type")}>
          {EVENT_TYPES.map((type) => (
            <option key={type} value={type}>
              {t(`admin.events.type.${type}`)}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label htmlFor="event-intensity" className={LABEL}>
          {t("admin.events.form.intensity")}
        </label>
        <input type="number" step="0.1" min="0.1" max="10" inputMode="decimal" className={FIELD} {...field("intensity")} {...register("intensity", { valueAsNumber: true })} />
        <p className="mt-1 text-xs text-muted">{t("admin.events.form.intensityHint")}</p>
        <FieldError id="event-intensity-error" message={errors.intensity?.message} />
      </div>
      <div>
        <label htmlFor="event-name_en" className={LABEL}>
          {t("admin.events.form.nameEn")}
        </label>
        <input className={FIELD} {...field("name_en")} {...register("name_en")} />
        <FieldError id="event-name_en-error" message={errors.name_en?.message} />
      </div>
      <div>
        <label htmlFor="event-name_bn" className={LABEL}>
          {t("admin.events.form.nameBn")}
        </label>
        <input lang="bn" className={FIELD} {...field("name_bn")} {...register("name_bn")} />
        <FieldError id="event-name_bn-error" message={errors.name_bn?.message} />
      </div>
      <div>
        <label htmlFor="event-starts_at" className={LABEL}>
          {t("admin.events.form.startsAt")}
        </label>
        <input type="datetime-local" className={FIELD} {...field("starts_at")} {...register("starts_at")} />
        <FieldError id="event-starts_at-error" message={errors.starts_at?.message} />
      </div>
      <div>
        <label htmlFor="event-ends_at" className={LABEL}>
          {t("admin.events.form.endsAt")}
        </label>
        <input type="datetime-local" className={FIELD} {...field("ends_at")} {...register("ends_at")} />
        <FieldError id="event-ends_at-error" message={errors.ends_at?.message} />
      </div>
      <div className="sm:col-span-2">
        <label htmlFor="event-district" className={LABEL}>
          {t("admin.events.form.district")}
        </label>
        <input className={FIELD} {...field("district")} {...register("district")} />
        <p className="mt-1 text-xs text-muted">{t("admin.events.form.districtHint")}</p>
        <FieldError id="event-district-error" message={errors.district?.message} />
      </div>
      {errors.root?.message ? (
        <p role="alert" className="text-small text-act-fg sm:col-span-2">
          {errors.root.message}
        </p>
      ) : null}
      <div className="flex flex-wrap justify-end gap-2 sm:col-span-2">
        <Dialog.Close asChild>
          <LiquidButton type="button" variant="ghost">
            {t("common.cancel")}
          </LiquidButton>
        </Dialog.Close>
        <LiquidButton type="submit" loading={save.isPending}>
          {t(event ? "admin.events.form.save" : "admin.events.form.create")}
        </LiquidButton>
      </div>
    </form>
  );
}

export function EventFormDialog({ target, onClose }: Props) {
  const { t } = useTranslation();
  const event = target === "new" ? null : target;
  return (
    <Dialog.Root open={target !== null} onOpenChange={(open) => (open ? undefined : onClose())}>
      <Dialog.Portal>
        <Dialog.Overlay className="ap-overlay fixed inset-0 z-(--z-overlay) bg-ink-950/40 backdrop-blur-[2px]" />
        <Dialog.Content className="ap-dialog fixed left-1/2 top-1/2 z-(--z-overlay) max-h-[92vh] w-[min(94vw,40rem)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto ap-card p-6 text-fg shadow-lift">
          <div className="flex items-start justify-between gap-4">
            <Dialog.Title className="font-display text-h2 font-bold">{t(event ? "admin.events.form.titleEdit" : "admin.events.form.titleNew")}</Dialog.Title>
            <Dialog.Close aria-label={t("common.close")} className="-m-2 grid size-10 place-items-center rounded-full text-muted hover:bg-surface-2 hover:text-fg">
              <X aria-hidden className="size-4" />
            </Dialog.Close>
          </div>
          <Dialog.Description className="mt-1 text-small text-muted">{t("admin.events.lead")}</Dialog.Description>
          {target !== null ? <EventFormBody key={event?.id ?? "new"} event={event} onClose={onClose} /> : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

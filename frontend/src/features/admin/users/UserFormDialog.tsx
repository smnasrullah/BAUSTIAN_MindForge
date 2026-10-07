import { zodResolver } from "@hookform/resolvers/zod";
import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useMemo } from "react";
import { useForm, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { useCreateUser, useOrg, useUpdateUser } from "../../../api/hooks/admin";
import type { AdminUser } from "../../../api/types";
import { LiquidButton } from "../../../components/ui/LiquidButton";
import { toast } from "../../../components/ui/toastStore";
import { errorCode } from "../../../lib/apiError";
import { FIELD, LABEL } from "../shared/fields";
import { createBody, formFromUser, ROLES, updateBody, userSchema, type UserForm } from "./userForm";
import { useSingleFlight } from "../../../lib/useSingleFlight";

const SERVER_FIELD: Record<string, keyof UserForm> = {
  email_taken: "email",
  agent_required: "agent_id",
  unknown_agent: "agent_id",
  distributor_required: "distributor_id",
  unknown_distributor: "distributor_id",
};
const KNOWN = ["agent_required", "distributor_required", "unknown_agent", "unknown_distributor", "email_taken", "cannot_change_self"] as const;
type Known = (typeof KNOWN)[number];

function isKnown(code: string | null): code is Known {
  return KNOWN.some((k) => k === code);
}

function FieldError({ id, message }: { id: string; message?: string }) {
  return message ? (
    <p id={id} className="mt-1 text-xs text-act-fg">
      {message}
    </p>
  ) : null;
}

function UserFormBody({ user, onClose }: { user: AdminUser | null; onClose: () => void }) {
  const { t } = useTranslation();
  const org = useOrg();
  const create = useCreateUser();
  const update = useUpdateUser();
  const schema = useMemo(
    () =>
      userSchema(
        {
          required: t("admin.common.required"),
          email: t("admin.users.error.email"),
          password: t("admin.users.error.password"),
          agent: t("admin.users.error.agent_required"),
          distributor: t("admin.users.error.distributor_required"),
        },
        user === null,
      ),
    [t, user],
  );
  const {
    register,
    handleSubmit,
    setError,
    control,
    formState: { errors },
  } = useForm<UserForm>({ resolver: zodResolver(schema), defaultValues: formFromUser(user) });
  const role = useWatch({ control, name: "role" });

  function fail(err: unknown) {
    const code = errorCode(err);
    const message = t(isKnown(code) ? `admin.users.error.${code}` : "admin.users.error.generic");
    const field = code ? SERVER_FIELD[code] : undefined;
    setError(field ?? "root", { message });
  }

  const once = useSingleFlight();
  const onSubmit = handleSubmit((values) => {
    if (user === null) {
      once((done) => create.mutate(createBody(values), {
        onSuccess: () => {
          toast({ tone: "success", title: t("admin.users.created") });
          onClose();
        },
        onError: fail,
        onSettled: done,
      }));
      return;
    }
    // A pending sign-up is approved by switching it on together with its role and link.
    const body = user.is_pending ? { ...updateBody(user, values), is_active: true } : updateBody(user, values);
    if (Object.keys(body).length === 0) {
      onClose();
      return;
    }
    once((done) => update.mutate(
      { id: user.id, body },
      {
        onSuccess: () => {
          toast({ tone: "success", title: t(user.is_pending ? "admin.users.approved" : "admin.users.saved") });
          onClose();
        },
        onError: fail,
        onSettled: done,
      },
    ));
  });

  const aria = (name: keyof UserForm) => ({
    id: `user-${name}`,
    "aria-invalid": errors[name] ? true : undefined,
    "aria-describedby": errors[name] ? `user-${name}-error` : undefined,
  });

  return (
    <form onSubmit={(e) => void onSubmit(e)} noValidate className="mt-4 grid gap-4 sm:grid-cols-2" data-testid="user-form">
      <div className="sm:col-span-2">
        <label htmlFor="user-email" className={LABEL}>
          {t("admin.users.form.email")}
        </label>
        <input type="email" autoComplete="off" disabled={user !== null} className={FIELD} {...aria("email")} {...register("email")} />
        <FieldError id="user-email-error" message={errors.email?.message} />
      </div>
      <div>
        <label htmlFor="user-full_name" className={LABEL}>
          {t("admin.users.form.fullName")}
        </label>
        <input autoComplete="off" className={FIELD} {...aria("full_name")} {...register("full_name")} />
        <FieldError id="user-full_name-error" message={errors.full_name?.message} />
      </div>
      <div>
        <label htmlFor="user-role" className={LABEL}>
          {t("admin.users.form.role")}
        </label>
        <select className={FIELD} {...aria("role")} {...register("role")}>
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {t(`role.${r}`)}
            </option>
          ))}
        </select>
      </div>
      {role === "agent" ? (
        <div className="sm:col-span-2">
          <label htmlFor="user-agent_id" className={LABEL}>
            {t("admin.users.form.agent")}
          </label>
          <select className={FIELD} disabled={org.isPending} {...aria("agent_id")} {...register("agent_id")}>
            <option value="">{t("admin.users.form.pick")}</option>
            {org.data?.agents.map((a) => (
              <option key={a.id} value={String(a.id)}>
                {a.code} · {a.name}
              </option>
            ))}
          </select>
          <FieldError id="user-agent_id-error" message={errors.agent_id?.message} />
        </div>
      ) : null}
      {role === "distributor" ? (
        <div className="sm:col-span-2">
          <label htmlFor="user-distributor_id" className={LABEL}>
            {t("admin.users.form.distributor")}
          </label>
          <select className={FIELD} disabled={org.isPending} {...aria("distributor_id")} {...register("distributor_id")}>
            <option value="">{t("admin.users.form.pick")}</option>
            {org.data?.distributors.map((d) => (
              <option key={d.id} value={String(d.id)}>
                {d.code} · {d.name}
              </option>
            ))}
          </select>
          <FieldError id="user-distributor_id-error" message={errors.distributor_id?.message} />
        </div>
      ) : null}
      {user === null ? (
        <div className="sm:col-span-2">
          <label htmlFor="user-password" className={LABEL}>
            {t("admin.users.form.password")}
          </label>
          <input type="password" autoComplete="new-password" className={FIELD} {...aria("password")} {...register("password")} />
          <p className="mt-1 text-xs text-muted">{t("admin.users.form.passwordHint")}</p>
          <FieldError id="user-password-error" message={errors.password?.message} />
        </div>
      ) : null}
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
        <LiquidButton type="submit" loading={create.isPending || update.isPending}>
          {t(user?.is_pending ? "admin.users.approveSubmit" : user ? "admin.users.form.save" : "admin.users.form.create")}
        </LiquidButton>
      </div>
    </form>
  );
}

export function UserFormDialog({ target, onClose }: { target: AdminUser | "new" | null; onClose: () => void }) {
  const { t } = useTranslation();
  const user = target === "new" ? null : target;
  return (
    <Dialog.Root open={target !== null} onOpenChange={(open) => (open ? undefined : onClose())}>
      <Dialog.Portal>
        <Dialog.Overlay className="ap-overlay fixed inset-0 z-(--z-overlay) bg-ink-950/40 backdrop-blur-[2px]" />
        <Dialog.Content className="ap-dialog fixed left-1/2 top-1/2 z-(--z-overlay) max-h-[92vh] w-[min(94vw,36rem)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto ap-card p-6 text-fg shadow-lift">
          <div className="flex items-start justify-between gap-4">
            <Dialog.Title className="font-display text-h2 font-bold">
              {t(user?.is_pending ? "admin.users.approveTitle" : user ? "admin.users.form.titleEdit" : "admin.users.form.titleNew")}
            </Dialog.Title>
            <Dialog.Close aria-label={t("common.close")} className="-m-2 grid size-10 place-items-center rounded-full text-muted hover:bg-surface-2 hover:text-fg">
              <X aria-hidden className="size-4" />
            </Dialog.Close>
          </div>
          <Dialog.Description className="mt-1 text-small text-muted">{t(user?.is_pending ? "admin.users.approveBody" : "admin.users.lead")}</Dialog.Description>
          {target !== null ? <UserFormBody key={user?.id ?? "new"} user={user} onClose={onClose} /> : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

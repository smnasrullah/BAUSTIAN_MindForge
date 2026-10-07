import { zodResolver } from "@hookform/resolvers/zod";
import axios from "axios";
import { CircleAlert, CircleCheck, KeyRound } from "lucide-react";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { localizeDigits } from "../../lib/format";
import { useLocale } from "../../lib/prefs";
import { changePassword } from "../auth/authApi";
import { passwordStrength, type Strength } from "./passwordStrength";

const MIN = 8;

// Messages are changePassword.err.* keys, translated where they are shown.
const schema = z
  .object({
    oldPassword: z.string().min(1, "currentRequired"),
    newPassword: z.string().min(MIN, "min").max(128),
    confirm: z.string(),
  })
  .refine((v) => v.newPassword === v.confirm, { path: ["confirm"], message: "mismatch" })
  .refine((v) => v.newPassword !== v.oldPassword, { path: ["newPassword"], message: "same" });
type Form = z.infer<typeof schema>;
const ERR_KEYS = ["currentRequired", "min", "mismatch", "same"] as const;
type ErrKey = (typeof ERR_KEYS)[number];
const isErrKey = (m: string | undefined): m is ErrKey => ERR_KEYS.some((k) => k === m);

const LEVEL = { "too short": "tooShort", weak: "weak", fair: "fair", strong: "strong" } as const satisfies Record<Strength, string>;

/** changePassword.err.* key for a failed request. */
function errorKey(err: unknown): "wrong" | "same" | "failed" {
  const detail = axios.isAxiosError(err) ? (err.response?.data as { detail?: unknown } | undefined)?.detail : undefined;
  if (detail === "wrong_password") return "wrong";
  if (detail === "same_password") return "same";
  return "failed";
}

const fieldClass =
  "mt-1 block min-h-11 w-full rounded-xl border border-line bg-surface px-3 text-base text-fg aria-[invalid=true]:border-risk-red";

const FIELDS = [
  { name: "oldPassword", label: "changePassword.current", autoComplete: "current-password" },
  { name: "newPassword", label: "changePassword.new", autoComplete: "new-password" },
  { name: "confirm", label: "changePassword.confirm", autoComplete: "new-password" },
] as const;

export function ChangePasswordForm() {
  const { t } = useTranslation();
  const { digits } = useLocale();
  const min = localizeDigits(String(MIN), digits);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    control,
    formState: { errors, isSubmitting },
  } = useForm<Form>({ resolver: zodResolver(schema), defaultValues: { oldPassword: "", newPassword: "", confirm: "" } });
  const strength = passwordStrength(useWatch({ control, name: "newPassword" }));

  const onSubmit = handleSubmit(async (values) => {
    setResult(null);
    try {
      const revoked = await changePassword(values.oldPassword, values.newPassword);
      reset();
      setResult({ ok: true, text: t("changePassword.done", { count: revoked, n: localizeDigits(String(revoked), digits) }) });
    } catch (err) {
      setResult({ ok: false, text: t(`changePassword.err.${errorKey(err)}`) });
    }
  });

  return (
    <form className="space-y-4" onSubmit={(e) => void onSubmit(e)} noValidate aria-labelledby="change-password-title">
      <h2 id="change-password-title" className="flex items-center gap-2 font-display text-xl font-bold">
        <KeyRound className="size-5" aria-hidden />
        {t("changePassword.title")}
      </h2>
      {FIELDS.map((field) => {
        const error = errors[field.name];
        return (
          <div key={field.name}>
            <label htmlFor={field.name} className="text-sm font-semibold">
              {t(field.label)}
            </label>
            <input
              id={field.name}
              type="password"
              autoComplete={field.autoComplete}
              className={fieldClass}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? `${field.name}-error` : field.name === "newPassword" ? "strength" : undefined}
              {...register(field.name)}
            />
            {field.name === "newPassword" && !error ? (
              <p id="strength" className="mt-1 text-xs text-muted">
                {t("changePassword.strength", { level: t(`changePassword.level.${LEVEL[strength]}`), min })}
              </p>
            ) : null}
            {error ? (
              <p id={`${field.name}-error`} className="mt-1 text-sm text-act-fg">
                {isErrKey(error.message) ? t(`changePassword.err.${error.message}`, { min }) : t("changePassword.err.failed")}
              </p>
            ) : null}
          </div>
        );
      })}
      {result ? (
        <p role={result.ok ? "status" : "alert"} className="flex items-center gap-2 rounded-xl border border-line px-3 py-2 text-sm">
          {result.ok ? (
            <CircleCheck className="size-4 shrink-0 text-risk-green" aria-hidden />
          ) : (
            <CircleAlert className="size-4 shrink-0 text-risk-red" aria-hidden />
          )}
          {result.text}
        </p>
      ) : null}
      <button
        type="submit"
        disabled={isSubmitting}
        className="ap-press min-h-11 rounded-[var(--radius-input)] bg-primary px-5 font-semibold text-on-primary shadow-soft hover:bg-primary-hover disabled:opacity-60"
      >
        {isSubmitting ? t("changePassword.saving") : t("changePassword.submit")}
      </button>
    </form>
  );
}

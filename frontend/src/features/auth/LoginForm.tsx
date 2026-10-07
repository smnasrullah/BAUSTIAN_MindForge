import { CircleAlert, Eye, EyeOff, FlaskConical, Info, KeyRound, LogIn } from "lucide-react";
import { useAnimate } from "motion/react";
import { useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { LiquidButton } from "../../components/ui/LiquidButton";
import { localizeDigits } from "../../lib/format";
import { useReducedMotionPref } from "../../lib/motionPrefs";
import { useLocale } from "../../lib/prefs";
import { DUR, EASE } from "../../styles/motion";
import { login } from "./authApi";
import { useAuthStore } from "./authStore";
import { FloatingField } from "./FloatingField";
import { classifyLoginError, fieldErrorKey, formatCountdown, type LoginFailure } from "./loginErrors";
import { loginResolver, type LoginValues } from "./loginResolver";
import { ALL_ROLES, landingPath } from "./types";
import { useDemoLogin, useDemoMode } from "./useDemoLogin";

const SHAKE_X = [0, -10, 10, -6, 6, -2, 0];

/** Lockout countdown: seconds left, ticking once a second; the lock clears itself at zero. */
function useLockout(): { secondsLeft: number; lockFor: (seconds: number) => void } {
  const [lock, setLock] = useState<{ until: number; now: number } | null>(null);
  const until = lock?.until ?? null;
  useEffect(() => {
    if (until === null) return;
    const id = window.setInterval(() => {
      const now = Date.now();
      setLock(now >= until ? null : { until, now });
    }, 1000);
    return () => window.clearInterval(id);
  }, [until]);
  function lockFor(seconds: number) {
    const now = Date.now();
    setLock({ until: now + seconds * 1000, now });
  }
  return { secondsLeft: lock ? Math.max(0, (lock.until - lock.now) / 1000) : 0, lockFor };
}

export function LoginForm() {
  const { t } = useTranslation();
  const { digits } = useLocale();
  const reduced = useReducedMotionPref();
  const setSession = useAuthStore((s) => s.setSession);
  const notice = useAuthStore((s) => s.notice);
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from;
  const demoMode = useDemoMode();
  const demo = useDemoLogin();
  const [scope, animate] = useAnimate<HTMLDivElement>();
  const [failure, setFailure] = useState<LoginFailure | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const { secondsLeft, lockFor } = useLockout();
  const locked = secondsLeft > 0;

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginValues>({ resolver: loginResolver, mode: "onTouched", defaultValues: { email: "", password: "" } });

  function shake() {
    if (reduced || !scope.current) return;
    void animate(scope.current, { x: SHAKE_X }, { duration: DUR.reveal, ease: EASE });
  }

  async function submitValid(values: LoginValues) {
    setFailure(null);
    try {
      const tokens = await login(values.email, values.password);
      setSession(tokens);
      navigate(landingPath(tokens.user.role, from), { replace: true });
    } catch (err) {
      const result = classifyLoginError(err);
      setFailure(result);
      lockFor(result.kind === "locked" ? result.retryAfterS : 0);
      shake();
    }
  }

  // Built per submit (not during render): the handlers read the shake ref and the clock.
  function onSubmit(e: FormEvent<HTMLFormElement>) {
    void handleSubmit(submitValid, shake)(e);
  }

  function trackCaps(e: KeyboardEvent<HTMLInputElement>) {
    setCapsLock(e.getModifierState("CapsLock"));
  }

  const fieldError = (msg: string | undefined) => {
    const key = fieldErrorKey(msg);
    return key ? t(`login.err.${key}`) : undefined;
  };

  const serverMessage =
    failure === null
      ? null
      : failure.kind === "locked"
        ? locked
          ? t("login.err.locked", { time: localizeDigits(formatCountdown(secondsLeft), digits) })
          : null
        : t(`login.err.${failure.kind}`);
  const passwordField = register("password");

  return (
    <div ref={scope} className="ap-card p-6 shadow-lift md:p-8">
      <p className="ap-eyebrow">{t("login.eyebrow")}</p>
      <h1 className="mt-2 font-display text-h1 font-bold">{t("login.title")}</h1>
      <p className="mt-1 text-body text-muted">{t("login.subtitle")}</p>

      {notice ? (
        <p role="status" className="mt-5 flex items-center gap-2 rounded-[var(--radius-input)] border border-line bg-surface-2 px-3 py-2 text-small">
          <Info className="size-4 shrink-0 text-pulse-fg" aria-hidden />
          {t(`login.notice.${notice}`)}
        </p>
      ) : null}

      <form className="mt-6 space-y-4" onSubmit={onSubmit} noValidate>
        <FloatingField
          id="email"
          type="email"
          autoComplete="username"
          inputMode="email"
          label={t("login.email")}
          error={fieldError(errors.email?.message)}
          {...register("email")}
        />
        <FloatingField
          id="password"
          type={showPassword ? "text" : "password"}
          autoComplete="current-password"
          label={t("login.password")}
          error={fieldError(errors.password?.message)}
          {...passwordField}
          onKeyDown={trackCaps}
          onKeyUp={trackCaps}
          onBlur={(e) => {
            setCapsLock(false);
            void passwordField.onBlur(e);
          }}
          hint={
            capsLock ? (
              <p role="status" className="flex items-center gap-1.5 text-small text-watch-fg">
                <KeyRound aria-hidden className="size-4" />
                {t("login.capsLock")}
              </p>
            ) : undefined
          }
          trailing={
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              aria-label={t(showPassword ? "login.hide" : "login.show")}
              aria-pressed={showPassword}
              className="ap-press grid size-11 place-items-center rounded-[var(--radius-input)] text-muted hover:text-fg"
            >
              {showPassword ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
            </button>
          }
        />

        {serverMessage ? (
          <p role="alert" className="flex items-start gap-2 rounded-[var(--radius-input)] border border-act/40 bg-act/8 px-3 py-2 text-small">
            <CircleAlert className="mt-0.5 size-4 shrink-0 text-act-fg" aria-hidden />
            <span>{serverMessage}</span>
          </p>
        ) : null}

        <LiquidButton
          type="submit"
          size="lg"
          icon={LogIn}
          loading={isSubmitting}
          disabled={locked}
          data-testid="login-submit"
          className="w-full"
        >
          {isSubmitting ? t("login.submitting") : t("login.submit")}
        </LiquidButton>
      </form>
      <p className="mt-4 flex flex-wrap items-center justify-between gap-2 text-small">
        <Link to="/forgot-password" className="inline-flex min-h-11 items-center font-semibold text-pulse-fg underline-offset-4 hover:underline">
          {t("login.forgot")}
        </Link>
        <span className="text-muted">
          {t("login.noAccount")}{" "}
          <Link to="/signup" className="font-semibold text-pulse-fg underline-offset-4 hover:underline">
            {t("login.signupLink")}
          </Link>
        </span>
      </p>
      {demoMode ? (
        <section aria-labelledby="judge-demo-title" className="mt-6 border-t border-line pt-5" data-testid="judge-demo">
          <h2 id="judge-demo-title" className="flex items-center gap-2 text-small font-semibold">
            <FlaskConical aria-hidden className="size-4 text-pulse-fg" />
            {t("login.demoTitle")}
          </h2>
          <div className="mt-2 flex flex-wrap gap-2" role="group" aria-label={t("login.demoTitle")}>
            {ALL_ROLES.map((role) => (
              <LiquidButton
                key={role}
                variant="secondary"
                size="sm"
                loading={demo.pending === role}
                disabled={demo.pending !== null && demo.pending !== role}
                onClick={() => void demo.signIn(role)}
                data-testid={`demo-chip-${role}`}
                className="min-h-11 rounded-full px-4"
              >
                {t(`role.${role}`)}
              </LiquidButton>
            ))}
          </div>
          <p className="mt-2 text-xs text-muted">{t("login.demoHint")}</p>
          <p className="mt-1 text-xs text-muted">{t("login.passwordHint")}</p>
          {demo.failed ? (
            <p role="alert" className="mt-2 text-small text-act-fg">
              {t("login.err.demo")}
            </p>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

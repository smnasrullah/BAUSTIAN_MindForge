import type { FieldErrors, Resolver } from "react-hook-form";

export interface LoginValues {
  email: string;
  password: string;
}

// Same rule as the zod email check it replaces; zod stays out of the first-load JS.
const EMAIL_RE = /^(?!\.)(?!.*\.\.)([A-Za-z0-9_'+\-.]*)[A-Za-z0-9_+-]@([A-Za-z0-9][A-Za-z0-9-]*\.)+[A-Za-z]{2,}$/;

/** Field errors use message keys, translated at render. */
export const loginResolver: Resolver<LoginValues> = (values) => {
  const email = values.email.trim();
  const errors: FieldErrors<LoginValues> = {};
  if (email.length === 0) errors.email = { type: "too_small", message: "emailRequired" };
  else if (!EMAIL_RE.test(email)) errors.email = { type: "invalid_format", message: "emailInvalid" };
  if (values.password.length === 0) errors.password = { type: "too_small", message: "passwordRequired" };
  return Object.keys(errors).length > 0 ? { values: {}, errors } : { values: { ...values, email }, errors: {} };
};

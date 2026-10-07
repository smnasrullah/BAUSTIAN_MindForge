import axios, { type InternalAxiosRequestConfig } from "axios";

import { useAuthStore } from "../features/auth/authStore";
import type { TokenResponse } from "../features/auth/types";
import { isServerUnreachable, useServerHealth } from "./serverHealth";

const BASE_URL = "/api/v1";
const TIMEOUT_MS = 10_000;
const REFRESH_LOCK = "agentpulse-refresh";

export const api = axios.create({ baseURL: BASE_URL, timeout: TIMEOUT_MS });
/** No interceptors: used for refresh/logout so a 401 there cannot loop. */
export const authClient = axios.create({ baseURL: BASE_URL, timeout: TIMEOUT_MS });

const NO_REFRESH_PATHS = [
  "/auth/login",
  "/auth/demo-login",
  "/auth/refresh",
  "/auth/logout",
  "/auth/signup",
  "/auth/forgot-password",
  "/auth/reset-password",
];

interface RetriableConfig extends InternalAxiosRequestConfig {
  _retried?: boolean;
}

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken;
  if (token) config.headers.set("Authorization", `Bearer ${token}`);
  return config;
});

let inflight: Promise<string | null> | null = null;

/** One shared refresh for all requests in this tab that hit 401 at the same time. */
export function refreshAccessToken(): Promise<string | null> {
  inflight ??= withCrossTabLock(doRefresh).finally(() => {
    inflight = null;
  });
  return inflight;
}

/**
 * Tabs share the refresh cookie. Rotating it from two tabs at once would look like token reuse
 * and end the session, so refreshes are serialised across tabs when the browser allows it.
 */
function withCrossTabLock<T>(fn: () => Promise<T>): Promise<T> {
  const locks = typeof navigator !== "undefined" ? navigator.locks : undefined;
  return locks ? locks.request(REFRESH_LOCK, fn) : fn();
}

async function doRefresh(): Promise<string | null> {
  const { status, setSession, signOut } = useAuthStore.getState();
  try {
    const res = await authClient.post<TokenResponse>("/auth/refresh");
    setSession(res.data);
    return res.data.access_token;
  } catch (err) {
    const rejected = axios.isAxiosError(err) && err.response?.status === 401;
    // Only the server's "no" ends a session. A network blip, a 5xx or a restart keeps it: a live
    // session stays signed in, and the check on page load is retried by AuthBootstrap (signing
    // out there sent users with a valid cookie back to the login page).
    if (rejected) signOut(status === "signedIn" ? "session_expired" : null);
    return null;
  }
}

// Server reachability for the reconnect banner (app/shell/ServerBanner).
api.interceptors.response.use(
  (res) => {
    useServerHealth.getState().markUp();
    return res;
  },
  (error: unknown) => {
    if (isServerUnreachable(error)) useServerHealth.getState().markDown();
    return Promise.reject(error);
  },
);

api.interceptors.response.use(undefined, async (error: unknown) => {
  if (!axios.isAxiosError(error) || error.response?.status !== 401 || !error.config) {
    return Promise.reject(error);
  }
  const config: RetriableConfig = error.config;
  const url = config.url ?? "";
  if (config._retried || NO_REFRESH_PATHS.some((p) => url.startsWith(p))) {
    return Promise.reject(error);
  }
  config._retried = true;
  const token = await refreshAccessToken();
  if (!token) return Promise.reject(error);
  config.headers.set("Authorization", `Bearer ${token}`);
  return api(config);
});

import { useAuthStore } from "../../features/auth/authStore";
import { api, refreshAccessToken } from "../../lib/api";
import type { CopilotChatIn, CopilotSuggestions, Lang, LlmText } from "../types";

export async function copilotSuggestions(lang: Lang, signal?: AbortSignal): Promise<CopilotSuggestions> {
  return (await api.get<CopilotSuggestions>("/copilot/suggestions", { params: { lang }, signal })).data;
}

/** Where the backend routed the question (backend app/llm/copilot/intents.py Route). */
export type CopilotRoute = "blocked" | "off_topic" | "status" | "whatif" | "swap_status" | "forecast_window" | "howto";

/** Liquidity Playbook passage the answer is grounded in. */
export interface CopilotSource {
  slug: string;
  title: string;
  score: number;
}

/** SSE `meta` payload (backend CopilotMeta; the stream is not in the OpenAPI response models). */
export interface CopilotMeta {
  agent_id: number;
  route: CopilotRoute;
  /** Allow-listed read-only tool the backend ran, if any. */
  tool: { tool: string } | null;
  sources: CopilotSource[];
}

/** SSE `done` payload (backend CopilotReply). */
export interface CopilotReply extends CopilotMeta {
  answer: LlmText;
  /** Conversation the turn was saved in (a new one when none was sent). */
  conversation_id?: number | null;
}

/** POST /copilot/chat body; omit `conversation_id` to start a new conversation. */
export type CopilotChatBody = CopilotChatIn & { conversation_id?: number | null };

/** Backend CopilotConversationOut. */
export interface CopilotConversation {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

/** Backend CopilotMessageOut (stored text is redacted). */
export interface CopilotHistoryMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export async function copilotConversations(signal?: AbortSignal): Promise<CopilotConversation[]> {
  return (await api.get<CopilotConversation[]>("/copilot/conversations", { signal })).data;
}

export async function copilotConversationMessages(id: number, signal?: AbortSignal): Promise<CopilotHistoryMessage[]> {
  return (await api.get<CopilotHistoryMessage[]>(`/copilot/conversations/${id}/messages`, { signal })).data;
}

export interface CopilotHandlers {
  onMeta?: (meta: CopilotMeta) => void;
  /** Deterministic template answer, sent before the final wording. */
  onDraft: (text: string) => void;
  /** Next chunk of the final (verified) answer. */
  onDelta?: (text: string) => void;
  onDone: (reply: CopilotReply) => void;
}

const CHAT_URL = "/api/v1/copilot/chat";

function post(body: CopilotChatBody, token: string | null, signal?: AbortSignal): Promise<Response> {
  return fetch(CHAT_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify(body),
    signal,
  });
}

function dispatch(block: string, h: CopilotHandlers): void {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  if (data.length === 0) return;
  const payload: unknown = JSON.parse(data.join("\n"));
  if (event === "meta") h.onMeta?.(payload as CopilotMeta);
  else if (event === "template") h.onDraft((payload as { text: string }).text);
  else if (event === "delta") h.onDelta?.((payload as { text: string }).text);
  else if (event === "done") h.onDone(payload as CopilotReply);
  else if (event === "error") throw new Error((payload as { detail: string }).detail);
}

/**
 * POST /copilot/chat and read its event stream (fetch: axios cannot stream). `message` is sent
 * exactly as given. One token refresh on 401, like the axios client.
 */
export async function streamCopilotChat(body: CopilotChatBody, h: CopilotHandlers, signal?: AbortSignal): Promise<void> {
  let res = await post(body, useAuthStore.getState().accessToken, signal);
  if (res.status === 401) {
    const token = await refreshAccessToken();
    if (token) res = await post(body, token, signal);
  }
  if (!res.ok || !res.body) throw new Error(`copilot_http_${res.status}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = done ? "" : (blocks.pop() ?? "");
    for (const block of blocks) dispatch(block, h);
    if (done) return;
  }
}

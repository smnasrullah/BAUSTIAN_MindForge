import { useQueryClient } from "@tanstack/react-query";
import { Send, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { useCopilotMessages } from "../../../api/hooks/copilot";
import { qk } from "../../../api/keys";
import { streamCopilotChat } from "../../../api/services/copilot";
import { CopilotSheet } from "../../../components/signature/CopilotSheet";
import { LangText } from "../../../components/ui/LangText";
import { LiquidButton } from "../../../components/ui/LiquidButton";
import { PageHeader } from "../../../components/ui/PageHeader";
import { Skeleton } from "../../../components/ui/Skeleton";
import { ErrorState } from "../../../components/ui/StatePanel";
import { useLocale } from "../../../lib/prefs";
import { AnswerCard, type Turn } from "./AnswerCard";
import { ConversationList } from "./ConversationList";
import { MicButton } from "./MicButton";
import { SuggestionChips } from "./SuggestionChips";
import { useSpeechInput } from "./useSpeechInput";

const MAX_CHARS = 500;

/** Agent Copilot: ask about your own floats in Bangla or English, by text or voice. Advisory language only. */
export function CopilotPage() {
  const { t } = useTranslation();
  const { lang } = useLocale();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [conversationId, setConversationId] = useState<number | null>(null);
  // Stored history is loaded once per opened conversation; live turns render after it.
  const [loadedId, setLoadedId] = useState<number | null>(null);
  const queryClient = useQueryClient();
  const past = useCopilotMessages(loadedId);
  const nextId = useRef(1);
  const abort = useRef<AbortController | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const log = useRef<HTMLDivElement>(null);
  const busy = turns.some((x) => x.state === "pending");
  const hear = useCallback((heard: string) => setText(heard.slice(0, MAX_CHARS)), []);
  const speech = useSpeechInput(lang, hear);

  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => {
    const el = log.current?.parentElement;
    if (el && typeof el.scrollTo === "function") el.scrollTo({ top: el.scrollHeight });
  }, [turns]);
  useEffect(() => {
    if (speech.problem === "unsupported" || speech.problem === "denied") input.current?.focus();
  }, [speech.problem]);

  function startNew(): void {
    abort.current?.abort();
    setConversationId(null);
    setLoadedId(null);
    setTurns([]);
  }

  function open(id: number): void {
    if (id === conversationId) return;
    abort.current?.abort();
    setConversationId(id);
    setLoadedId(id);
    setTurns([]);
  }

  function update(id: number, patch: (x: Turn) => Partial<Turn>): void {
    setTurns((all) => all.map((x) => (x.id === id ? { ...x, ...patch(x) } : x)));
  }

  /** Sends `question` exactly as given (suggestion chips rely on exact-text replay). */
  function ask(question: string): void {
    if (busy || question.length === 0) return;
    speech.stop();
    const id = nextId.current++;
    setTurns((all) => [...all, { id, question, meta: null, draft: "", streamed: "", final: null, state: "pending" }]);
    abort.current = new AbortController();
    streamCopilotChat(
      { message: question, lang, ...(conversationId !== null ? { conversation_id: conversationId } : {}) },
      {
        onMeta: (meta) => update(id, () => ({ meta })),
        onDraft: (draft) => update(id, () => ({ draft })),
        onDelta: (part) => update(id, (x) => ({ streamed: x.streamed + part })),
        onDone: (reply) => {
          update(id, () => ({ meta: reply, final: reply.answer, state: "done" }));
          // Keep the live turns on screen; only the list needs refreshing.
          if (reply.conversation_id != null) setConversationId(reply.conversation_id);
          void queryClient.invalidateQueries({ queryKey: qk.copilotConversations() });
        },
      },
      abort.current.signal,
    ).catch((err: unknown) => {
      if (err instanceof DOMException && err.name === "AbortError") return;
      update(id, () => ({ state: "failed" }));
    });
  }

  function retry(turn: Turn): void {
    setTurns((all) => all.filter((x) => x.id !== turn.id));
    ask(turn.question);
  }

  function submit(e: FormEvent): void {
    e.preventDefault();
    const typed = text.trim();
    if (!typed) return;
    setText("");
    ask(typed);
  }

  const notice = (
    <p data-testid="copilot-notice" className="flex items-start gap-2 text-small lg:mx-auto lg:max-w-3xl">
      <ShieldCheck aria-hidden className="mt-0.5 size-4 shrink-0 text-safe-fg" />
      {t("copilot.notice")}
    </p>
  );

  const composer = (
    <form onSubmit={submit} className="space-y-2 lg:mx-auto lg:max-w-3xl">
      <div className="flex items-end gap-2">
        <MicButton listening={speech.listening} problem={speech.problem} disabled={busy} onStart={speech.start} onStop={speech.stop} />
        <label htmlFor="copilot-input" className="sr-only">
          {t("copilot.inputLabel")}
        </label>
        <input
          ref={input}
          id="copilot-input"
          value={text}
          maxLength={MAX_CHARS}
          onChange={(e) => setText(e.target.value)}
          placeholder={t(speech.listening ? "copilot.mic.listening" : "copilot.placeholder")}
          autoComplete="off"
          className="min-h-11 w-full min-w-0 rounded-[var(--radius-input)] border border-line-strong bg-surface px-3 text-body shadow-xs outline-none transition-[border-color,box-shadow] hover:border-ink-600/50 focus:border-pulse focus:ring-4 focus:ring-pulse/20"
        />
        <LiquidButton type="submit" icon={Send} disabled={busy || text.trim().length === 0} loading={busy}>
          {t("copilot.send")}
        </LiquidButton>
      </div>
      <p aria-live="polite" data-testid="copilot-mic-status" className="min-h-4 text-xs text-muted">
        {speech.listening ? t("copilot.mic.listening") : speech.problem ? t(`copilot.mic.${speech.problem}`) : ""}
      </p>
    </form>
  );

  return (
    // Desktop: a side panel (title + suggestions as a list) and a wide chat panel with a reading-width column.
    <div className="space-y-4 lg:grid lg:grid-cols-[minmax(16rem,22rem)_minmax(0,1fr)] lg:items-start lg:gap-6 lg:space-y-0">
      <div className="space-y-4 lg:sticky lg:top-20 lg:max-h-[calc(100dvh-7rem)] lg:overflow-y-auto lg:rounded-[var(--radius-card)] lg:border lg:border-line lg:bg-surface lg:p-5 lg:shadow-soft">
        <PageHeader title={t("copilot.title")} description={t("copilot.lead")} />
        <ConversationList activeId={conversationId} disabled={busy} onSelect={open} onNew={startNew} />
        <SuggestionChips onPick={ask} disabled={busy} />
      </div>

      <CopilotSheet label={t("copilot.sheet")} header={notice} footer={composer}>
        <div ref={log} className="space-y-3 lg:mx-auto lg:max-w-3xl">
          {loadedId === null ? null : past.isPending ? (
            <div className="space-y-2" aria-busy="true">
              <Skeleton className="ml-auto h-10 w-2/3" />
              <Skeleton className="h-16 w-full" />
            </div>
          ) : past.isError ? (
            <ErrorState compact body={t("copilot.history.error")} onRetry={() => void past.refetch()} retrying={past.isFetching} />
          ) : (
            <ol className="space-y-3" data-testid="copilot-history-log">
              {past.data.map((m) => (
                <li key={m.id}>
                  <p
                    className={
                      m.role === "user"
                        ? "ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-md bg-brand/15 px-4 py-2 text-body"
                        : "w-fit max-w-[92%] rounded-2xl rounded-bl-md border border-line bg-surface px-4 py-2 text-body"
                    }
                  >
                    <LangText text={m.content} />
                  </p>
                </li>
              ))}
            </ol>
          )}
          {turns.length === 0 ? (
            loadedId === null ? (
              <p className="text-small text-muted">{t("copilot.empty")}</p>
            ) : null
          ) : (
            <ol aria-live="polite" className="space-y-3" data-testid="copilot-log">
              {turns.map((x) => (
                <li key={x.id} className="space-y-2">
                  <p className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-md bg-brand/15 px-4 py-2 text-body" data-testid="copilot-question">
                    <LangText text={x.question} />
                  </p>
                  <AnswerCard turn={x} onRetry={() => retry(x)} retryDisabled={busy} />
                </li>
              ))}
            </ol>
          )}
        </div>
      </CopilotSheet>
    </div>
  );
}

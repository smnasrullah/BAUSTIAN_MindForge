import * as Dialog from "@radix-ui/react-dialog";
import { CircleCheck, ShieldCheck, X, XCircle } from "lucide-react";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { useDecideVanPlan, type VanPlan } from "../../../api/vanPlans";
import { LiquidButton } from "../../../components/ui/LiquidButton";
import { toast } from "../../../components/ui/toastStore";
import { errorCode } from "../../../lib/apiError";
import { formatMoney, formatNumber } from "../../../lib/format";
import { useLocale } from "../../../lib/prefs";
import { VAN_NS } from "../../../i18n/vanRoutes";
import { NOTE_MAX, NOTE_MIN } from "../decisionNote";

interface ApproveDialogProps {
  plan: VanPlan;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The decision was saved: the page keeps showing this plan (it is no longer pending). */
  onDecided: (planId: number) => void;
}

/** Approve or reject a plan. The note is required and goes to the audit log; no money moves. */
export function ApproveDialog({ plan, open, onOpenChange, onDecided }: ApproveDialogProps) {
  const { t } = useTranslation();
  const { t: tv } = useTranslation(VAN_NS);
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="ap-overlay fixed inset-0 z-(--z-overlay) bg-ink-950/40 backdrop-blur-[2px]" />
        <Dialog.Content
          data-testid="van-approve-dialog"
          className="ap-dialog fixed left-1/2 top-1/2 z-(--z-overlay) max-h-[92dvh] w-[min(94vw,30rem)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto ap-card p-6 text-fg shadow-lift"
        >
          <div className="flex items-start justify-between gap-4">
            <Dialog.Title className="font-display text-h2 font-bold">{tv("approve.title")}</Dialog.Title>
            <Dialog.Close aria-label={t("common.close")} className="-m-2 grid size-10 place-items-center rounded-full text-muted hover:bg-surface-2 hover:text-fg">
              <X aria-hidden className="size-4" />
            </Dialog.Close>
          </div>
          <Dialog.Description className="mt-1 text-small text-muted">{tv("approve.lead")}</Dialog.Description>
          {open ? <DialogBody plan={plan} onDone={() => onOpenChange(false)} onDecided={onDecided} /> : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function DialogBody({ plan, onDone, onDecided }: { plan: VanPlan; onDone: () => void; onDecided: (planId: number) => void }) {
  const { t } = useTranslation();
  const { t: tv } = useTranslation(VAN_NS);
  const { lang, digits } = useLocale();
  const noteId = useId();
  const [note, setNote] = useState("");
  const decide = useDecideVanPlan();
  const trimmed = note.trim();
  const noteOk = trimmed.length >= NOTE_MIN;

  function send(decision: "approve" | "reject"): void {
    decide.mutate(
      { id: plan.id, body: { decision, note: trimmed } },
      {
        onSuccess: () => {
          onDecided(plan.id);
          toast({ tone: "success", title: tv(`done.${decision}`), body: tv("done.body") });
          onDone();
        },
        onError: (err) => {
          const already = errorCode(err) === "already_decided";
          toast({ tone: "error", title: tv(already ? "error.already" : "error.failed") });
          if (already) onDone();
        },
      },
    );
  }

  return (
    <div className="mt-4 space-y-4">
      <p className="num rounded-2xl border border-line p-3 text-small" data-testid="van-approve-summary">
        {tv("approve.summary", {
          vans: formatNumber(plan.trips, digits),
          stops: formatNumber(plan.served, digits),
          km: formatNumber(plan.km, digits, { fraction: 1 }),
          total: formatMoney(plan.total_bdt, digits, { compact: true, lang }),
        })}
      </p>

      <div>
        <label htmlFor={noteId} className="text-small font-semibold">
          {t("dialog.note")}
        </label>
        <textarea
          id={noteId}
          value={note}
          maxLength={NOTE_MAX}
          onChange={(e) => setNote(e.target.value)}
          placeholder={t("dialog.notePlaceholder")}
          rows={3}
          aria-describedby={`${noteId}-hint`}
          data-testid="van-note"
          className="mt-1.5 w-full resize-none rounded-[var(--radius-input)] border border-line-strong bg-surface px-3 py-2 text-body shadow-xs outline-none transition-[border-color,box-shadow] hover:border-ink-600/50 focus:border-pulse focus:ring-4 focus:ring-pulse/20"
        />
        <p id={`${noteId}-hint`} className="mt-1 text-xs text-muted">
          {t("dialog.noteHint", { count: NOTE_MIN })}
        </p>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <LiquidButton icon={CircleCheck} disabled={!noteOk || decide.isPending} loading={decide.isPending && decide.variables?.body.decision === "approve"} onClick={() => send("approve")} data-testid="van-approve">
          {tv("approve.approve")}
        </LiquidButton>
        <LiquidButton variant="ghost" icon={XCircle} disabled={!noteOk || decide.isPending} onClick={() => send("reject")} data-testid="van-reject">
          {tv("approve.reject")}
        </LiquidButton>
      </div>

      <p className="flex items-center gap-1.5 text-xs text-muted">
        <ShieldCheck aria-hidden className="size-3.5" />
        {tv("notice")}
      </p>
    </div>
  );
}

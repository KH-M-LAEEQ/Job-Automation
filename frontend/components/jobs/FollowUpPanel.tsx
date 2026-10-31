"use client";

import { Send, Trash2 } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { useDiscardFollowup, useResolveFollowup, useSendFollowup } from "@/hooks/useApplications";
import { ApiError } from "@/lib/api-client";
import type { FollowUp } from "@/lib/types";

const STATUS_BADGE: Record<FollowUp["status"], string> = {
  pending_approval: "pending",
  sending: "pending",
  sent: "extracted",
  failed: "failed",
  discarded: "failed",
};

const STATUS_LABEL: Record<FollowUp["status"], string> = {
  pending_approval: "awaiting approval",
  sending: "send uncertain",
  sent: "sent",
  failed: "failed",
  discarded: "discarded",
};

function DraftEditor({ applicationId, draft }: { applicationId: string; draft: FollowUp }) {
  const [subject, setSubject] = useState(draft.subject);
  const [content, setContent] = useState(draft.content);
  const [error, setError] = useState<string | null>(null);
  const send = useSendFollowup(applicationId);
  const discard = useDiscardFollowup(applicationId);
  const busy = send.isPending || discard.isPending;

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    }
  }

  return (
    <div className="space-y-2 rounded-lg border border-amber-200 bg-amber-50/50 p-3 dark:border-amber-900/50 dark:bg-amber-950/20">
      <p className="text-xs text-amber-800 dark:text-amber-300">
        Draft follow-up to <span className="font-medium">{draft.recipient}</span>. Nothing is sent until you approve it.
        Check the address is the employer&apos;s and edit anything that isn&apos;t accurate.
      </p>
      <Input value={subject} onChange={(e) => setSubject(e.target.value)} aria-label="Subject" maxLength={300} />
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        aria-label="Email body"
        rows={6}
        maxLength={5000}
        className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
      />
      {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
      <div className="flex gap-2">
        <Button
          type="button"
          disabled={busy || !subject.trim() || !content.trim()}
          onClick={() => run(() => send.mutateAsync({ id: draft.id, subject, content }))}
        >
          {send.isPending ? <Spinner className="h-4 w-4" /> : <Send className="h-4 w-4" />}
          Approve and send
        </Button>
        <Button type="button" variant="secondary" disabled={busy} onClick={() => run(() => discard.mutateAsync(draft.id))}>
          <Trash2 className="h-4 w-4" />
          Discard
        </Button>
      </div>
    </div>
  );
}

function UncertainSend({ applicationId, followup }: { applicationId: string; followup: FollowUp }) {
  const resolve = useResolveFollowup(applicationId);
  const [error, setError] = useState<string | null>(null);

  async function answer(sent: boolean) {
    setError(null);
    try {
      await resolve.mutateAsync({ id: followup.id, sent });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    }
  }

  return (
    <div className="space-y-2 rounded-lg border border-zinc-200 p-3 text-sm dark:border-zinc-700">
      <p className="text-zinc-700 dark:text-zinc-300">
        Sending &quot;{followup.subject}&quot; to {followup.recipient} was interrupted, so it may or may not have
        gone out. It is never retried automatically. Check your mailbox&apos;s Sent folder, then record what happened.
      </p>
      {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
      <div className="flex gap-2">
        <Button type="button" variant="secondary" disabled={resolve.isPending} onClick={() => answer(true)}>
          It was sent
        </Button>
        <Button type="button" variant="secondary" disabled={resolve.isPending} onClick={() => answer(false)}>
          It wasn&apos;t sent
        </Button>
      </div>
    </div>
  );
}

export function FollowUpPanel({ applicationId, followups }: { applicationId: string; followups: FollowUp[] }) {
  const drafts = followups.filter((f) => f.status === "pending_approval");
  const uncertain = followups.filter((f) => f.status === "sending");
  const history = followups.filter((f) => f.status !== "pending_approval" && f.status !== "sending");
  return (
    <div className="rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
      <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-zinc-400">
        <Send className="h-3.5 w-3.5" />
        Follow-ups
      </p>
      <div className="space-y-3">
        {uncertain.map((followup) => (
          <UncertainSend key={followup.id} applicationId={applicationId} followup={followup} />
        ))}
        {drafts.map((draft) => (
          <DraftEditor key={draft.id} applicationId={applicationId} draft={draft} />
        ))}
        {history.length > 0 && (
          <ul className="space-y-2">
            {history.map((f) => (
              <li key={f.id} className="flex items-center justify-between gap-2 text-sm">
                <span className="truncate text-zinc-700 dark:text-zinc-300" title={f.error ?? undefined}>{f.subject}</span>
                <span className="flex shrink-0 items-center gap-2">
                  <span className="text-xs text-zinc-400">{new Date(f.decided_at ?? f.sent_at).toLocaleDateString()}</span>
                  <Badge status={STATUS_BADGE[f.status]}>{STATUS_LABEL[f.status]}</Badge>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowUp, Check, CornerDownRight, Loader2, Sparkles, User } from "lucide-react";
import type { AdvisorTurn, Message, Proposal, Spec } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

const SECTION_NOTE: Record<Proposal["section"], string> = {
  constraints: "constraint",
  discretion: "discretion",
  acceptance: "acceptance criterion",
};

type CardVerdict = "accepted" | "dismissed";

// The rail is one component, scoped by its props (0009 initiative rail / 0010 u5 project rail):
// `messagesUrl` + `advisorUrl` are where it reads/writes; `specId` (initiative scope only)
// enables the proposal-card accept flow. The project rail omits specId — it has no single spec.
export default function ConversationRail({
  messagesUrl,
  advisorUrl,
  mode,
  intro,
  subtitle = "how you author & steer it — your thinking partner",
  shapeHint = false,
  specId,
}: {
  messagesUrl: string;
  advisorUrl: string;
  mode: string;
  intro: string;
  subtitle?: string;
  shapeHint?: boolean;
  specId?: string;
}) {
  const router = useRouter();
  const [messages, setMessages] = useState<Message[] | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // per-proposal verdict, keyed by `${messageId}#${index}` — session-local UI state.
  const [cards, setCards] = useState<Record<string, CardVerdict>>({});
  const [cardBusy, setCardBusy] = useState<string | null>(null);
  const threadEnd = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch(messagesUrl, { cache: "no-store" });
      if (!res.ok) throw new Error(`couldn't load the conversation (${res.status})`);
      setMessages(await res.json());
    } catch (e) {
      setError((e as Error).message);
    }
  }, [messagesUrl]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    threadEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, sending]);

  async function send() {
    const content = input.trim();
    if (!content || sending) return;
    setSending(true);
    setError(null);
    // optimistic: show the human turn immediately
    const optimistic: Message = {
      id: `pending-${Date.now()}`,
      role: "human",
      content,
      metadata: {},
      created_at: new Date().toISOString(),
    };
    setMessages((cur) => [...(cur ?? []), optimistic]);
    setInput("");
    try {
      const res = await fetch(advisorUrl, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ content }),
      });
      if (!res.ok) {
        let msg = `the Advisor couldn't respond (${res.status})`;
        if (res.status === 502) msg = "the Advisor is unreachable — check the LLM key, then retry.";
        setError(msg);
        // drop the optimistic turn; nothing was persisted on a failure
        setMessages((cur) => (cur ?? []).filter((m) => m.id !== optimistic.id));
        setInput(content);
        return;
      }
      const turn: AdvisorTurn = await res.json();
      setMessages((cur) => [
        ...(cur ?? []).filter((m) => m.id !== optimistic.id),
        turn.human,
        turn.advisor,
      ]);
    } catch (e) {
      setError((e as Error).message);
      setMessages((cur) => (cur ?? []).filter((m) => m.id !== optimistic.id));
      setInput(content);
    } finally {
      setSending(false);
    }
  }

  async function accept(messageId: string, idx: number, p: Proposal) {
    if (!specId) return; // project rail has no spec to add to
    const key = `${messageId}#${idx}`;
    if (cardBusy) return;
    setCardBusy(key);
    setError(null);
    try {
      // read the live version so the optimistic-lock write is fresh
      const specRes = await fetch(`/api/specs/${specId}`, { cache: "no-store" });
      if (!specRes.ok) throw new Error(`couldn't read the spec (${specRes.status})`);
      const spec: Spec = await specRes.json();
      const body: Record<string, unknown> = {
        section: p.section,
        text: p.text,
        version: spec.version,
        provenance: "ai_proposed", // lands as a proposed item the human still confirms (a3)
      };
      if (p.section === "acceptance") {
        body.verify = { kind: p.verify_kind ?? "behavior", detail: p.verify_detail ?? p.text };
      }
      const res = await fetch(`/api/specs/${specId}/items`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.status === 409) {
        setError("the spec just changed — reopen it and try the card again.");
        return;
      }
      if (!res.ok) throw new Error(`couldn't add the item (${res.status})`);
      setCards((c) => ({ ...c, [key]: "accepted" }));
      router.refresh(); // nudge the server tree; the spec list itself shows it on reload
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCardBusy(null);
    }
  }

  function dismiss(messageId: string, idx: number) {
    setCards((c) => ({ ...c, [`${messageId}#${idx}`]: "dismissed" }));
  }

  const empty = messages !== null && messages.length === 0;

  return (
    <aside className="animate-rise flex flex-col overflow-hidden rounded-2xl bg-rail text-rail-foreground shadow-2xl ring-1 ring-black/20">
      <div className="border-b border-rail-border px-5 py-4">
        <div className="flex items-baseline justify-between">
          <span className="font-serif text-[15px] font-semibold">Conversation</span>
          <span className="flex items-center gap-1.5 font-mono text-[10px] tracking-wide text-rail-muted uppercase">
            <Sparkles className="size-3 text-primary" />
            advisor · {mode}
          </span>
        </div>
        <p className="mt-0.5 font-mono text-[10.5px] tracking-wide text-rail-muted">{subtitle}</p>
      </div>

      <div className="max-h-[460px] flex-1 space-y-4 overflow-y-auto px-5 py-4">
        {error && <p className="font-mono text-xs text-proposed">{error}</p>}

        {empty && !error && (
          <div className="py-2 text-sm leading-relaxed text-rail-muted">
            {intro}
            {shapeHint && (
              <>
                {" "}
                Try{" "}
                <code className="rounded bg-rail-card px-1 py-0.5 font-mono text-[11px] text-rail-foreground">
                  shape this initiative: …
                </code>{" "}
                for a full first draft.
              </>
            )}
          </div>
        )}

        {(messages ?? []).map((m) => (
          <MessageRow
            key={m.id}
            message={m}
            canAccept={!!specId}
            cards={cards}
            cardBusy={cardBusy}
            onAccept={accept}
            onDismiss={dismiss}
          />
        ))}

        {sending && (
          <div className="flex items-center gap-2 font-mono text-[11px] text-rail-muted">
            <Loader2 className="size-3 animate-spin text-primary" /> the Advisor is thinking…
          </div>
        )}
        <div ref={threadEnd} />
      </div>

      <div className="border-t border-rail-border p-3">
        <Textarea
          rows={2}
          value={input}
          disabled={sending}
          placeholder="Say what you mean…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              send();
            }
          }}
          className="resize-none border-rail-border bg-rail-card text-rail-foreground placeholder:text-rail-muted"
        />
        <div className="mt-2 flex items-center justify-between">
          <span className="font-mono text-[10px] tracking-wide text-rail-muted">⌘↵ to send</span>
          <Button size="sm" disabled={sending || !input.trim()} onClick={send}>
            {sending ? <Loader2 className="animate-spin" /> : <ArrowUp />} Send
          </Button>
        </div>
      </div>
    </aside>
  );
}

function MessageRow({
  message,
  canAccept,
  cards,
  cardBusy,
  onAccept,
  onDismiss,
}: {
  message: Message;
  canAccept: boolean;
  cards: Record<string, CardVerdict>;
  cardBusy: string | null;
  onAccept: (messageId: string, idx: number, p: Proposal) => void;
  onDismiss: (messageId: string, idx: number) => void;
}) {
  const isHuman = message.role === "human";
  const proposals = canAccept ? (message.metadata?.proposals ?? []) : [];
  return (
    <div>
      <div
        className={cn(
          "mb-1 flex items-center gap-1.5 font-mono text-[9.5px] tracking-[0.13em] uppercase",
          isHuman ? "text-rail-muted" : "text-primary",
        )}
      >
        {isHuman ? <User className="size-3" /> : <Sparkles className="size-3" />}
        {isHuman ? "you" : "advisor"}
      </div>
      <p
        className={cn(
          "text-[13px] leading-relaxed whitespace-pre-wrap",
          isHuman ? "text-rail-foreground" : "text-rail-foreground/90",
        )}
      >
        {message.content}
      </p>

      {proposals.length > 0 && (
        <div className="mt-2.5 space-y-2">
          {proposals.map((p, idx) => (
            <ProposalCard
              key={`${message.id}#${idx}`}
              proposal={p}
              verdict={cards[`${message.id}#${idx}`]}
              busy={cardBusy === `${message.id}#${idx}`}
              onAccept={() => onAccept(message.id, idx, p)}
              onDismiss={() => onDismiss(message.id, idx)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ProposalCard({
  proposal,
  verdict,
  busy,
  onAccept,
  onDismiss,
}: {
  proposal: Proposal;
  verdict?: CardVerdict;
  busy: boolean;
  onAccept: () => void;
  onDismiss: () => void;
}) {
  if (verdict) {
    return (
      <div className="flex items-start gap-1.5 font-mono text-[11px] leading-relaxed text-rail-muted">
        <CornerDownRight className="mt-0.5 size-3 shrink-0" />
        {verdict === "accepted"
          ? `Added to ${proposal.section} as a proposed item — confirm it in the spec to make it govern.`
          : "Left out."}
      </div>
    );
  }
  return (
    <div className="rounded-xl border border-primary/40 bg-rail-card p-3.5">
      <div className="mb-1.5 flex items-center gap-1.5 font-mono text-[9.5px] tracking-[0.1em] text-primary uppercase">
        <Sparkles className="size-3" /> proposed {SECTION_NOTE[proposal.section]}
      </div>
      <p className="text-[12.5px] leading-snug text-rail-foreground">{proposal.text}</p>
      {proposal.section === "acceptance" && proposal.verify_kind && (
        <p className="mt-1.5 font-mono text-[10px] text-rail-muted">
          verify: {proposal.verify_kind}
          {proposal.verify_detail ? ` — ${proposal.verify_detail}` : ""}
        </p>
      )}
      <div className="mt-3 flex items-center justify-between gap-2">
        <span className="font-mono text-[10px] text-rail-muted">add to the spec?</span>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={onDismiss}
            className="h-7 border border-rail-border px-2.5 text-xs text-rail-foreground hover:bg-white/5"
          >
            Dismiss
          </Button>
          <Button size="sm" disabled={busy} onClick={onAccept} className="h-7 px-2.5 text-xs">
            {busy ? <Loader2 className="animate-spin" /> : <Check />} Accept
          </Button>
        </div>
      </div>
    </div>
  );
}

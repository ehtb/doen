"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  ArrowUp,
  Check,
  CornerDownRight,
  FilePlus2,
  Loader2,
  RotateCcw,
  Sparkles,
  User,
  ClipboardList,
  X,
} from "lucide-react";
import type {
  AcceptanceCriterion,
  AdvisorReply,
  Message,
  Proposal,
  Spec,
} from "@/lib/types";
import {
  appendMessage,
  clearConversation,
  type ConversationScope,
  deleteMessage,
  loadConversation,
  recentWindow,
  updateProposalVerdict,
} from "@/lib/conversations";
import { stashInitiativeDraft } from "@/lib/initiativeDraft";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { useSpecOptional } from "./spec-context";

const SECTION_NOTE: Record<Proposal["section"], string> = {
  constraints: "constraint",
  discretion: "discretion",
  acceptance: "acceptance criterion",
};

type CardVerdict = "accepted" | "dismissed";

// The rail is one component, scoped by its props (0009 initiative rail / 0010 u5 project rail):
// `scope` is the IndexedDB conversation it reads/writes (browser-local now — spec uvama);
// `advisorUrl` is the stateless Advisor endpoint it POSTs a windowed slice to; `specId`
// (initiative scope only) enables the proposal-card accept flow. The project rail omits specId.
// BD-20: `discoverable` enables the guided discovery mode toggle (project rail only).
export default function ConversationRail({
  scope,
  advisorUrl,
  mode,
  intro,
  subtitle = "how you author & steer it — your thinking partner",
  hintPrompt,
  specId,
  review,
  discoverable = false,
}: {
  scope: ConversationScope;
  advisorUrl: string;
  mode: string;
  intro: string;
  subtitle?: string;
  hintPrompt?: string;
  specId?: string;
  // 0012 u3: an optional guided-review panel pinned at the top of the thread (initiative rail only).
  review?: ReactNode;
  // BD-20: enables the discovery mode toggle (project rail only).
  discoverable?: boolean;
}) {
  const specCtx = useSpecOptional();
  // The parent passes a fresh scope object each render; pin it to a stable identity keyed by the
  // owning id so the load effect doesn't re-fire every render.
  const isProject = !("initiativeId" in scope);
  const scopeId =
    "initiativeId" in scope
      ? scope.initiativeId
      : "projectId" in scope
      ? scope.projectId
      : scope.discoveryProjectId;

  // BD-20: discovery mode is a separate conversation thread (distinct IndexedDB scope) with a
  // different system prompt. Only enabled on the project rail when `discoverable` is true.
  const [railMode, setRailMode] = useState<"general" | "discovery">(
    "discoveryProjectId" in scope ? "discovery" : "general"
  );

  const convo = useMemo<ConversationScope>(() => {
    if (!isProject) return { initiativeId: scopeId };
    if (railMode === "discovery") return { discoveryProjectId: scopeId };
    return { projectId: scopeId };
  }, [isProject, scopeId, railMode]);

  const [messages, setMessages] = useState<Message[] | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // per-proposal verdict, keyed by `${messageId}#${index}` — session-local UI state.
  const [cards, setCards] = useState<Record<string, CardVerdict>>({});
  const [cardBusy, setCardBusy] = useState<string | null>(null);
  // Reset flow: a one-step inline confirmation (no native confirm(), no new dialog dep) whose copy
  // makes the blast radius explicit — only the on-device message history clears.
  const [confirmingReset, setConfirmingReset] = useState(false);
  const [resetting, setResetting] = useState(false);
  // BD-1 u3 (project rail only): a synthesised PROPOSED initiative description per advisor message
  // id. Transient session state — never written to IndexedDB — so the 'Create initiative from this'
  // action shows only for a real synthesis and is gone on reload or reset.
  const [synthesis, setSynthesis] = useState<Record<string, string>>({});
  // BD-20: initiative type hint from discovery mode, keyed by message id alongside synthesis.
  const [synthesisTypes, setSynthesisTypes] = useState<
    Record<string, "engineering" | "research">
  >({});
  // BD-15: evidence submission from the rail. `evidenceOpen` tracks which message's panel is open;
  // `evidenceBusy` is the criterion id currently being submitted (only one at a time).
  const [evidenceOpen, setEvidenceOpen] = useState<string | null>(null);
  const [evidenceBusy, setEvidenceBusy] = useState<string | null>(null);
  const threadEnd = useRef<HTMLDivElement>(null);

  // BD-20: when switching modes, clear transient synthesis/reset state — the new mode's conversation
  // loads fresh and prior-mode synthesis isn't relevant.
  useEffect(() => {
    setConfirmingReset(false);
    setSynthesis({});
    setSynthesisTypes({});
  }, [railMode]);

  // The confirmed criteria available for evidence submission (initiative rail only).
  const confirmedCriteria: AcceptanceCriterion[] =
    specCtx?.spec.acceptance.filter((c) => c.status === "confirmed") ?? [];

  const load = useCallback(async () => {
    try {
      const loaded = await loadConversation(convo);
      setMessages(loaded);
      // Restore verdicts from persisted proposal state so dismissed/accepted cards survive reload.
      const restoredCards: Record<string, CardVerdict> = {};
      for (const msg of loaded) {
        const proposals = msg.metadata?.proposals ?? [];
        proposals.forEach((p, idx) => {
          if (p.verdict) restoredCards[`${msg.id}#${idx}`] = p.verdict;
        });
      }
      setCards(restoredCards);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [convo]);

  useEffect(() => {
    load();
  }, [load]);

  // Listen for external reset events (from ResetConversationLink).
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<ConversationScope>).detail;
      const matches =
        ("initiativeId" in detail && "initiativeId" in convo && detail.initiativeId === convo.initiativeId) ||
        ("projectId" in detail && "projectId" in convo && detail.projectId === convo.projectId);
      if (matches) {
        setMessages([]);
        setCards({});
        setSynthesis({});
        setSynthesisTypes({});
        setConfirmingReset(false);
      }
    };
    window.addEventListener("doen:conversation-reset", handler);
    return () => window.removeEventListener("doen:conversation-reset", handler);
  }, [convo]);

  useEffect(() => {
    threadEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, sending]);

  // 0013 u3: the kickoff surface can ask the Advisor to decompose the spec. It sets a one-shot
  // rail prompt; we send it once the rail is free, then clear it so it can't re-fire.
  useEffect(() => {
    const pending = specCtx?.railPrompt;
    if (pending && !sending) {
      specCtx?.clearRailPrompt();
      send(pending);
    }
    // send is a stable closure over component state; re-running on prompt/sending is enough.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [specCtx?.railPrompt, sending]);

  async function send(explicit?: string) {
    const content = (explicit ?? input).trim();
    if (!content || sending) return;
    setSending(true);
    setError(null);

    // The windowed slice the Advisor sees is the recent history BEFORE this new turn, read live
    // from IndexedDB — not from the in-memory `messages` cache. Re-querying on every call is what
    // makes a reset take effect immediately: right after clearConversation this returns [], so the
    // next turn carries no prior history (AC item_599cae4aaa38).
    let history: { role: "human" | "advisor"; content: string }[];
    try {
      history = await recentWindow(convo);
    } catch (e) {
      setError((e as Error).message);
      setSending(false);
      return;
    }

    // Persist + show the human turn immediately (browser-local; survives a refresh).
    let human: Message;
    try {
      human = await appendMessage(convo, { role: "human", content });
    } catch (e) {
      setError((e as Error).message);
      setSending(false);
      return;
    }
    setMessages((cur) => [...(cur ?? []), human]);
    setInput("");

    try {
      const res = await fetch(advisorUrl, {
        method: "POST",
        headers: { "content-type": "application/json" },
        // BD-20: include railMode so the backend uses the discovery system prompt when appropriate.
        body: JSON.stringify({ content, history, mode: isProject ? railMode : "general" }),
      });
      if (!res.ok) {
        let msg = `the Advisor couldn't respond (${res.status})`;
        if (res.status === 502)
          msg = "the Advisor is unreachable — check the LLM key, then retry.";
        setError(msg);
        // nothing was generated — roll the human turn back so it isn't left dangling
        await deleteMessage(human.id);
        setMessages((cur) => (cur ?? []).filter((m) => m.id !== human.id));
        setInput(content);
        return;
      }
      const reply: AdvisorReply = await res.json();
      // Write the Advisor's reply into IndexedDB (with any proposal cards in metadata).
      const advisor = await appendMessage(convo, {
        role: "advisor",
        content: reply.message.content,
        metadata: reply.message.metadata,
      });
      setMessages((cur) => [...(cur ?? []), advisor]);
      // BD-1 u3: if this project turn synthesised a proposed initiative, hang it off this message
      // (transient — not persisted) so its 'Create initiative from this' action renders inline.
      if (isProject && reply.proposed_initiative?.trim()) {
        const description = reply.proposed_initiative.trim();
        setSynthesis((s) => ({ ...s, [advisor.id]: description }));
        // BD-20: also stash the initiative type hint when provided (discovery mode).
        if (reply.proposed_initiative_type) {
          setSynthesisTypes((s) => ({
            ...s,
            [advisor.id]: reply.proposed_initiative_type!,
          }));
        }
      }
    } catch (e) {
      setError((e as Error).message);
      await deleteMessage(human.id);
      setMessages((cur) => (cur ?? []).filter((m) => m.id !== human.id));
      setInput(content);
    } finally {
      setSending(false);
    }
  }

  // BD-15: submit an Advisor message's content as evidence against a criterion.
  async function submitEvidence(criterionId: string, content: string) {
    if (!specId || evidenceBusy) return;
    setEvidenceBusy(criterionId);
    setError(null);
    try {
      const evidence = content.length > 2000 ? content.slice(0, 2000) : content;
      const res = await fetch(
        `/api/specs/${specId}/criteria/${criterionId}/evidence`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ evidence }),
        },
      );
      if (!res.ok) throw new Error(`couldn't submit evidence (${res.status})`);
      setEvidenceOpen(null);
      await specCtx?.refreshSpec();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setEvidenceBusy(null);
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
      const specRes = await fetch(`/api/specs/${specId}`, {
        cache: "no-store",
      });
      if (!specRes.ok)
        throw new Error(`couldn't read the spec (${specRes.status})`);
      const spec: Spec = await specRes.json();
      const body: Record<string, unknown> = {
        section: p.section,
        text: p.text,
        version: spec.version,
        provenance: "ai_proposed", // lands as a proposed item the human still confirms (a3)
      };
      if (p.section === "acceptance") {
        body.verify = p.verify ?? { kind: "behavior", detail: p.text };
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
      await updateProposalVerdict(messageId, idx, "accepted");
      await specCtx?.refreshSpec(); // pull the updated spec into the context immediately
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCardBusy(null);
    }
  }

  function dismiss(messageId: string, idx: number) {
    setCards((c) => ({ ...c, [`${messageId}#${idx}`]: "dismissed" }));
    updateProposalVerdict(messageId, idx, "dismissed").catch(() => {});
  }

  // Wipe every message for this conversation from IndexedDB and reset the rail to a fresh session.
  // Only the message history is touched — the spec, decisions, work units, and memory are separate
  // stores entirely and untouched. We don't navigate or reload, so the rest of the view stays put;
  // we don't auto-send a greeting — the next human turn simply starts with no prior history.
  async function reset() {
    if (resetting) return;
    setResetting(true);
    setError(null);
    try {
      await clearConversation(convo);
      setMessages([]);
      setCards({});
      setSynthesis({});
      setSynthesisTypes({});
      setConfirmingReset(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setResetting(false);
    }
  }

  const empty = messages !== null && messages.length === 0;
  const hasHistory = (messages?.length ?? 0) > 0;

  // BD-20: discovery mode presents different copy throughout the rail.
  const effectiveSubtitle =
    isProject && railMode === "discovery"
      ? "guided discovery — from observation to initiative"
      : subtitle;
  const effectiveIntro =
    isProject && railMode === "discovery"
      ? "Start with what you're noticing — a problem, a gap, or something that's bugging you. I'll guide you from there to a shaped initiative, one question at a time."
      : intro;

  return (
    <aside className="animate-rise flex flex-col overflow-hidden rounded-xl border border-border bg-card text-rail-foreground">
      <div className="border-b border-border px-5 py-4">
        <div className="flex items-baseline justify-between">
          <span className="font-serif text-[15px] font-semibold">
            Conversation
          </span>
          <span className="flex items-center gap-1.5 font-mono text-[10px] tracking-wide text-rail-muted uppercase">
            <Sparkles className="size-3 text-primary" />
            advisor · {mode}
          </span>
        </div>
        <div className="mt-0.5 flex items-baseline justify-between gap-3">
          <p className="font-mono text-[10.5px] tracking-wide text-rail-muted">
            {effectiveSubtitle}
          </p>
          {hasHistory && !confirmingReset && (
            <button
              type="button"
              onClick={() => setConfirmingReset(true)}
              className="flex shrink-0 items-center gap-1 font-mono text-[10px] tracking-wide text-rail-muted uppercase transition-colors hover:text-rail-foreground"
            >
              <RotateCcw className="size-2.5" /> Reset
            </button>
          )}
        </div>
        {/* BD-20: discovery mode toggle — only on the project rail */}
        {discoverable && (
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              onClick={() => setRailMode("general")}
              className={cn(
                "flex-1 rounded-md border px-3 py-1.5 font-mono text-[10px] tracking-wide transition-colors",
                railMode === "general"
                  ? "border-primary/40 bg-primary/10 text-accent-deep"
                  : "border-rail-border text-rail-muted hover:border-rail-border/80 hover:text-rail-foreground",
              )}
            >
              General
            </button>
            <button
              type="button"
              onClick={() => setRailMode("discovery")}
              className={cn(
                "flex-[2] rounded-md border px-3 py-1.5 font-mono text-[10px] tracking-wide transition-colors",
                railMode === "discovery"
                  ? "border-primary/40 bg-primary/10 text-accent-deep"
                  : "border-rail-border text-rail-muted hover:border-rail-border/80 hover:text-rail-foreground",
              )}
            >
              Discover what to build
            </button>
          </div>
        )}
      </div>

      <div className="max-h-[460px] flex-1 space-y-4 overflow-y-auto px-5 py-4">
        {confirmingReset && (
          <div className="rounded-xl border border-rail-border bg-rail-card p-3.5">
            <div className="mb-1.5 flex items-center gap-1.5 font-mono text-[9.5px] tracking-[0.1em] text-rail-muted uppercase">
              <RotateCcw className="size-3" /> reset conversation
            </div>
            <p className="text-[13px] leading-snug text-rail-foreground">
              This clears the message history for this{" "}
              {isProject ? "project" : "initiative"} on this device only. Your
              spec, decisions, work units, and memory are unaffected — the
              Advisor simply starts fresh.
            </p>
            <div className="mt-3 flex items-center justify-end gap-2">
              <Button
                size="sm"
                variant="ghost"
                disabled={resetting}
                onClick={() => setConfirmingReset(false)}
                className="h-7 border border-rail-border px-2.5 text-xs text-rail-foreground hover:bg-black/5"
              >
                Cancel
              </Button>
              <Button
                size="sm"
                disabled={resetting}
                onClick={reset}
                className="h-7 px-2.5 text-xs"
              >
                {resetting ? (
                  <Loader2 className="animate-spin" />
                ) : (
                  <RotateCcw />
                )}{" "}
                Reset conversation
              </Button>
            </div>
          </div>
        )}
        {review}
        {error && <p className="font-mono text-xs text-proposed">{error}</p>}

        {empty && !error && (
          <div className="pt-2 text-sm leading-relaxed text-rail-muted">
            {effectiveIntro}
            {hintPrompt && railMode !== "discovery" && (
              <>
                {" "}
                Try{" "}
                <code className="rounded bg-rail-card px-1 py-0.5 font-mono text-[11px] text-rail-foreground">
                  {hintPrompt}
                </code>
                .
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
            synthesis={synthesis[m.id]}
            onCreateInitiative={() =>
              stashInitiativeDraft(scopeId, synthesis[m.id], synthesisTypes[m.id])
            }
            // BD-15: evidence submission from the rail
            criteria={confirmedCriteria}
            evidenceOpen={evidenceOpen === m.id}
            evidenceBusy={evidenceBusy}
            onToggleEvidence={() =>
              setEvidenceOpen((cur) => (cur === m.id ? null : m.id))
            }
            onSubmitEvidence={submitEvidence}
          />
        ))}

        {sending && (
          <div className="flex items-center gap-2 font-mono text-[11px] text-rail-muted">
            <Loader2 className="size-3 animate-spin text-primary" /> the Advisor
            is thinking…
          </div>
        )}
        <div ref={threadEnd} />
      </div>

      <div className="border-t border-border p-3">
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
          className="resize-none border-border bg-rail-card text-rail-foreground placeholder:text-rail-muted"
        />
        <div className="mt-2 flex items-center justify-between">
          <span className="font-mono text-[10px] tracking-wide text-rail-muted">
            ⌘↵ to send
          </span>
          <Button
            size="sm"
            disabled={sending || !input.trim()}
            onClick={() => send()}
          >
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
  synthesis,
  onCreateInitiative,
  criteria,
  evidenceOpen,
  evidenceBusy,
  onToggleEvidence,
  onSubmitEvidence,
}: {
  message: Message;
  canAccept: boolean;
  cards: Record<string, CardVerdict>;
  cardBusy: string | null;
  onAccept: (messageId: string, idx: number, p: Proposal) => void;
  onDismiss: (messageId: string, idx: number) => void;
  synthesis?: string;
  onCreateInitiative?: () => void;
  // BD-15: evidence submission from the rail
  criteria?: AcceptanceCriterion[];
  evidenceOpen?: boolean;
  evidenceBusy?: string | null;
  onToggleEvidence?: () => void;
  onSubmitEvidence?: (criterionId: string, content: string) => void;
}) {
  const [selectedCriterion, setSelectedCriterion] = useState<string>("");
  const isHuman = message.role === "human";
  const proposals = canAccept ? (message.metadata?.proposals ?? []) : [];
  const canSubmitEvidence =
    !isHuman && !!canAccept && !!criteria?.length && !!onSubmitEvidence;

  // Reset criterion selection whenever the panel is closed so a re-open starts fresh.
  useEffect(() => {
    if (!evidenceOpen) setSelectedCriterion("");
  }, [evidenceOpen]);

  return (
    <div>
      <div
        className={cn(
          "mb-1 flex items-center gap-1.5 font-mono text-[9.5px] tracking-[0.13em] uppercase",
          isHuman ? "text-rail-muted" : "text-primary",
        )}
      >
        {isHuman ? (
          <User className="size-3" />
        ) : (
          <Sparkles className="size-3" />
        )}
        {isHuman ? "you" : "advisor"}
        {/* BD-15: submit-as-evidence toggle on Advisor messages */}
        {canSubmitEvidence && (
          <button
            type="button"
            onClick={onToggleEvidence}
            className={cn(
              "ml-auto flex items-center gap-1 font-mono text-[9px] tracking-wide uppercase transition-colors",
              evidenceOpen
                ? "text-primary"
                : "text-rail-muted hover:text-rail-foreground",
            )}
            title="Submit as evidence"
          >
            <ClipboardList className="size-2.5" /> evidence
          </button>
        )}
      </div>
      <p
        className={cn(
          "text-[13px] leading-relaxed whitespace-pre-wrap",
          isHuman ? "text-rail-foreground" : "text-rail-foreground/90",
        )}
      >
        {message.content}
      </p>

      {/* BD-15: criterion selector panel — shown when evidence toggle is open */}
      {canSubmitEvidence && evidenceOpen && criteria && (
        <div className="mt-2.5 rounded-xl border border-primary/30 bg-rail-card p-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="font-mono text-[9.5px] tracking-[0.1em] text-primary uppercase">
              submit as evidence
            </span>
            <button
              type="button"
              onClick={onToggleEvidence}
              className="text-rail-muted hover:text-rail-foreground"
            >
              <X className="size-3" />
            </button>
          </div>
          <select
            value={selectedCriterion}
            onChange={(e) => setSelectedCriterion(e.target.value)}
            className="mb-2.5 w-full rounded-md border border-rail-border bg-background px-2.5 py-1.5 font-mono text-[11px] text-foreground focus:outline-none"
          >
            <option value="">— pick a criterion —</option>
            {criteria.map((c) => (
              <option key={c.id} value={c.id}>
                {c.text.length > 80 ? `${c.text.slice(0, 80)}…` : c.text}
              </option>
            ))}
          </select>
          <Button
            size="sm"
            disabled={!selectedCriterion || !!evidenceBusy}
            onClick={() => {
              if (selectedCriterion && onSubmitEvidence) {
                onSubmitEvidence(selectedCriterion, message.content);
              }
            }}
            className="h-7 w-full px-2.5 text-xs"
          >
            {/* Show spinner whenever any submission is in-flight, not just this criterion. */}
            {evidenceBusy ? <Loader2 className="animate-spin" /> : <Check />}{" "}
            Submit finding
          </Button>
        </div>
      )}

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

      {/* BD-1 u3: the project rail's bridge to a new initiative. The rail only hands off — the
          creation form is the deliberate act, so this navigates-and-pre-fills, never creates. */}
      {!isHuman && synthesis && (
        <div className="mt-3 rounded-xl border border-primary/40 bg-rail-card p-3.5">
          <div className="mb-1.5 flex items-center gap-1.5 font-mono text-[9.5px] tracking-[0.1em] text-primary uppercase">
            <Sparkles className="size-3" /> proposed initiative
          </div>
          <p className="text-[13px] leading-snug text-rail-foreground">
            {synthesis}
          </p>
          <div className="mt-3 flex items-center justify-between gap-2">
            <span className="font-mono text-[10px] text-rail-muted">
              start from this?
            </span>
            <Button
              size="sm"
              onClick={onCreateInitiative}
              className="h-7 px-2.5 text-xs"
            >
              <FilePlus2 /> Create initiative from this
            </Button>
          </div>
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
        <Sparkles className="size-3" /> proposed{" "}
        {SECTION_NOTE[proposal.section]}
      </div>
      <p className="text-[13px] leading-snug text-rail-foreground">
        {proposal.text}
      </p>
      {proposal.section === "acceptance" && proposal.verify && (
        <p className="mt-1.5 font-mono text-[10px] text-rail-muted">
          verify: {proposal.verify.kind}
          {proposal.verify.detail ? ` — ${proposal.verify.detail}` : ""}
        </p>
      )}
      <div className="mt-3 flex items-center justify-between gap-2">
        <span className="font-mono text-[10px] text-rail-muted">
          add to the spec?
        </span>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={onDismiss}
            className="h-7 border border-rail-border px-2.5 text-xs text-rail-foreground hover:bg-black/5"
          >
            Dismiss
          </Button>
          <Button
            size="sm"
            disabled={busy}
            onClick={onAccept}
            className="h-7 px-2.5 text-xs"
          >
            {busy ? <Loader2 className="animate-spin" /> : <Check />} Accept
          </Button>
        </div>
      </div>
    </div>
  );
}

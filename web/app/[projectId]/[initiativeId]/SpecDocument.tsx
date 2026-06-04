"use client";

import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  CircleCheck,
  CircleDot,
  Compass,
  HelpCircle,
  Lock,
  Plus,
  Sparkles,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { AcceptanceCriterion, SpecItem } from "@/lib/types";
import { useSpec } from "./spec-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import AttentionSurface from "./AttentionSurface";
import SpecIntent from "./SpecIntent";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

type Section = "constraints" | "discretion" | "acceptance";

// 0012 a2: the guided review arc is Intent -> Constraints -> Acceptance criteria (-> Work Units,
// which render below this component). Intent leads, always open; these two governing sections
// disclose progressively and auto-advance. Discretion is NOT here — it lives under "Agent
// latitude" (a3), de-emphasised and outside the auto-expand chain.
const GOVERNING_BASE: { key: Section; title: string; researchTitle?: string; note: string; icon: LucideIcon }[] = [
  { key: "constraints", title: "Constraints", note: "locked — I won't cross these", icon: Lock },
  {
    key: "acceptance",
    title: "Acceptance criteria",
    researchTitle: "Success criteria",  // BD-15: research initiatives use this label
    note: "how the work gets judged",
    icon: CircleCheck,
  },
];

const PROV_LABEL: Record<string, string> = {
  human: "yours",
  ai_proposed: "AI proposed",
  ai_confirmed_by_human: "AI · you confirmed",
};

// status drives the trust cue: confirmed governs, proposed does not, retired is history.
function itemClasses(status: string): string {
  return cn(
    "group relative rounded-md border border-l-[3px] px-3.5 py-3 transition-colors",
    status === "confirmed" && "border-l-confirmed bg-confirmed/[0.06] hover:bg-confirmed/[0.09]",
    status === "proposed" &&
      "border-dashed [border-left-style:solid] border-l-proposed bg-card/60 hover:bg-card",
    status === "retired" && "opacity-55",
  );
}

const STATUS = {
  confirmed: { dot: "bg-confirmed", text: "text-confirmed-foreground" },
  proposed: { dot: "bg-proposed", text: "text-proposed-foreground" },
  retired: { dot: "bg-retired", text: "text-retired" },
} as const;

// BD-14: classification badge config
const CLASSIFICATION_CONFIG = {
  confident: {
    icon: Check,
    label: "confident",
    className: "text-confirmed-foreground bg-confirmed/10",
  },
  flagged: {
    icon: AlertTriangle,
    label: "flagged",
    className: "text-amber-600 bg-amber-50 dark:bg-amber-950/40",
  },
  uncertain: {
    icon: HelpCircle,
    label: "uncertain",
    className: "text-ink-soft bg-muted/60",
  },
} as const;

function ClassificationBadge({
  classification,
  reason,
}: {
  classification: "confident" | "flagged" | "uncertain";
  reason?: string | null;
}) {
  const cfg = CLASSIFICATION_CONFIG[classification];
  const Icon = cfg.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[9.5px] tracking-wide uppercase",
        cfg.className,
      )}
      title={reason ?? undefined}
    >
      <Icon className="size-2.5" />
      {cfg.label}
    </span>
  );
}

function Cue({
  status,
  provenance,
  classification,
  classificationReason,
}: {
  status: string;
  provenance: string;
  classification?: "confident" | "flagged" | "uncertain" | null;
  classificationReason?: string | null;
}) {
  const s = STATUS[status as keyof typeof STATUS] ?? STATUS.proposed;
  return (
    <div className="mb-2 flex flex-wrap items-center gap-2 font-mono text-[10px] tracking-widest uppercase">
      <span className="flex items-center gap-1.5">
        <span className={cn("size-1.5 rounded-full", s.dot)} />
        <span className={s.text}>{status}</span>
      </span>
      <span className="text-ink-faint">· {PROV_LABEL[provenance] ?? provenance}</span>
      {status === "proposed" && classification && (
        <ClassificationBadge classification={classification} reason={classificationReason} />
      )}
    </div>
  );
}

export default function SpecDocument() {
  // Shared spec + writes (0012 u3): the rail's guided review mutates the same spec, so accepting
  // or rejecting there updates this document and the progress bar live (a6).
  const { spec, busy, error, mutate } = useSpec();
  const isDraft = spec.state === "draft";
  const isResearch = spec.initiative_type === "research";
  // BD-15: adapt acceptance-criteria section title for research initiatives.
  const GOVERNING = GOVERNING_BASE.map((g) => ({
    ...g,
    title: isResearch && g.researchTitle ? g.researchTitle : g.title,
  }));
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [adding, setAdding] = useState<Section | null>(null);
  const [addText, setAddText] = useState("");
  const [verifyKind, setVerifyKind] = useState("behavior");
  const [verifyDetail, setVerifyDetail] = useState("");

  const iid = spec.initiative_id;

  // BD-14: batch approve confident items
  const confidentProposed = [...spec.constraints, ...spec.discretion, ...spec.acceptance].filter(
    (i) => i.status === "proposed" && i.advisor_classification === "confident",
  );
  const hasSynthesis =
    !!spec.shaping_review_synthesis &&
    [...spec.constraints, ...spec.discretion, ...spec.acceptance].some(
      (i) => i.status === "proposed",
    );

  async function batchApproveConfident() {
    await mutate(`/api/specs/${iid}/batch-approve-confident`, "POST", { version: spec.version });
  }

  // Progressive disclosure (a1/a2): governing sections collapse by default; the guided flow keeps
  // exactly one open — the first with items still awaiting review — and advances to the next when
  // that one is cleared. "View all" escapes the flow and opens everything; "Agent latitude" (a3)
  // is a separate, de-emphasised disclosure outside this chain.
  const pendingIn = (key: Section) =>
    (spec[key] as SpecItem[]).filter((i) => i.status === "proposed").length;
  const guidedActive = GOVERNING.find((s) => pendingIn(s.key) > 0)?.key ?? null;

  // u2 (a4): live review progress across every spec item — confirmed vs. total reviewable.
  // Rejected items are deleted (they leave the total); retired items are history (excluded). The
  // count is driven by `spec` state, so accepting or rejecting updates it immediately.
  const reviewItems = [...spec.constraints, ...spec.discretion, ...spec.acceptance].filter(
    (i) => i.status !== "retired",
  );
  const reviewTotal = reviewItems.length;
  const reviewConfirmed = reviewItems.filter((i) => i.status === "confirmed").length;
  const reviewPct = reviewTotal ? Math.round((reviewConfirmed / reviewTotal) * 100) : 0;
  const reviewDone = reviewTotal > 0 && reviewConfirmed === reviewTotal;

  // a9: while a fresh spec still has items awaiting review, the rail leads with the guided
  // walkthrough and the document stays calm — the "needs your attention" wall is the return-path
  // view, shown only once every item has been reviewed.
  const reviewMode = reviewConfirmed < reviewTotal;

  const [viewAll, setViewAll] = useState(false);
  const [openKey, setOpenKey] = useState<Section | null>(guidedActive);
  const [latitudeOpen, setLatitudeOpen] = useState(spec.state === "draft");

  // When a section is fully reviewed the guided step advances; follow it (a2) without clobbering a
  // manual toggle between advances — we only force-open on the *transition*.
  const prevActive = useRef(guidedActive);
  useEffect(() => {
    if (prevActive.current !== guidedActive) {
      setOpenKey(guidedActive);
      prevActive.current = guidedActive;
    }
  }, [guidedActive]);

  function toggleSection(key: Section) {
    if (viewAll) {
      setViewAll(false);
      setOpenKey(key);
    } else {
      setOpenKey((k) => (k === key ? null : key));
    }
  }

  const retireItem = (it: SpecItem) =>
    mutate(`/api/specs/${iid}/items/${it.id}/retire`, "POST", {});
  // a6: per-item accept (confirm -> governing) and reject (delete + log to rail, D1 -> c)
  const confirmItem = (it: SpecItem) =>
    mutate(`/api/specs/${iid}/items/${it.id}/confirm`, "POST", {});
  const rejectItem = (it: SpecItem) =>
    mutate(`/api/specs/${iid}/items/${it.id}/reject`, "POST", {});
  // D2 -> c: bulk confirm is only offered for discretion (agent latitude). Constraints and
  // acceptance criteria are confirmed one at a time — per-item confirmation is the trust model.
  const confirmSection = (section: Section) =>
    mutate(`/api/specs/${iid}/confirm-all`, "POST", { section });

  async function saveEdit(it: SpecItem) {
    if (!draft.trim()) return;
    if (await mutate(`/api/specs/${iid}/items/${it.id}`, "PATCH", { text: draft })) {
      setEditingId(null);
      setDraft("");
    }
  }

  async function submitAdd(section: Section) {
    if (!addText.trim()) return;
    const body: Record<string, unknown> = { section, text: addText };
    if (section === "acceptance")
      body.verify = { kind: verifyKind, detail: verifyDetail.trim() || addText };
    if (await mutate(`/api/specs/${iid}/items`, "POST", body)) {
      setAdding(null);
      setAddText("");
      setVerifyDetail("");
    }
  }

  function renderItem(it: SpecItem, isAcceptance: boolean) {
    const editing = editingId === it.id;
    return (
      <li key={it.id} className={cn("list-none", itemClasses(it.status))}>
        <Cue
          status={it.status}
          provenance={it.provenance}
          classification={it.advisor_classification}
          classificationReason={it.advisor_classification_reason}
        />

        {editing ? (
          <div className="space-y-2">
            <Textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={2}
              className="font-mono text-[13px]"
            />
            <div className="flex gap-2">
              <Button size="sm" disabled={busy} onClick={() => saveEdit(it)}>
                <Check /> Save
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={() => {
                  setEditingId(null);
                  setDraft("");
                }}
              >
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <>
            <p className="font-mono text-[13px] leading-relaxed tracking-tight text-foreground">
              {it.text}
              {isAcceptance && (
                <span className="text-ink-faint">
                  {" "}
                  [{(it as AcceptanceCriterion).verify?.kind}]
                </span>
              )}
            </p>
            {it.status === "proposed" && isDraft && (
              // a6: Accept / Reject are prominent on every proposed item — not buried in a menu.
              // Confirming makes it governing; rejecting removes it (and logs to the rail).
              <div className="mt-2.5 flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  disabled={busy}
                  onClick={() => confirmItem(it)}
                  className="h-7 bg-confirmed px-2.5 text-white shadow-sm hover:bg-confirmed/90"
                >
                  <Check /> Accept
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy}
                  onClick={() => rejectItem(it)}
                  className="h-7 px-2.5 text-proposed-foreground hover:bg-proposed/10"
                >
                  <X /> Reject
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 px-2 text-xs text-ink-faint"
                  disabled={busy}
                  onClick={() => {
                    setEditingId(it.id);
                    setDraft(it.text);
                  }}
                >
                  Edit
                </Button>
              </div>
            )}
            {it.status === "confirmed" && isDraft && (
              <div className="mt-2.5 flex gap-1 opacity-70 transition-opacity group-hover:opacity-100">
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 px-2 text-xs"
                  disabled={busy}
                  onClick={() => {
                    setEditingId(it.id);
                    setDraft(it.text);
                  }}
                >
                  Edit
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 px-2 text-xs"
                  disabled={busy}
                  onClick={() => retireItem(it)}
                >
                  Retire
                </Button>
              </div>
            )}
          </>
        )}
      </li>
    );
  }

  function renderAdd(section: Section) {
    if (adding !== section)
      return isDraft ? (
        <Button
          variant="ghost"
          size="sm"
          className="mt-2 h-7 px-2 font-mono text-[11px] tracking-wide text-ink-faint hover:text-accent-deep"
          onClick={() => {
            setAdding(section);
            setAddText("");
          }}
        >
          <Plus /> add {section === "acceptance" ? "criterion" : "item"}
        </Button>
      ) : null;
    return (
      <div className="mt-2 rounded-md border border-l-[3px] border-l-primary border-dashed [border-left-style:solid] bg-card/60 px-3.5 py-3">
        <Textarea
          autoFocus
          value={addText}
          onChange={(e) => setAddText(e.target.value)}
          rows={2}
          placeholder={`New ${section} item — saved as yours, confirmed`}
          className="font-mono text-[13px]"
        />
        {section === "acceptance" && (
          <div className="mt-2 flex items-center gap-2">
            <Select value={verifyKind} onValueChange={setVerifyKind}>
              <SelectTrigger size="sm" className="w-40 font-mono text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="font-mono text-xs">
                <SelectItem value="test">test</SelectItem>
                <SelectItem value="behavior">behavior</SelectItem>
                <SelectItem value="metric">metric</SelectItem>
                <SelectItem value="human_judgment">human_judgment</SelectItem>
              </SelectContent>
            </Select>
            <Input
              value={verifyDetail}
              onChange={(e) => setVerifyDetail(e.target.value)}
              placeholder="how it's verified"
              className="flex-1"
            />
          </div>
        )}
        <div className="mt-2.5 flex gap-2">
          <Button size="sm" disabled={busy} onClick={() => submitAdd(section)}>
            Add
          </Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => setAdding(null)}>
            Cancel
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* u2 (a4): live review progress at the top of the spec — confirmed vs. total, updating
          as items are accepted or rejected; reads "done" when nothing is left to review. */}
      {reviewTotal > 0 && (
        <div className="mb-5">
          <div className="flex items-baseline justify-between gap-3">
            <span
              className={cn(
                "flex items-center gap-1.5 font-mono text-[11px] tracking-wide",
                reviewDone ? "text-confirmed-foreground" : "text-ink-soft",
              )}
            >
              {reviewDone && <Check className="size-3.5" />}
              {reviewDone ? "Review complete" : `${reviewConfirmed} of ${reviewTotal} confirmed`}
            </span>
            <span className="font-mono text-[10px] tabular-nums text-ink-faint">{reviewPct}%</span>
          </div>
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-border/70">
            <div
              className="h-full rounded-full bg-confirmed transition-all duration-500 ease-out"
              style={{ width: `${reviewPct}%` }}
            />
          </div>
        </div>
      )}

      {/* BD-14: shaping review synthesis — Advisor's classification summary + batch approve */}
      {hasSynthesis && (
        <div className="mb-5 rounded-md border border-border bg-muted/40 px-4 py-3.5">
          <div className="mb-2 flex items-center gap-1.5 font-mono text-[10px] font-semibold tracking-widest text-ink-soft uppercase">
            <Sparkles className="size-3" />
            Advisor review
          </div>
          <pre className="whitespace-pre-wrap font-mono text-[12px] leading-relaxed text-foreground">
            {spec.shaping_review_synthesis}
          </pre>
          {confidentProposed.length > 0 && (
            <div className="mt-3 flex items-center gap-3">
              <Button
                size="sm"
                disabled={busy}
                onClick={batchApproveConfident}
                className="h-7 bg-confirmed px-3 text-[11px] text-white shadow-sm hover:bg-confirmed/90"
              >
                <Check /> Approve {confidentProposed.length} confident item{confidentProposed.length !== 1 ? "s" : ""}
              </Button>
              <span className="font-mono text-[10px] text-ink-faint">
                flagged and uncertain items stay open
              </span>
            </div>
          )}
        </div>
      )}

      {/* the return-path surface (0011 C4/a5): what needs you, once you're driving the document.
          Hidden while the rail leads a fresh review (a9 — no wall of undifferentiated content). */}
      {!reviewMode && (
        <div className="mb-6">
          <AttentionSurface
            spec={spec}
            initiativeId={iid}
            onConfirmItem={confirmItem}
            onRejectItem={rejectItem}
            busy={busy}
          />
        </div>
      )}

      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <p className="font-mono text-[11px] tracking-wide text-ink-faint">
          the living spec · v{spec.version} — only confirmed items bind executors
        </p>
        <button
          type="button"
          onClick={() => setViewAll((v) => !v)}
          className="font-mono text-[11px] tracking-wide text-ink-faint underline-offset-4 transition-colors hover:text-accent-deep hover:underline"
        >
          {viewAll ? "Guided view" : "View all"}
        </button>
      </div>

      {error && (
        <p className="mt-3 rounded-md border border-proposed/30 bg-proposed/10 px-3 py-1.5 font-mono text-xs text-proposed-foreground">
          {error}
        </p>
      )}

      <section className="mt-7 animate-rise [animation-delay:60ms]">
        <h2 className="flex items-center gap-2 font-mono text-[11.5px] font-semibold tracking-[0.13em] text-accent-deep uppercase">
          <CircleDot className="size-3.5" /> Intent
        </h2>
        <SpecIntent />
      </section>

      {/* a1/a2: governing sections collapse by default, show a review count, and the guided flow
          keeps the current one open — Constraints, then Acceptance criteria. */}
      {GOVERNING.map(({ key, title, note, icon: Icon }) => {
        const items = spec[key] as SpecItem[];
        const pending = pendingIn(key);
        const open = viewAll || openKey === key;
        return (
          <section key={key} className="mt-6 animate-rise">
            <button
              type="button"
              onClick={() => toggleSection(key)}
              className="flex w-full items-center justify-between gap-3 rounded-md py-1.5 text-left transition-colors hover:text-accent-deep"
            >
              <h2 className="flex items-center gap-2 font-mono text-[11.5px] font-semibold tracking-[0.13em] text-ink-soft uppercase">
                {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
                <Icon className="size-3.5" /> {title}
                <span className="font-normal tracking-normal text-ink-faint normal-case">
                  · {note}
                </span>
              </h2>
              {pending > 0 ? (
                <span className="rounded-full bg-proposed/15 px-2 py-0.5 font-mono text-[10px] font-semibold tracking-wide text-proposed-foreground tabular-nums">
                  {pending} to review
                </span>
              ) : (
                <span className="flex items-center gap-1 font-mono text-[10px] tracking-wide text-confirmed-foreground">
                  <Check className="size-3" /> reviewed
                </span>
              )}
            </button>
            {open && (
              <div className="mt-2">
                <ul className="space-y-2">
                  {items.map((it) => renderItem(it, key === "acceptance"))}
                </ul>
                {renderAdd(key)}
              </div>
            )}
          </section>
        );
      })}

      {/* a3: discretion is the executor's latitude, not a governing decision — collapsed under
          "Agent latitude," de-emphasised, and outside the guided auto-expand chain. D2 -> c:
          bulk "confirm all" is offered here (and only here). */}
      {(() => {
        const items = spec.discretion;
        const pending = pendingIn("discretion");
        const open = viewAll || latitudeOpen;
        return (
          <section className="mt-9 rounded-lg border border-border/60 bg-muted/30 px-3.5 py-2.5">
            <button
              type="button"
              onClick={() => setLatitudeOpen((o) => !o)}
              className="flex w-full items-center justify-between gap-3 text-left transition-colors hover:text-accent-deep"
            >
              <h2 className="flex items-center gap-2 font-mono text-[10.5px] font-medium tracking-[0.13em] text-ink-faint uppercase">
                {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
                <Compass className="size-3.5" /> Agent latitude
                <span className="font-normal tracking-normal normal-case">
                  · discretion — the executor's calls, not yours
                </span>
              </h2>
              {pending > 0 && (
                <span className="rounded-full bg-ink-faint/15 px-2 py-0.5 font-mono text-[10px] font-medium tracking-wide text-ink-faint tabular-nums">
                  {pending}
                </span>
              )}
            </button>
            {open && (
              <div className="mt-3">
                {pending > 0 && isDraft && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() => confirmSection("discretion")}
                    className="mb-2.5 h-7 px-2.5 font-mono text-[11px] tracking-wide text-ink-soft"
                  >
                    <Check /> Confirm all latitude ({pending})
                  </Button>
                )}
                <ul className="space-y-2">
                  {items.map((it) => renderItem(it, false))}
                </ul>
                {renderAdd("discretion")}
              </div>
            )}
          </section>
        );
      })()}
    </div>
  );
}

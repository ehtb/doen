"use client";

import { useState } from "react";
import { Check, CircleCheck, CircleDot, Compass, Loader2, Lock, Plus, Sparkles, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { AcceptanceCriterion, Spec, SpecItem } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import AttentionSurface from "./AttentionSurface";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

type Section = "constraints" | "discretion" | "acceptance";

const SECTIONS: {
  key: Section;
  title: string;
  note: string;
  icon: LucideIcon;
  delay: string;
}[] = [
  { key: "constraints", title: "Constraints", note: "locked — I won't cross these", icon: Lock, delay: "[animation-delay:140ms]" },
  { key: "discretion", title: "Discretion", note: "my latitude — decide as I build", icon: Compass, delay: "[animation-delay:200ms]" },
  { key: "acceptance", title: "Acceptance criteria", note: "how the work gets judged", icon: CircleCheck, delay: "[animation-delay:260ms]" },
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

function Cue({ status, provenance }: { status: string; provenance: string }) {
  const s = STATUS[status as keyof typeof STATUS] ?? STATUS.proposed;
  return (
    <div className="mb-2 flex items-center gap-2 font-mono text-[10px] tracking-widest uppercase">
      <span className="flex items-center gap-1.5">
        <span className={cn("size-1.5 rounded-full", s.dot)} />
        <span className={s.text}>{status}</span>
      </span>
      <span className="text-ink-faint">· {PROV_LABEL[provenance] ?? provenance}</span>
    </div>
  );
}

export default function SpecDocument({ initialSpec }: { initialSpec: Spec }) {
  const [spec, setSpec] = useState<Spec>(initialSpec);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [adding, setAdding] = useState<Section | null>(null);
  const [addText, setAddText] = useState("");
  const [verifyKind, setVerifyKind] = useState("behavior");
  const [verifyDetail, setVerifyDetail] = useState("");
  const [shapeOpen, setShapeOpen] = useState(false);
  const [shapeDesc, setShapeDesc] = useState("");
  const [shapeBusy, setShapeBusy] = useState(false);

  const iid = spec.initiative_id;
  const canShape = spec.state === "draft"; // shaping happens while the spec is still a draft (0011)

  async function shapeWithAI() {
    if (!shapeDesc.trim() || shapeBusy) return;
    setShapeBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/specs/${iid}/shape`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ description: shapeDesc }),
      });
      if (!res.ok) {
        let msg = `shaping failed (${res.status})`;
        try {
          const j = await res.json();
          if (j?.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
        } catch {
          /* keep the status-code message */
        }
        setError(msg);
        return;
      }
      setSpec(await res.json()); // proposed items appear in the sections below, ready to confirm
      setShapeOpen(false);
      setShapeDesc("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setShapeBusy(false);
    }
  }

  async function mutate(path: string, method: string, body: object): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(path, {
        method,
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ ...body, version: spec.version }),
      });
      if (res.status === 409) {
        setError("The spec changed elsewhere — reloading to catch up…");
        setTimeout(() => location.reload(), 900);
        return false;
      }
      if (!res.ok) {
        setError(`request failed (${res.status})`);
        return false;
      }
      setSpec(await res.json());
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  const retireItem = (it: SpecItem) =>
    mutate(`/api/specs/${iid}/items/${it.id}/retire`, "POST", {});
  // a6: per-item accept (confirm -> governing) and reject (delete + log to rail, D1 -> c)
  const confirmItem = (it: SpecItem) =>
    mutate(`/api/specs/${iid}/items/${it.id}/confirm`, "POST", {});
  const rejectItem = (it: SpecItem) =>
    mutate(`/api/specs/${iid}/items/${it.id}/reject`, "POST", {});
  const confirmAll = () => mutate(`/api/specs/${iid}/confirm-all`, "POST", {});
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

  const proposedCount = SECTIONS.reduce(
    (n, { key }) => n + (spec[key] as SpecItem[]).filter((i) => i.status === "proposed").length,
    0,
  );

  function renderItem(it: SpecItem, isAcceptance: boolean) {
    const editing = editingId === it.id;
    return (
      <li key={it.id} className={cn("list-none", itemClasses(it.status))}>
        <Cue status={it.status} provenance={it.provenance} />

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
            {it.status === "proposed" && (
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
            {it.status === "confirmed" && (
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
      return (
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
      );
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
      {/* lead with what needs the human (0011 C4/a5); the full spec below is the reference */}
      <div className="mb-6">
        <AttentionSurface
          spec={spec}
          initiativeId={iid}
          onConfirmItem={confirmItem}
          onRejectItem={rejectItem}
          busy={busy}
        />
      </div>

      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <p className="font-mono text-[11px] tracking-wide text-ink-faint">
          the living spec · v{spec.version} — only confirmed items bind executors
        </p>
        <Button
          disabled={busy || proposedCount === 0}
          onClick={confirmAll}
          className="bg-confirmed text-white shadow-sm hover:bg-confirmed/90"
        >
          {proposedCount === 0 ? (
            "All confirmed"
          ) : (
            <>
              <Check /> Confirm all proposed ({proposedCount})
            </>
          )}
        </Button>
      </div>

      {canShape && (
        <div className="mt-4 rounded-lg border border-primary/30 bg-primary/[0.04] p-4">
          {!shapeOpen ? (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="font-mono text-[11.5px] tracking-wide text-ink-soft">
                <Sparkles className="mr-1.5 inline size-3.5 text-primary" />
                Describe the idea — the AI drafts a full spec, informed by past initiatives, for you
                to correct.
              </p>
              <Button
                size="sm"
                disabled={busy}
                onClick={() => {
                  setShapeOpen(true);
                  setShapeDesc("");
                }}
              >
                <Sparkles /> Shape with AI
              </Button>
            </div>
          ) : (
            <div>
              <Textarea
                autoFocus
                value={shapeDesc}
                onChange={(e) => setShapeDesc(e.target.value)}
                rows={4}
                disabled={shapeBusy}
                placeholder="Describe the initiative in a few sentences — the problem, who it's for, what success looks like."
                className="text-[13px]"
              />
              <div className="mt-2.5 flex items-center gap-2">
                <Button
                  size="sm"
                  disabled={shapeBusy || !shapeDesc.trim()}
                  onClick={shapeWithAI}
                >
                  {shapeBusy ? (
                    <>
                      <Loader2 className="animate-spin" /> Drafting…
                    </>
                  ) : (
                    <>
                      <Sparkles /> Generate spec
                    </>
                  )}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={shapeBusy}
                  onClick={() => setShapeOpen(false)}
                >
                  Cancel
                </Button>
                <span className="font-mono text-[10.5px] text-ink-faint">
                  arrives as proposed items — confirm, edit, or reject each below
                </span>
              </div>
            </div>
          )}
        </div>
      )}

      {error && (
        <p className="mt-3 rounded-md border border-proposed/30 bg-proposed/10 px-3 py-1.5 font-mono text-xs text-proposed-foreground">
          {error}
        </p>
      )}

      <section className="mt-7 animate-rise [animation-delay:60ms]">
        <h2 className="flex items-center gap-2 font-mono text-[11.5px] font-semibold tracking-[0.13em] text-accent-deep uppercase">
          <CircleDot className="size-3.5" /> Intent
        </h2>
        <p className="mt-2.5 max-w-[54ch] font-serif text-[19px] leading-relaxed whitespace-pre-wrap">
          {spec.intent || "—"}
        </p>
      </section>

      {SECTIONS.map(({ key, title, note, icon: Icon, delay }) => {
        const items = spec[key] as SpecItem[];
        const sectionProposed = items.filter((i) => i.status === "proposed").length;
        return (
          <section key={key} className={cn("mt-8 animate-rise", delay)}>
            <div className="flex items-end justify-between gap-3">
              <h2 className="flex items-center gap-2 font-mono text-[11.5px] font-semibold tracking-[0.13em] text-ink-soft uppercase">
                <Icon className="size-3.5" /> {title}
                <span className="font-normal tracking-normal text-ink-faint normal-case">
                  · {note}
                </span>
              </h2>
              {sectionProposed > 0 && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy}
                  onClick={() => confirmSection(key)}
                  className="h-7 border-confirmed/50 px-2.5 font-mono text-[11px] tracking-wide text-confirmed-foreground hover:bg-confirmed/10"
                >
                  confirm all ({sectionProposed})
                </Button>
              )}
            </div>
            <ul className="mt-3 space-y-2">
              {items.map((it) => renderItem(it, key === "acceptance"))}
            </ul>
            {renderAdd(key)}
          </section>
        );
      })}
    </div>
  );
}

"""Learn service: assemble the outcome review, capture memory, and extract heuristics.

The review gathers intent and the resolved decisions (the calls + why) so the human can
reflect on what happened. Submitting writes one append-only memory row embedded for the
cross-initiative flywheel. BD-17: after the outcome is captured, the Advisor proposes
heuristics for human confirmation before any heuristic enters long-term memory.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.exceptions import NotFoundError, ValidationError
from app.models import Heuristic
from app.providers.llm import StructuredLLM, get_advisor_llm
from app.schemas import ConfirmHeuristics, HeuristicDraftResult, HeuristicProposal, LearnReview, LearningItem, OutcomeDraft, RationaleClaim
from app.store import SpecStore

_PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
LEARN_DRAFT_SYSTEM_PROMPT = (_PROMPTS / "learn-draft.txt").read_text().strip()
LEARNING_EVAL_SYSTEM_PROMPT = (_PROMPTS / "learn-evaluation.txt").read_text().strip()

LEARN_DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "What was intended vs. what happened."},
        "conclusion": {
            "type": "string",
            "description": "Research initiatives only: a direct, synthesized answer to the research question. One to three paragraphs. Omit for engineering initiatives.",
        },
        "learnings": {
            "type": "array",
            "description": "Durable, transferable lessons as bullet-point items.",
            "items": {"type": "string"},
        },
        "rationale_claims": {
            "type": "array",
            "description": "Cause-effect claims each traceable to a specific decision or criterion id in the record.",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string", "description": "One-sentence cause-effect statement."},
                    "source_id": {"type": "string", "description": "The exact id (dec_… or item_…) from the record."},
                    "source_type": {"type": "string", "enum": ["decision", "criterion"]},
                },
                "required": ["claim", "source_id", "source_type"],
            },
        },
    },
    "required": ["summary", "learnings"],
}


async def learn_review(store: SpecStore, initiative_id: str) -> LearnReview:
    init = await store.get_initiative(initiative_id)
    if init is None:
        raise NotFoundError(f"no initiative {initiative_id}")
    spec = await store.get_spec(initiative_id)
    return LearnReview(
        initiative=init,
        intent=spec.intent if spec else "",
        decisions=await store.list_decisions(initiative_id, status="resolved"),
        memory=await store.list_memory(initiative_id),
    )


def _build_history(review: LearnReview, spec=None) -> str:
    """Build the history context for the Advisor, including record IDs so the LLM can
    produce traceable rationale claims (BD-13)."""
    parts = [f"# INTENT\n{review.intent or '(none recorded)'}"]
    if review.decisions:
        parts.append(
            "# DECISIONS MADE (id · question · outcome):\n"
            + "\n".join(
                f"- id={d.id}  question: {d.question}\n"
                f"  chose: {d.chosen or '(unresolved)'}"
                + (f" — {d.rationale}" if d.rationale else "")
                for d in review.decisions
            )
        )
    if spec is not None and spec.acceptance:
        confirmed = [c for c in spec.acceptance if c.status == "confirmed"]
        if confirmed:
            parts.append(
                "# ACCEPTANCE CRITERIA (id · text · verification outcome):\n"
                + "\n".join(
                    f"- id={c.id}  {c.text}\n"
                    f"  status={c.verification_status}"
                    + (f" | feedback: {c.feedback}" if c.feedback else "")
                    for c in confirmed
                )
            )
    return "\n\n".join(parts)


def _parse_rationale_claims(raw_claims: list[Any], valid_ids: set[str]) -> list[RationaleClaim]:
    """Parse and validate rationale claims from LLM output — only keep claims whose
    source_id matches an actual record entry (BD-13 constraint: no fabricated IDs)."""
    result = []
    for item in raw_claims or []:
        try:
            c = RationaleClaim(
                claim=str(item.get("claim", "")).strip(),
                source_id=str(item.get("source_id", "")).strip(),
                source_type=item.get("source_type", "decision"),
            )
            if not c.claim or not c.source_id:
                continue
            if c.source_id not in valid_ids:
                continue  # reject fabricated IDs — constraint item_ed83f4886d2c
            result.append(c)
        except Exception:
            continue
    return result


LEARNING_EVAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "evaluations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {
                        "type": "integer",
                        "description": "0-based index of the learning in the input list.",
                    },
                    "auto_approved": {
                        "type": "boolean",
                        "description": (
                            "True ONLY when HIGH CONFIDENCE the learning maps directly to a "
                            "discretion item or criterion. False for anything ambiguous."
                        ),
                    },
                    "matched_item_id": {
                        "type": ["string", "null"],
                        "description": "The id of the matching item. Null when auto_approved is false.",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "One sentence explaining your confidence assessment.",
                    },
                },
                "required": ["index", "auto_approved", "reasoning"],
            },
        }
    },
    "required": ["evaluations"],
}


def _render_spec_items_for_eval(
    discretion_items: list[Any],
    acceptance_criteria: list[Any],
) -> str:
    parts: list[str] = []
    confirmed_disc = [i for i in discretion_items if i.status == "confirmed"]
    confirmed_acc = [i for i in acceptance_criteria if i.status == "confirmed"]
    if confirmed_disc:
        parts.append("Confirmed DISCRETION items (id → text):")
        parts += [f"  {i.id}: {i.text}" for i in confirmed_disc]
    if confirmed_acc:
        parts.append("\nConfirmed ACCEPTANCE CRITERIA (id → text · verification outcome):")
        parts += [
            f"  {c.id}: {c.text}"
            + (f" [verification: {c.verification_status}]" if c.verification_status else "")
            for c in confirmed_acc
        ]
    if not parts:
        return "No confirmed spec items available."
    return "\n".join(parts)


async def evaluate_learnings(
    learnings: list[str],
    discretion_items: list[Any],
    acceptance_criteria: list[Any],
    *,
    llm: StructuredLLM | None = None,
) -> list[LearningItem]:
    """BD-25: classify each learning as auto_approved or needs_review, reusing the
    Discretion Auditor's high-confidence gate pattern (constraint item_d48cf8171aac).
    On any LLMError, all learnings fall back to needs_review — no silent loss.
    With no spec items to match against, all learnings need human review."""
    from app.providers.llm import LLMError

    if not learnings:
        return []

    confirmed_disc = [i for i in discretion_items if i.status == "confirmed"]
    confirmed_acc = [i for i in acceptance_criteria if i.status == "confirmed"]
    if not confirmed_disc and not confirmed_acc:
        return [
            LearningItem(
                text=t,
                auto_approved=False,
                reasoning="No confirmed spec items — cannot gate auto-approval.",
            )
            for t in learnings
        ]

    llm = llm or get_advisor_llm()
    user_msg = "\n".join(f"{i}: {t}" for i, t in enumerate(learnings))
    user_msg += "\n\n" + _render_spec_items_for_eval(discretion_items, acceptance_criteria)

    try:
        raw = await llm.complete_structured(
            system=LEARNING_EVAL_SYSTEM_PROMPT,
            user=user_msg,
            schema=LEARNING_EVAL_SCHEMA,
            schema_name="learning_evaluation",
        )
    except LLMError:
        return [
            LearningItem(
                text=t,
                auto_approved=False,
                reasoning="Evaluator LLM unavailable — surfaced to human as a safe fallback.",
            )
            for t in learnings
        ]

    evals: dict[int, dict] = {}
    for ev in (raw.get("evaluations") or []):
        idx = ev.get("index")
        if isinstance(idx, int) and 0 <= idx < len(learnings):
            evals[idx] = ev

    valid_item_ids = {i.id for i in confirmed_disc} | {c.id for c in confirmed_acc}
    result: list[LearningItem] = []
    for i, text in enumerate(learnings):
        ev = evals.get(i)
        if ev is None:
            result.append(LearningItem(text=text, auto_approved=False, reasoning="No evaluation returned."))
            continue
        within = bool(ev.get("auto_approved", False))
        item_id = ev.get("matched_item_id") if within else None
        # Reject hallucinated IDs — same guard as discretion_auditor.
        if item_id and item_id not in valid_item_ids:
            within = False
            item_id = None
        result.append(LearningItem(
            text=text,
            auto_approved=within,
            matched_item_id=item_id,
            reasoning=str(ev.get("reasoning", "")),
        ))
    return result


async def draft_outcome(
    store: SpecStore, initiative_id: str, *, llm: StructuredLLM | None = None
) -> OutcomeDraft:
    """BD-13 enriched / BD-25 structured draft: outcome + bullet-point learnings evaluated
    for auto-approval + rationale claims. Nothing is written to memory here."""
    review = await learn_review(store, initiative_id)  # raises NotFoundError if absent
    spec = await store.get_spec(initiative_id)
    llm = llm or get_advisor_llm()
    raw = await llm.complete_structured(
        system=LEARN_DRAFT_SYSTEM_PROMPT,
        user=_build_history(review, spec),
        schema=LEARN_DRAFT_SCHEMA,
        schema_name="outcome",
    )

    # Parse learnings — LLM returns an array; guard against old string format.
    raw_learnings = raw.get("learnings") or []
    if isinstance(raw_learnings, str):
        # Graceful fallback if model returns a string: split on newlines.
        raw_learnings = [l.strip().lstrip("- ").strip() for l in raw_learnings.split("\n") if l.strip()]
    learning_texts = [str(l).strip().lstrip("- ").strip() for l in raw_learnings if str(l).strip()]

    # BD-25: evaluate each learning against discretion + criteria using the Auditor pattern.
    discretion_items = list(spec.discretion) if spec else []
    acceptance_criteria = list(spec.acceptance) if spec else []
    evaluated = await evaluate_learnings(
        learning_texts, discretion_items, acceptance_criteria, llm=llm
    )
    auto_approved = [item for item in evaluated if item.auto_approved]
    needs_review = [item for item in evaluated if not item.auto_approved]

    # Build the set of valid record IDs the LLM is allowed to cite.
    decision_ids = {d.id for d in review.decisions}
    criterion_ids = {c.id for c in (spec.acceptance if spec else [])}
    valid_ids = decision_ids | criterion_ids
    claims = _parse_rationale_claims(raw.get("rationale_claims") or [], valid_ids)

    raw_conclusion = raw.get("conclusion") or None
    is_research = review.initiative.initiative_type == "research"

    return OutcomeDraft(
        summary=str(raw.get("summary", "")).strip(),
        conclusion=str(raw_conclusion).strip() if raw_conclusion and is_research else None,
        auto_approved_learnings=auto_approved,
        needs_review_learnings=needs_review,
        rationale_claims=claims,
    )


async def submit_learn(
    store: SpecStore,
    initiative_id: str,
    *,
    summary: str,
    conclusion: str | None = None,
    auto_approved_learnings: list[str] | None = None,
    human_approved_learnings: list[str] | None = None,
    learnings: str | None = None,  # legacy compat
    outcome: dict | None = None,
    rationale_claims: list[RationaleClaim] | None = None,
) -> LearnReview:
    init = await store.get_initiative(initiative_id)
    if init is None:
        raise NotFoundError(f"no initiative {initiative_id}")
    if not summary.strip():
        raise ValidationError("capturing the outcome needs a human-written summary")

    # BD-25: build structured learning approvals and format bullet-point learnings string.
    all_approved_texts: list[str] = []
    learning_approvals: list[dict] = []

    auto_list = auto_approved_learnings or []
    human_list = human_approved_learnings or []

    for text in auto_list:
        if text.strip():
            all_approved_texts.append(f"- {text.strip().lstrip('- ')}")
            learning_approvals.append({"text": text.strip(), "approved_by": "auto"})
    for text in human_list:
        if text.strip():
            all_approved_texts.append(f"- {text.strip().lstrip('- ')}")
            learning_approvals.append({"text": text.strip(), "approved_by": "human"})

    # Legacy: if no structured learnings were provided, fall back to the plain string.
    structured_learnings_str: str | None = "\n".join(all_approved_texts) if all_approved_texts else learnings

    # BD-13: merge human-confirmed rationale claims into the outcome dict.
    if rationale_claims:
        outcome = {**(outcome or {}), "rationale_claims": [c.model_dump() for c in rationale_claims]}
    # BD-25: store approval metadata in outcome so the UI can render visual distinction.
    if learning_approvals:
        outcome = {**(outcome or {}), "learning_approvals": learning_approvals}
    # Research conclusion: store in outcome so context hits can surface the direct answer.
    if conclusion and conclusion.strip():
        outcome = {**(outcome or {}), "conclusion": conclusion.strip()}

    # BD-15: carry the initiative type into memory so context hits expose the source type.
    await store.create_memory(
        initiative_id, summary.strip(), structured_learnings_str, outcome,
        initiative_type=init.initiative_type,
    )
    return await learn_review(store, initiative_id)


# --- BD-17: heuristic extraction from the Learn stage --------------------------------

HEURISTIC_DRAFT_SYSTEM_PROMPT = (_PROMPTS / "heuristic-draft.txt").read_text().strip()

HEURISTIC_DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "heuristics": {
            "type": "array",
            "description": "Extracted heuristics, 0–5.",
            "items": {
                "type": "object",
                "properties": {
                    "rule": {"type": "string", "description": "Actionable transferable rule."},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "1–3 short retrieval tags.",
                    },
                    "supersedes": {
                        "type": "string",
                        "description": "Rule text of a prior heuristic this one replaces. Null if new.",
                        "nullable": True,
                    },
                },
                "required": ["rule", "tags"],
            },
        }
    },
    "required": ["heuristics"],
}


async def draft_heuristics(
    store: SpecStore, initiative_id: str, *, llm: StructuredLLM | None = None
) -> HeuristicDraftResult:
    """BD-17: Advisor proposes heuristics from the initiative's history. The human reviews
    and confirms via confirm_heuristics — nothing is written to memory here (constraint
    item_a743fde4bc87)."""
    review = await learn_review(store, initiative_id)
    spec = await store.get_spec(initiative_id)
    llm = llm or get_advisor_llm()
    raw = await llm.complete_structured(
        system=HEURISTIC_DRAFT_SYSTEM_PROMPT,
        user=_build_history(review, spec),
        schema=HEURISTIC_DRAFT_SCHEMA,
        schema_name="heuristics",
    )

    # Resolve supersedes to heuristic IDs from the project's existing heuristics.
    init = review.initiative
    existing = await store.list_heuristics(project_id=init.project_id, active_only=False)
    rule_to_id: dict[str, str] = {h.rule: h.id for h in existing}

    proposals: list[HeuristicProposal] = []
    for item in raw.get("heuristics") or []:
        rule = str(item.get("rule", "")).strip()
        if not rule:
            continue
        tags = [str(t).strip().lower() for t in (item.get("tags") or []) if str(t).strip()][:3]
        # Try to resolve "supersedes" text to an existing heuristic ID.
        supersedes_text: str | None = item.get("supersedes")
        replaces: str | None = None
        if supersedes_text:
            # Exact match first; fall back to substring match.
            replaces = rule_to_id.get(supersedes_text.strip())
            if replaces is None:
                for h in existing:
                    if supersedes_text.strip().lower() in h.rule.lower():
                        replaces = h.id
                        break
        proposals.append(HeuristicProposal(rule=rule, tags=tags, replaces=replaces))

    return HeuristicDraftResult(initiative_id=initiative_id, proposals=proposals)


async def confirm_heuristics(
    store: SpecStore,
    initiative_id: str,
    body: ConfirmHeuristics,
) -> list[Heuristic]:
    """BD-17: write human-confirmed heuristics to long-term memory (constraint item_a743fde4bc87).
    Each proposal with `replaces` set marks the old heuristic as superseded by this initiative
    (constraint item_580f56224a2b). If `agents_md_path` is provided, appends to agents.md
    using the append/supersede pattern (constraint item_857693d05f70)."""
    init = await store.get_initiative(initiative_id)
    if init is None:
        raise NotFoundError(f"no initiative {initiative_id}")
    if not body.proposals:
        return []

    written: list[Heuristic] = []
    superseded_pairs: list[tuple[Heuristic, Heuristic]] = []  # (old, new) for agents.md

    for proposal in body.proposals:
        if not proposal.rule.strip():
            continue
        # Resolve the old heuristic before creating the new one (if it supersedes something).
        old_heur = await store.get_heuristic(proposal.replaces) if proposal.replaces else None
        heur = await store.create_heuristic(
            initiative_id,
            proposal.rule.strip(),
            project_id=init.project_id,
            tags=proposal.tags,
            replaces=proposal.replaces,
        )
        written.append(heur)
        if old_heur:
            superseded_pairs.append((old_heur, heur))

    # BD-17: append to agents.md using append/supersede if path provided.
    if body.agents_md_path and written:
        _write_heuristics_to_agents_md(
            body.agents_md_path, written, superseded_pairs, initiative_id
        )

    return written


# --- BD-17: agents.md append/supersede (constraint item_857693d05f70) ----------------

_HEURISTICS_SECTION_HEADER = "## Heuristics"
_HEURISTICS_SECTION_MARKER = "<!-- doen-heuristics -->"


def apply_heuristics_to_agents_md(
    content: str,
    new_heuristics: list[Heuristic],
    superseded_pairs: list[tuple[Heuristic, Heuristic]],
    initiative_id: str,
) -> str:
    """Pure function: update agents.md content with heuristics using append/supersede.
    - New heuristics are appended after the ## Heuristics section header (created if absent).
    - Superseded heuristics are marked with a `[superseded by <initiative_id>]` suffix.
    - No existing lines are ever removed — only additions and markers (item_857693d05f70).
    Returns the updated content."""
    # Mark superseded entries in-place.
    lines = content.split("\n")
    for old_heur, new_heur in superseded_pairs:
        for i, line in enumerate(lines):
            # Match the line containing the old heuristic rule (after the bullet marker).
            clean = line.strip().lstrip("- ").strip()
            if clean.startswith(old_heur.rule[:40]) and "[superseded" not in line:
                lines[i] = line.rstrip() + f"  [superseded by {initiative_id}]"
    content = "\n".join(lines)

    # Find or create the Heuristics section and append new entries.
    new_entries: list[str] = []
    for h in new_heuristics:
        tags_part = f" ({', '.join(h.tags)})" if h.tags else ""
        replaces_part = f"  [replaces {h.replaces}]" if h.replaces else ""
        new_entries.append(f"- {h.rule}{tags_part}{replaces_part}")

    if not new_entries:
        return content

    if _HEURISTICS_SECTION_HEADER in content:
        # Insert after the header line.
        idx = content.index(_HEURISTICS_SECTION_HEADER)
        after_header = content.index("\n", idx) + 1
        insertion = "\n".join(new_entries) + "\n"
        content = content[:after_header] + insertion + content[after_header:]
    else:
        # Append a new section at the end.
        section = f"\n{_HEURISTICS_SECTION_HEADER}\n\n" + "\n".join(new_entries) + "\n"
        content = content.rstrip("\n") + "\n" + section

    return content


def _write_heuristics_to_agents_md(
    path_str: str,
    new_heuristics: list[Heuristic],
    superseded_pairs: list[tuple[Heuristic, Heuristic]],
    initiative_id: str,
) -> None:
    """Read agents.md, apply heuristics append/supersede, write back. Non-fatal on I/O errors."""
    try:
        p = Path(path_str)
        current = p.read_text(encoding="utf-8") if p.exists() else ""
        updated = apply_heuristics_to_agents_md(current, new_heuristics, superseded_pairs, initiative_id)
        p.write_text(updated, encoding="utf-8")
    except Exception:
        pass  # agents.md write is best-effort — heuristics DB write already succeeded

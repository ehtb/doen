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
from app.schemas import ConfirmHeuristics, HeuristicDraftResult, HeuristicProposal, LearnReview, OutcomeDraft, RationaleClaim
from app.store import SpecStore

from pathlib import Path

_PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
LEARN_DRAFT_SYSTEM_PROMPT = (_PROMPTS / "learn-draft.txt").read_text().strip()

LEARN_DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "What was intended vs. what happened."},
        "learnings": {"type": "string", "description": "Durable, transferable lessons."},
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


async def draft_outcome(
    store: SpecStore, initiative_id: str, *, llm: StructuredLLM | None = None
) -> OutcomeDraft:
    """BD-13 enriched draft: outcome + structured rationale claims with record-traceable IDs.
    The human corrects and confirms via submit_learn — nothing is written to memory here."""
    review = await learn_review(store, initiative_id)  # raises NotFoundError if absent
    spec = await store.get_spec(initiative_id)
    llm = llm or get_advisor_llm()
    raw = await llm.complete_structured(
        system=LEARN_DRAFT_SYSTEM_PROMPT,
        user=_build_history(review, spec),
        schema=LEARN_DRAFT_SCHEMA,
        schema_name="outcome",
    )

    # Build the set of valid record IDs the LLM is allowed to cite.
    decision_ids = {d.id for d in review.decisions}
    criterion_ids = {c.id for c in (spec.acceptance if spec else [])}
    valid_ids = decision_ids | criterion_ids

    claims = _parse_rationale_claims(raw.get("rationale_claims") or [], valid_ids)

    return OutcomeDraft(
        summary=str(raw.get("summary", "")).strip(),
        learnings=str(raw.get("learnings", "")).strip(),
        rationale_claims=claims,
    )


async def submit_learn(
    store: SpecStore,
    initiative_id: str,
    *,
    summary: str,
    learnings: str | None,
    outcome: dict | None,
    rationale_claims: list[RationaleClaim] | None = None,
) -> LearnReview:
    init = await store.get_initiative(initiative_id)
    if init is None:
        raise NotFoundError(f"no initiative {initiative_id}")
    if not summary.strip():
        raise ValidationError("capturing the outcome needs a human-written summary")
    # BD-13: merge human-confirmed rationale claims into the outcome dict so they are
    # stored with the memory record and retrievable for future initiatives.
    if rationale_claims:
        outcome = {**(outcome or {}), "rationale_claims": [c.model_dump() for c in rationale_claims]}
    # BD-15: carry the initiative type into memory so context hits expose the source type.
    await store.create_memory(
        initiative_id, summary.strip(), learnings, outcome,
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

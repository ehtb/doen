"""get_guidance (spec 0009 u4): the Advisor's contextual briefing for one work unit.

This is the agent-to-agent bridge (constraint 6): the executor reads what the Advisor knows
before it builds, and both coordinate through the shared spec — no messaging protocol. The
briefing is grounded in real spec + memory (the constraints, criteria, and prior patterns are
pulled, never invented); the Advisor only adds the synthesis (the approach + the pitfalls).

Read-only (constraint 5): nothing here writes to the unit or the spec. Briefings are cached
in Redis keyed by unit_id + spec_version, so a spec edit invalidates a stale one for free.
"""

from __future__ import annotations

from typing import Any

from app.exceptions import NotFoundError
from app.models import AcceptanceCriterion, Guidance, ProjectContext, Spec, WorkUnit
from app.providers.llm import StructuredLLM, get_advisor_llm
from app.store import SpecStore

GUIDANCE_SYSTEM_PROMPT = """You are the Doen Advisor, briefing an executor (a coding agent) that \
is about to build ONE work unit of an initiative. Produce a tight, actionable briefing grounded \
in the spec and prior initiatives — not a restatement of the obvious, not generic advice.

You're given the unit's title and scope, the confirmed constraints that bind it, the acceptance \
criteria it must satisfy, and relevant patterns from past initiatives. Constraints are hard lines \
the executor must not cross; acceptance criteria are how the work will be judged.

Return via the guidance tool:
- briefing: a few sentences — how to approach THIS unit, which of the constraints are most \
load-bearing here, and how any prior pattern applies. Specific and concrete, not boilerplate.
- pitfalls: the specific traps to avoid — things that would fail a criterion, cross a constraint, \
or repeat a past mistake. Each one short and actionable.

If this unit's initiative belongs to a PROJECT, you may also be given compact summaries of \
sibling initiatives — their constraints and decisions. Draw on them: reuse a pattern that \
applies, point to a sibling decision that bears on this unit, and flag any contradiction or \
dependency this unit would create with a sibling. You hold only summaries, not full sibling \
specs — don't invent specifics you weren't given.

You are read-only: you brief, you don't build, and you never invent constraints or criteria that \
weren't given to you."""

GUIDANCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "briefing": {
            "type": "string",
            "description": "How to approach this unit; the load-bearing constraints; prior patterns.",
        },
        "pitfalls": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Specific traps to avoid — each short and actionable.",
        },
    },
    "required": ["briefing"],
}


def _criteria_for(spec: Spec, unit: WorkUnit) -> list[AcceptanceCriterion]:
    """The acceptance criteria this unit maps to (by id). Falls back to none if its
    criterion_ids don't resolve — the briefing still carries the constraints + scope."""
    by_id = {a.id: a for a in spec.acceptance}
    return [by_id[cid] for cid in unit.criterion_ids if cid in by_id]


def _criterion_line(a: AcceptanceCriterion) -> str:
    return f"{a.text}  [verify: {a.verify.kind} — {a.verify.detail}]"


def _project_block(pctx: ProjectContext) -> str:
    """Compact sibling awareness for a unit in a project (0010 a6): which sibling constraints
    and decisions may bear on this unit. Summaries, not full specs (constraint 3/5)."""
    lines = [
        f"# PROJECT CONTEXT — {pctx.name}",
        "Sibling initiatives whose constraints or decisions may bear on this unit "
        "(reuse what applies; flag any contradiction or dependency):",
    ]
    for s in pctx.siblings:
        lines.append(f"- {s.title} [{s.initiative_id}] · stage {s.stage}")
        lines += [f"    constraint: {c}" for c in s.constraints]
        if s.latest_decision:
            lines.append(f"    decision: {s.latest_decision}")
    return "\n".join(lines)


def _build_user_message(
    unit: WorkUnit,
    constraints: list[str],
    criteria: list[str],
    memory_block: str,
    project_block: str = "",
) -> str:
    parts = [
        f"# WORK UNIT\nTitle: {unit.title}\nScope: {unit.scope}",
    ]
    if unit.progress_note:
        parts.append(f"Progress so far: {unit.progress_note}")
    parts.append(
        "# CONFIRMED CONSTRAINTS (hard lines — must not cross):\n"
        + ("\n".join(f"- {c}" for c in constraints) or "(none confirmed yet)")
    )
    parts.append(
        "# ACCEPTANCE CRITERIA THIS UNIT MUST SATISFY:\n"
        + ("\n".join(f"- {c}" for c in criteria) or "(none mapped)")
    )
    if project_block:
        parts.append(project_block)
    if memory_block:
        parts.append(memory_block)
    return "\n\n".join(parts)


async def generate_guidance(
    store: SpecStore, unit_id: str, *, llm: StructuredLLM | None = None
) -> Guidance:
    """Build (or serve from cache) the briefing for a work unit. Grounded fields come from the
    spec + memory; the Advisor synthesises the briefing + pitfalls. Cached by unit_id +
    spec_version (constraint 5 / discretion: a spec edit invalidates it for free)."""
    unit = await store.get_unit(unit_id)
    if unit is None:
        raise NotFoundError(f"no work unit {unit_id}")
    spec = await store.get_spec(unit.spec_id)
    if spec is None:
        raise NotFoundError(f"no spec for initiative {unit.spec_id}")

    cached = await store.read_guidance_cache(unit_id, spec.version)
    if cached is not None:
        return cached

    # the initiative's project (if any) scopes both the memory search and the sibling block (0010 a6)
    init = await store.get_initiative(unit.spec_id)
    project_id = init.project_id if init else None

    constraints = [c.text for c in spec.confirmed_constraints()]
    criteria = [_criterion_line(a) for a in _criteria_for(spec, unit)]
    # ground the briefing in prior patterns relevant to this unit's work — project-first when
    # the initiative is in a project (constraint 4), so sibling decisions surface first.
    query = f"{unit.title}\n{unit.scope}"
    memory = await store.get_context(query, limit=5, project_id=project_id)
    memory_block = ""
    if memory:
        memory_block = "# RELEVANT PRIOR PATTERNS (reuse what applies; don't contradict them):\n" + "\n".join(
            f"- ({h.type} · {h.initiative_id}, score {h.score}): {h.text}" for h in memory
        )
    # sibling awareness: the constraints/decisions of other initiatives in this project (a6)
    project_block = ""
    if project_id:
        pctx = await store.get_project_context(project_id, exclude=unit.spec_id)
        if pctx and pctx.siblings:
            project_block = _project_block(pctx)

    llm = llm or get_advisor_llm()
    raw = await llm.complete_structured(
        system=GUIDANCE_SYSTEM_PROMPT,
        user=_build_user_message(unit, constraints, criteria, memory_block, project_block),
        schema=GUIDANCE_SCHEMA,
        schema_name="guidance",
    )
    pitfalls = [str(p) for p in (raw.get("pitfalls") or [])]
    guidance = Guidance(
        unit_id=unit_id,
        title=unit.title,
        scope=unit.scope,
        spec_version=spec.version,
        constraints=constraints,
        criteria=criteria,
        memory=memory,
        briefing=str(raw.get("briefing", "")).strip(),
        pitfalls=pitfalls,
    )
    await store.write_guidance_cache(guidance)
    return guidance

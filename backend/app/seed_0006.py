"""Seed spec 0006 — AI-assisted spec shaping — INTO Doen.

Its own initiative_id (the author's header said `initiative: build-doen`, but that id is
the shipped Steering-rail spec; following the `build-doen-000N-name` convention so it
never clobbers a prior spec). Items seed as proposed; the human confirms in the UI.

The one open shaping decision is resolved per the author's recommendation ("go with the
recommendation") and folded into the constraints — no open decision row is seeded:
  D1 -> (b) distill the spec contract for the system prompt (adapt the /spec skill's
            SKILL.md), not the full spec-contract.md   (constraint 9)

Planned decomposition (proposed later via MCP propose_unit during decompose, NOT seeded):
  u1 LLM provider interface + Claude default (Anthropic SDK)      -> a6
  u2 shaping prompt + structured-output parsing + get_context     -> a2, a4, a5
  u3 shaping endpoint (description -> get_context -> LLM -> save)  -> a3
  u4 shaping UI ("shape with AI" + proposed items in the view)    -> a1, a7, a8

    cd backend && .venv/bin/python -m app.seed_0006
"""

from __future__ import annotations

import asyncio

import asyncpg
from redis import asyncio as aioredis

from app.config import DATABASE_URL, DEV_ORG_ID, DEV_USER_ID, REDIS_URL
from app.store import (
    AcceptanceCriterion,
    Reference,
    Spec,
    SpecItem,
    SpecStore,
    Verify,
)

INITIATIVE_ID = "build-doen-0006-ai-assisted-spec-shaping"
TITLE = "AI-assisted spec shaping"

_DRAFT = dict(provenance="ai_proposed", status="proposed")

_INTENT = """Shaping a spec today means hand-typing every constraint, discretion item, and \
acceptance criterion — or having Claude Code draft them externally and pasting them in. The \
authoring half works (0002), but the human starts from a blank page every time. This spec adds \
the AI to the authoring: describe what you want in plain language, and the system proposes a \
complete structured spec — intent, constraints, discretion, acceptance criteria — all as \
ai_proposed items you confirm, edit, or reject one by one. Memory feeds it: relevant patterns \
from completed initiatives are retrieved via get_context and included in the prompt, so the \
proposal is informed by organizational history, not just the description. This is \
correction-over-authoring made real in the product: the AI drafts, the human corrects, and the \
spec crystallises through confirmation."""

_CONSTRAINTS = [
    "The LLM provider is pluggable — not hard-coded to any vendor. Same pattern as the embedding "
    "provider (0005): a provider interface (structured prompt in, structured spec out), with a "
    "concrete default wired for dogfooding. The hosted tier uses it as-is; a self-hoster can swap "
    "providers.",
    "API keys are environment variables, never stored in the database. No secrets in the app "
    "store. The shaping endpoint reads from env at call time.",
    "All generated items enter as ai_proposed / proposed. Nothing is auto-confirmed. The human "
    "confirmation step is non-negotiable — this is the product's central trust boundary.",
    "The LLM output must be structured and parseable into existing Pydantic models (SpecItem, "
    "AcceptanceCriterion, etc.). Free-form markdown that requires regex extraction is not "
    "acceptable. Use structured output (tool_use, JSON mode, or equivalent) to guarantee shape.",
    "The system prompt encodes the spec contract's structure and discipline. It must communicate: "
    "intent as narrative (problem + outcome), constraints as must/must-not, discretion as explicit "
    "latitude, acceptance criteria as verifiable with [test]/[behavior]/[metric]/[human_judgment] "
    "tags, and the constraint-vs-discretion partition (if a likely decision falls in neither, flag "
    "it). The prompt is the product — the quality of the proposed spec depends entirely on it.",
    "get_context is called before the LLM call to feed relevant priors from memory. If no relevant "
    "context exists, shaping works without it — graceful degradation, not failure.",
    "A failed LLM call surfaces a clear error — no silent failure, no partial spec corruption. The "
    "spec is untouched if the call fails.",
    "No auth this slice — single dev user.",
    "The shaping system prompt uses a DISTILLED spec contract — the structure "
    "(intent/constraints/discretion/acceptance), the constraint-vs-discretion discipline, and the "
    "acceptance-criteria rules — adapting the /spec skill's SKILL.md as its core, not the full "
    "spec-contract.md (the LLM needs neither the MCP tool signatures nor the operating loop to "
    "draft a spec) (D1 resolved -> b: distill).",
]

_DISCRETION = [
    "The dogfooding default LLM provider (Claude API via the Anthropic SDK is the obvious choice, "
    "but this is yours).",
    "Structured output mechanism (tool_use with a spec schema, JSON mode with a Pydantic schema "
    "prompt, or another approach that satisfies constraint 4).",
    "Whether to stream the response for UX or wait for the complete response before showing "
    "proposed items.",
    "The 'shape with AI' trigger: button placement, how the text input is presented (modal, "
    "inline, full-page), minimum input required.",
    "Loading / progress indication during the LLM call.",
    "Whether re-triggering shaping on a spec that already has items replaces all proposed "
    "(unconfirmed) items, adds alongside them, or prompts the user to choose.",
    "How proposed items are presented after generation (all at once in the spec view, section by "
    "section, or with a review step before persisting).",
    "How many get_context results to include in the prompt (balance context richness against token "
    "cost).",
]

# (text, verify kind, verify detail)
_ACCEPTANCE = [
    ("A 'shape with AI' action is available on a spec in the discover or shape stage. Triggering "
     "it presents a text input for describing the initiative's intent.", "behavior",
     "Open a discover/shape spec; the 'shape with AI' control presents a description input."),
    ("Submitting a description calls the LLM provider and produces structured spec items: intent "
     "text, constraints, discretion items, and acceptance criteria (with verify kinds and tags).",
     "behavior",
     "Submit a description; structured items (intent + constraints + discretion + acceptance) "
     "come back."),
    ("Every generated item is persisted as provenance=ai_proposed, status=proposed. No item is "
     "auto-confirmed.", "test",
     "After generation, assert every new item has provenance=ai_proposed and status=proposed."),
    ("get_context is called with the description as query before the LLM call; results (if any) "
     "are included in the prompt. When no relevant context exists, the call succeeds without "
     "memory context.", "test",
     "Assert get_context runs pre-LLM and its hits feed the prompt; with an empty corpus the call "
     "still succeeds."),
    ("Generated items are valid model instances: constraints and discretion are SpecItem, "
     "acceptance criteria are AcceptanceCriterion with verify.kind and verify.detail populated.",
     "test",
     "Parse the LLM output into the models; assert validation passes and verify fields are set."),
    ("A failed LLM call (network error, malformed response, missing API key) surfaces an error "
     "message in the UI; the spec is unchanged.", "test",
     "Force a provider failure; assert an error is returned and the spec version/content is "
     "untouched."),
    ("After generation, the proposed items appear in the spec view and are immediately actionable "
     "via the existing editing flow — confirm, edit, reject, retire.", "behavior",
     "After generation, confirm / edit / retire a proposed item through the existing 0002 "
     "controls."),
    ("A human describes a feature idea in a few sentences, receives a complete proposed spec "
     "informed by organizational memory, and confirms it item by item into a governing spec. The "
     "shaping feels like correcting a knowledgeable first draft, not filling a blank form. "
     "[HEADLINE]", "human_judgment",
     "Describe a feature; judge whether the proposed, memory-informed spec is a first draft worth "
     "correcting into a governing spec."),
]

_REFERENCES = [
    ("code", "backend/app/embeddings.py",
     "the pluggable-provider pattern (0005) to mirror for the LLM provider (constraint 1)."),
    ("code", "backend/app/store.py",
     "get_context feeds memory priors (constraint 6); save_spec persists proposed items; "
     "SpecItem / AcceptanceCriterion are the parse targets (constraint 4)."),
    ("prior_initiative", "build-doen-0002-spec-editing",
     "the proposed->confirmed authoring flow the generated items enter and act through (a7)."),
    ("prior_initiative", "build-doen-0005-memory-learn-stage",
     "get_context + the pluggable-provider precedent this builds on."),
    ("doc", "docs/spec-contract.md",
     "distilled (not included whole) into the shaping system prompt — D1 resolved -> b."),
    ("doc", "/spec skill (SKILL.md)",
     "adapted as the core of the shaping system prompt (D1 -> b)."),
]


def build_spec() -> Spec:
    return Spec(
        initiative_id=INITIATIVE_ID,
        stage="shape",
        title=TITLE,
        intent=_INTENT,
        constraints=[SpecItem(text=t, **_DRAFT) for t in _CONSTRAINTS],
        discretion=[SpecItem(text=t, **_DRAFT) for t in _DISCRETION],
        acceptance=[
            AcceptanceCriterion(text=t, verify=Verify(kind=k, detail=d), **_DRAFT)
            for (t, k, d) in _ACCEPTANCE
        ],
        references=[Reference(kind=k, pointer=p, note=n) for (k, p, n) in _REFERENCES],
    )


async def seed() -> None:
    pg = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    store = SpecStore(pg, redis)
    try:
        await pg.execute(
            """INSERT INTO initiatives (id, org_id, owner_id, appetite, stage, title)
               VALUES ($1, $2, $3, $4, 'shape', $5)
               ON CONFLICT (id) DO NOTHING""",
            INITIATIVE_ID, DEV_ORG_ID, DEV_USER_ID, "small", TITLE,
        )
        existing = await store.get_spec(INITIATIVE_ID)
        if existing is not None:
            print(f"spec for '{INITIATIVE_ID}' already present (v{existing.version}); "
                  "leaving it untouched")
            return
        saved = await store.save_spec(build_spec())
        print(f"seeded '{INITIATIVE_ID}' spec v{saved.version}: {saved.title}")
    finally:
        await pg.close()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(seed())

"""Seed spec 0009 — Conversation rail & the Doen Advisor — INTO Doen.

Follows the `build-doen-000N-name` convention (the author header said `initiative:
build-doen`, but that id is the shipped Steering-rail spec). Items seed as proposed; the
human confirms in the UI.

Two shaping decisions were resolved by the author in-session, folded into the items per the
0006 precedent (no open decision row is seeded):
  D1 (proactive vs reactive) -> (b) reactive, with the one proactive trigger: auto-generate
     a verification review when a unit is submitted. Folded into constraint 6 + discretion.
  D2 (one-shot shaping coexistence) -> (c) the one-shot becomes a rail command: "shape this
     initiative: [description]" triggers the 0006 full draft, surfaced as proposal cards,
     then refined through dialogue. One AI surface. Folded into constraint 4 + a3.

Planned decomposition (proposed later via MCP propose_unit during decompose, NOT seeded):
  u1 conversation persistence (messages table, endpoints, context-window assembly)  -> a4
  u2 Advisor core (stage-aware prompt, LLM via 0006 provider, structured proposals)  -> a2, a5
  u3 conversation rail UI (dark surface, messages, input, proposal cards, mode)      -> a1, a3
  u4 get_guidance MCP tool (unit briefing, caching, read-only to executors)          -> a6
  u5 verify review + learn draft (evidence vs criteria; outcome drafting)            -> a7, a8, a9

    cd backend && .venv/bin/python -m app.seed_0009
"""

from __future__ import annotations

import asyncio

import asyncpg
from redis import asyncio as aioredis

from app.config import DATABASE_URL, DEV_ORG_ID, DEV_USER_ID, REDIS_URL
from app.models import AcceptanceCriterion, Reference, Spec, SpecItem, Verify
from app.store import SpecStore

INITIATIVE_ID = "build-doen-0009-conversation-rail"
TITLE = "Conversation rail & the Doen Advisor"

_DRAFT = dict(provenance="ai_proposed", status="proposed")

_INTENT = """The AI appears at one moment today — the entrance. After shaping, Doen goes \
passive: the spec is a static document, the human watches from the outside, and nobody is \
actively thinking alongside either the human or the executor. The thesis says Doen is where a \
human authors intent and verifies outcomes with an AI as a thinking partner; in practice the \
thinking partner shows up for five minutes and vanishes. The conversation rail fixes this. It's \
the persistent dark surface from the LivingSpec prototype — visually distinct from the spec, \
present on every initiative — and it hosts the Doen Advisor: an AI agent that knows the spec \
contract discipline, the organisational memory, and the full initiative context. The Advisor's \
contribution changes with the lifecycle stage: it shapes through dialogue during shape, proposes \
unit breakdowns during decompose, generates contextual briefings executors read via MCP during \
implement, reviews submissions against criteria during verify, and drafts outcome summaries \
during learn. The executor and the Advisor share context through the spec — not through direct \
messaging — so every exchange is visible, auditable, and steerable by the human."""

_CONSTRAINTS = [
    "Conversation history is persisted per initiative — individual message rows, not a JSONB "
    "blob. The rail shows the full history; the Advisor's LLM calls receive a windowed recent "
    "context (not unbounded). Context management is explicit: a maximum message window plus the "
    "current spec state plus relevant memory.",
    "The Advisor reuses the LLM provider interface from 0006. Same pluggable provider, same "
    "env-based key management. No second AI integration path.",
    "The Advisor's system prompt is stage-aware. It adapts based on the initiative's current "
    "stage — shaping drafts spec items, implementing generates guidance, verifying reviews "
    "evidence, learning drafts outcomes. The prompt always includes: the spec contract structure "
    "(distilled), the current confirmed spec, relevant memory from get_context, and conversation "
    "history within the window.",
    "All spec mutations go through the existing editing flow (0002). The Advisor proposes items "
    "that appear as actionable proposal cards in the rail; confirming a card calls the editing "
    "endpoints. The Advisor never writes to the spec directly. The human confirmation step is "
    "non-negotiable. (D2 resolved -> c: the 0006 one-shot becomes a rail command — \"shape this "
    "initiative: [description]\" produces a full draft as a batch of proposal cards, not a silent "
    "write; refinement then happens through dialogue. One AI surface, not two.)",
    "get_guidance(unit_id) is a new read-only MCP tool. It returns the Advisor's contextual "
    "briefing for a specific work unit — relevant constraints, memory, known pitfalls, the "
    "Advisor's notes. The executor reads it; it never writes to it. Briefings are generated on "
    "demand (or cached briefly in Redis with a short TTL).",
    "The Advisor includes executor submissions and progress in its context when relevant (during "
    "verify and implement stages). This enables the verification review and the agent-to-agent "
    "coordination: the Advisor reads what the executor produced; the executor reads the Advisor's "
    "guidance. Both go through Doen, both are visible to the human. (D1 resolved -> b: the rail is "
    "reactive — it speaks when spoken to — with exactly one proactive trigger: an auto-generated "
    "verification review when a unit is submitted, the highest-value, least-noisy moment.)",
    "The conversation rail is the dark surface from the prototype — visually distinct from the "
    "warm spec surface. The two-surface model is the design, not an afterthought.",
    "No auth this slice — single dev user.",
]

_DISCRETION = [
    "Context window strategy: how many recent messages to include, whether to summarise older "
    "history into a compact context block, how to balance message history against spec state "
    "against memory tokens.",
    "Whether to stream Advisor responses for UX or wait for the complete response.",
    "Proposal card rendering: how they appear in the rail, how confirm/reject connects to the "
    "editing endpoints, whether to show a diff-preview of what confirming would add to the spec.",
    "Whether to show the Advisor's reasoning process or just the output.",
    "get_guidance caching: TTL, cache key (unit_id + spec version?), invalidation on spec change.",
    "How the Advisor's stage-specific behaviour is triggered — by the initiative's stage field "
    "automatically, or by the type of request the human makes.",
    "Rail layout details: message density, how proposals interleave with regular messages, scroll "
    "behaviour, the input area.",
    "Whether the Advisor's verification review notes appear automatically when a unit is submitted, "
    "or only when the human asks. (D1 resolved -> b: automatically on submit — the single "
    "proactive moment.)",
]

# (text, verify kind, verify detail)
_ACCEPTANCE = [
    ("A conversation rail is visible alongside the spec on every initiative page, visually "
     "distinct (dark surface, per the prototype's design language).", "behavior",
     "Open any initiative; a dark conversation rail sits alongside the warm spec surface."),
    ("Messages sent by the human receive Advisor responses that demonstrate awareness of: the "
     "current spec (confirmed items), the current stage, and relevant memory (prior initiative "
     "patterns when applicable).", "behavior",
     "Message the Advisor; its reply references the confirmed spec, the current stage, and "
     "relevant prior-initiative memory when applicable."),
    ("During shape, the Advisor proposes spec items through dialogue. Proposals appear as "
     "actionable cards in the rail with confirm / reject. Confirming adds the item to the spec as "
     "ai_proposed / proposed via the existing editing flow.", "behavior",
     "In shape, ask the Advisor for items; cards appear; confirming one adds an ai_proposed item "
     "via the 0002 editing endpoints."),
    ("Conversation history persists across sessions. Closing and reopening an initiative shows "
     "prior messages. Messages are stored as individual rows with role, content, and timestamp.",
     "test",
     "Post messages, restart; reopening the initiative replays them. DB shows one row per message "
     "with role, content, created_at."),
    ("The Advisor's responses adapt to the current lifecycle stage: shaping produces spec-item "
     "proposals, implementing surfaces risks and guidance, verifying references acceptance "
     "criteria against evidence, learning drafts outcome summaries.", "behavior",
     "Move an initiative through stages; the same Advisor shifts mode — proposals, then risks, "
     "then criteria-vs-evidence, then outcome drafts."),
    ("get_guidance(unit_id) on the MCP server returns a contextual briefing for the unit — "
     "informed by the spec, memory, and the Advisor's reasoning. The executor calls it before "
     "building.", "behavior",
     "Call get_guidance(unit_id) over MCP; it returns a briefing drawing on the unit's spec scope "
     "+ memory, read-only."),
    ("During verify, the Advisor can review a submitted unit's evidence against the acceptance "
     "criteria and surface preliminary notes (gaps, alignment, concerns) for the human verifier.",
     "behavior",
     "Submit a unit in verify; the Advisor posts preliminary review notes mapping evidence to each "
     "acceptance criterion."),
    ("During learn, the Advisor drafts an outcome summary and key learnings from the initiative's "
     "history (spec, decisions, verification outcomes). The human corrects and confirms before it "
     "writes to memory.", "behavior",
     "In learn, the Advisor drafts a summary + learnings from the history; the human edits and "
     "confirms before it persists to memory."),
    ("The Advisor is a persistent thinking partner throughout the lifecycle. A developer shaping, "
     "building, verifying, and learning on an initiative feels actively guided — the AI knows the "
     "context, remembers the history, and contributes at the right moments without overstepping "
     "into decisions that belong to the human. [HEADLINE]", "human_judgment",
     "Run a full initiative with the Advisor; it feels like a present, context-aware partner that "
     "contributes at the right moments and never usurps the human's decisions."),
]

_REFERENCES = [
    ("design", "docs/prototypes/living-spec.jsx",
     "the dark conversation-rail surface (visually distinct from the warm spec) to build — u3 / "
     "a1 / constraint 7."),
    ("code", "backend/app/providers/llm.py",
     "the pluggable LLM provider the Advisor reuses — no second integration path (constraint 2) — "
     "u2."),
    ("code", "backend/app/services/shaping.py",
     "the 0006 one-shot full-draft generation the rail command (\"shape this initiative: ...\") "
     "reuses, surfacing results as proposal cards instead of a silent write — D2 / u2 / u3 / a3."),
    ("code", "backend/app/services/authoring.py",
     "the existing editing flow (add/confirm ai_proposed items) that confirming a proposal card "
     "calls — the Advisor never writes the spec directly (constraint 4) — u3 / a3."),
    ("code", "backend/app/store.py",
     "get_context (memory retrieval) the Advisor's prompt draws on, and where conversation "
     "persistence + briefing assembly live — u1 / u4 / constraint 3."),
    ("code", "backend/app/mcp_server.py",
     "where get_guidance(unit_id) is added as a read-only MCP tool the executor calls before "
     "building — u4 / a6."),
    ("prior_initiative", "build-doen-0005-memory-learn-stage",
     "get_context + the memory the Advisor retrieves and the learn-stage outcome it drafts — a2 / "
     "a8."),
    ("prior_initiative", "build-doen-0006-ai-assisted-spec-shaping",
     "the LLM provider + one-shot shaping the Advisor extends into dialogue — constraint 2 / D2."),
    ("doc", "docs/spec-contract.md",
     "the spec-contract discipline distilled into the Advisor's stage-aware system prompt — "
     "constraint 3 / u2."),
]


def build_spec() -> Spec:
    return Spec(
        initiative_id=INITIATIVE_ID,
        state="draft",
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
            """INSERT INTO initiatives (id, org_id, owner_id, appetite, state, title, project_id)
               VALUES ($1, $2, $3, $4, 'draft', $5, 'build-doen')
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

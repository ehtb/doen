"""Seed spec 0012 — Progressive disclosure & guided review — INTO Doen.

Follows the `build-doen-000N-name` convention. Items seed as proposed; the human confirms
in the UI (and, once u3 lands, is walked through them by the Advisor item by item).

Two shaping decisions were resolved by the author in-session, folded into the items per the
0006/0011 precedent (no open decision row is seeded):
  D1 (conversation-led review: opt-in or context-default?) -> (b) context-default. A freshly
     shaped spec opens in conversation-led review (the natural continuation of "here's what I
     drafted"); returning to an existing spec gets the document view with progressive disclosure
     + the 0011 attention surface. The signal is whether the Advisor's last message is the
     shaping proposal. Folded into constraint 5.
  D2 ("Confirm all remaining" — should it exist?) -> (c) confirm-all for discretion only.
     Constraints and acceptance criteria are the contract — each governs what the agent must /
     must not do, so individual confirmation is the trust model, not overhead. Discretion items
     are agent latitude by definition; bulk-confirming them is fine. Folded into constraint 3.

Planned decomposition (proposed later via MCP propose_unit during shaping, NOT seeded):
  u1 progressive disclosure (collapsible sections, badges, guided order, View all, latitude) -> a1, a2, a3
  u2 progress indicator (confirmed/total at the top, live-updating)                          -> a4
  u3 conversation-led review (Advisor walks items in the rail; surface builds up live)       -> a5, a6, a8
  u4 adaptive rail prominence (open in review; collapse on manual interaction; resume-aware)  -> a7, a9
  u5 sequential initiative IDs (project prefix + per-project sequence, slug, URL, migration)  -> a10, a11

    cd backend && .venv/bin/python -m app.seed_0012
"""

from __future__ import annotations

import asyncio

import asyncpg
from redis import asyncio as aioredis

from app.config import DATABASE_URL, DEV_ORG_ID, DEV_USER_ID, REDIS_URL
from app.models import AcceptanceCriterion, Reference, Spec, SpecItem, Verify
from app.store import SpecStore

INITIATIVE_ID = "build-doen-0012-progressive-disclosure"
TITLE = "Progressive disclosure & guided review"

_DRAFT = dict(provenance="ai_proposed", status="proposed")

_INTENT = """The spec page shows everything at once with equal visual weight. A freshly shaped \
initiative lands the user on a wall of 12+ items — constraints, discretion, criteria, units — all \
with Accept buttons, alongside a full conversation thread. There's no hierarchy, no sequence, no \
sense of "start here" or "you're done." The content is right; the experience is overwhelming. This \
spec transforms the spec page from a document you parse into a flow you're guided through. Sections \
disclose progressively, the Advisor walks you through items one at a time in the rail, the spec \
surface builds up visually as you confirm, and discretion steps back so the human focuses on what \
actually governs. The user always knows where they are, what's next, and when they're finished."""

_CONSTRAINTS = [
    "Sections are collapsed by default when unconfirmed items exist. Each section header shows a "
    "badge: \"3 to review.\" Expanding one section focuses attention there. The full document is "
    "always reachable via a \"View all\" toggle — progressive disclosure is the default, not a "
    "prison.",
    "The guided order is: Intent -> Constraints -> Acceptance Criteria -> Work Units. This is the "
    "natural review arc — why, what boundaries, how we judge, how we build. The UI presents "
    "sections in this order and auto-expands the next section with unconfirmed items after the "
    "current one is complete.",
    "Discretion is not part of the main review flow. It collapses under an \"Agent latitude\" "
    "section, visually de-emphasised. These are the executor's choices, not the human's governing "
    "decisions. Showing them at the same prominence as constraints dilutes focus. (D2 resolved -> "
    "c: a \"Confirm all remaining\" action exists for discretion items ONLY — they are agent "
    "latitude by definition, so bulk-confirming them is fine. Constraints and acceptance criteria "
    "require individual confirmation; each governs what the agent must / must not do, and per-item "
    "confirmation is the trust model, not ceremony.)",
    "A progress indicator shows confirmed vs. total at the top of the spec page, updating live as "
    "items are confirmed. The user always sees how far along the review is and when it's complete.",
    "A conversation-led review mode is the default for freshly shaped specs. The Advisor presents "
    "items one at a time in the rail: the item text, its rationale if relevant, and Accept / Reject "
    "/ Edit actions. Confirming moves to the next item. The spec surface on the left builds up in "
    "real time as items are confirmed — the human watches the spec crystallise. (D1 resolved -> b: "
    "conversation-led review is context-default, not always-on. Fresh shape -> the walkthrough "
    "(the natural next step after \"here's what I drafted\"). Returning to an existing spec -> the "
    "document view with progressive disclosure + the 0011 attention surface. The signal is whether "
    "the Advisor's last message is the shaping proposal.)",
    "The rail adapts its prominence to the moment. During creation and conversation-led review: the "
    "rail is open and dominant (it's the primary interaction surface). When the user switches to "
    "manual document review (expanding sections directly, using \"View all\"): the rail "
    "auto-collapses to a slim trigger the user can reopen to ask the Advisor questions. The two "
    "surfaces complement, never compete.",
    "Rejecting an item in conversation-led review removes it from the spec (per 0011's decision: "
    "delete from spec, log in rail) and the Advisor acknowledges and moves on. No friction, no "
    "\"are you sure.\" The conversation history preserves what was proposed and rejected.",
    "Initiatives get sequential IDs within their project. Each project has a short prefix (e.g. "
    "\"BD\" for Build Doen). Each initiative is numbered sequentially: BD-1, BD-2, BD-3. The URL "
    "slug combines the sequential ID with a human-readable slug: `bd-1-csv-export`. The sequential "
    "number auto-increments per project and is immutable once assigned. The prefix + number is the "
    "canonical short identifier used in references, navigation, and conversation (\"see BD-7\").",
]

_DISCRETION = [
    "How the collapsed rail trigger appears (icon, thin strip, floating button, edge tab).",
    "Animation when an item is confirmed and appears on the spec surface (fade in, slide, subtle "
    "highlight).",
    "Whether the Advisor provides rationale for each item automatically during the guided review or "
    "only when the user asks.",
    "How editing an item works in the conversation-led flow (inline text edit in the rail card, or "
    "opens the item in the spec surface for editing, then returns to the rail flow).",
    "How \"View all\" is presented (a toggle, a tab, or a scroll-past that opens all sections).",
    "Whether to show a completion state (all items reviewed) with a summary or celebration.",
    "The progress indicator format (bar, fraction, ring, stepper dots).",
    "How the user re-enters conversation-led review if they navigated away mid-flow (a \"resume "
    "review\" prompt, or the rail picks up where it left off automatically).",
    "Whether the Advisor groups related items (\"here are the 3 constraints about security — want "
    "to review them together?\") or always presents individually.",
    "How the project prefix is derived: auto-generated from the project name (first letters of each "
    "word), manually set by the user at project creation, or editable after auto-generation.",
    "Whether the sequential ID (BD-7) is shown prominently in the spec page header, the project "
    "dashboard, and the rail — or just in navigation and URLs.",
]

# (text, verify kind, verify detail)
_ACCEPTANCE = [
    ("On a spec with unconfirmed items, sections are collapsed by default. Each section header "
     "shows a count of items awaiting review. \"View all\" opens everything.", "behavior",
     "Open a spec with proposed items; sections are collapsed with per-section review counts; "
     "\"View all\" expands everything."),
    ("Sections follow the guided order: Intent -> Constraints -> Acceptance Criteria -> Work "
     "Units. Completing a section (all items confirmed or rejected) auto-expands the next section "
     "with pending items.", "behavior",
     "Sections render in the guided order; finishing one section auto-expands the next section "
     "that still has pending items."),
    ("Discretion is collapsed under \"Agent latitude,\" visually distinct from the governing "
     "sections, and not part of the auto-expand sequence.", "behavior",
     "Discretion sits under an \"Agent latitude\" section, visually de-emphasised, and is skipped "
     "by the auto-expand flow."),
    ("A progress indicator at the top of the spec page shows confirmed/total (e.g. \"5 of 14 "
     "confirmed\") and updates live as items are accepted or rejected.", "behavior",
     "The top of the spec page shows confirmed/total; accepting or rejecting an item updates the "
     "count live."),
    ("On a freshly shaped spec, the conversation rail opens in guided review mode: the Advisor "
     "presents the first item with Accept / Reject / Edit. Accepting moves to the next item. The "
     "user is walked through the spec sequentially.", "behavior",
     "A freshly shaped spec opens with the rail in guided review; the Advisor presents item 1 with "
     "Accept / Reject / Edit; accepting advances to the next item."),
    ("As items are confirmed in the conversation-led review, they appear on the spec surface in "
     "real time — the spec visibly builds up. The user sees the contract crystallising, not just a "
     "list of buttons changing state.", "behavior",
     "Confirming an item in the rail makes it appear/solidify on the spec surface immediately — the "
     "surface builds up as the review proceeds."),
    ("Switching from conversation-led review to manual document interaction (expanding a section, "
     "clicking \"View all\") collapses the rail to a slim trigger. Reopening the rail resumes the "
     "conversation where it left off.", "behavior",
     "Expanding a section or clicking \"View all\" collapses the rail to a trigger; reopening it "
     "resumes the guided review at the same point."),
    ("Rejecting an item in conversation-led review removes it from the spec and the Advisor moves "
     "to the next item without friction. The rejection is visible in the conversation history.",
     "test",
     "Reject an item in guided review -> it is removed from the spec, the Advisor advances to the "
     "next item with no confirmation step, and the rejection appears in the conversation history."),
    ("A user receiving a freshly shaped spec is guided through it item by item, always knows what "
     "to review next, sees the spec build up as they confirm, and never faces a wall of "
     "undifferentiated content. The experience feels like a conversation, not a form. [HEADLINE]",
     "human_judgment",
     "A user handed a freshly shaped spec is walked through it item by item, always knows what's "
     "next, watches the spec build up, and never hits a wall of undifferentiated content — it "
     "feels like a conversation, not a form."),
    ("Every initiative has a sequential ID within its project (e.g. BD-1, BD-2). The URL uses the "
     "format /{project}/specs/{prefix-number-slug} (e.g. /build-doen/specs/bd-1-csv-export). IDs "
     "auto-increment per project and are immutable.", "test",
     "Each initiative has a per-project sequential ID (BD-1, BD-2, ...); the URL is "
     "/{project}/specs/{prefix-number-slug}; IDs auto-increment per project and never change once "
     "assigned."),
    ("The sequential ID is visible in the spec page header, the project dashboard, and anywhere "
     "initiatives are referenced. Users can refer to initiatives by short ID (BD-7) in "
     "conversation with the Advisor.", "behavior",
     "The short ID shows in the spec header, the project dashboard, and references; the Advisor "
     "understands \"BD-7\" in conversation."),
]

_REFERENCES = [
    ("code", "web/app/projects/[id]/specs/[specId]/SpecDocument.tsx",
     "progressive disclosure: collapsible sections, review-count badges, guided order, \"View "
     "all\", discretion under \"Agent latitude\" — u1 / a1 / a2 / a3."),
    ("code", "web/app/projects/[id]/specs/[specId]/page.tsx",
     "hosts the progress indicator at the top and the spec surface that builds up live during "
     "guided review — u2 / u3 / a4 / a6."),
    ("code", "web/app/projects/[id]/specs/[specId]/ConversationRail.tsx",
     "conversation-led review: item-by-item Accept / Reject / Edit; adaptive prominence (collapse "
     "on manual interaction, resume-aware) — u3 / u4 / a5 / a7."),
    ("code", "web/app/projects/[id]/specs/[specId]/AttentionSurface.tsx",
     "the 0011 attention surface shown on RETURN to an existing spec (the non-fresh path of the "
     "context-default review) — u4 / D1."),
    ("code", "backend/app/services/advisor.py",
     "guided-review mode: detect a freshly shaped spec and present items sequentially with "
     "rationale; understand short IDs (BD-7) in conversation — u3 / u5 / a5 / a11."),
    ("code", "backend/app/models.py",
     "Project prefix + per-project sequential number on the initiative; the canonical short ID — "
     "u5 / a10."),
    ("code", "backend/app/store.py",
     "allocate the immutable per-project sequence on creation; resolve a spec by prefix-number "
     "slug — u5 / a10."),
    ("code", "web/app/projects/[id]/page.tsx",
     "the project dashboard shows each initiative's short ID (BD-N) — u5 / a11."),
    ("prior_initiative", "build-doen-0009-conversation-rail",
     "the Advisor + rail this guided review drives item by item and adapts in prominence — u3 / "
     "u4 / a5 / a7."),
    ("prior_initiative", "build-doen-0010-projects",
     "projects gain a prefix and a per-project initiative sequence (BD-1, BD-2) — u5 / a10."),
    ("prior_initiative", "build-doen-0011-guiding-the-human",
     "the attention surface + description-first creation this builds on; the rejection-deletes-and-"
     "logs decision reused in guided review — u1 / u4 / a3 / a8."),
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

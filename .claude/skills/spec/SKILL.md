---
name: spec
description: >
  Author a Doen spec — the living-spec artifact that governs a feature or initiative.
  Use whenever asked to write, draft, shape, or scaffold a spec, or to turn a feature idea
  into a spec under specs/. Produces a well-formed spec (intent, constraints, discretion,
  acceptance criteria, work units, decisions) following docs/spec-contract.md and the
  discipline in docs/design-principles.md.
---

# Authoring a Doen spec

A spec is the source of truth that governs an executor. A good one lets an agent build the
right thing and lets a human verify it without reading diffs. The canonical format is in
`docs/spec-contract.md`; the discipline and rationale are in `docs/design-principles.md`.
Follow both. This skill is the procedure for producing one well.

## Process — shape, draft, correct

1. **Shape first.** If the request is thin on *intent*, the *constraint/discretion split*, or a
   *measurable definition of success*, ask only the few questions needed to fill those gaps —
   one at a time, not an interrogation. Do not invent intent.
2. **Draft** from `template.md` (in this skill folder). Copy it and fill every section.
3. **Present for correction.** The draft is a starting point; the human's edits are the real
   authoring. Flag any assumption you made inline so it's easy to reject.
4. **Write** the confirmed spec to `specs/NNNN-slug.md` (see Output below).

## How to fill each section

- **Intent** — one short paragraph in plain prose: the problem and the desired outcome. The
  human voice. Not a task list.
- **Constraints** — hard *must / must-not* lines the executor will not cross. Pull in the
  architecture invariants from CLAUDE.md that actually bind this feature, plus the scope fences
  for *this* work. Each a clear assertion.
- **Discretion** — explicit latitude: where the executor decides freely (naming, internal
  structure, UI specifics, library choices within constraints). The inverse of constraints.
- Constraints + discretion should **partition the decision space.** If a likely decision falls
  in neither and bears on intent, either pull it into one of them or record it under Decisions —
  never leave it for the agent to resolve silently.
- **Acceptance criteria** — how the work is judged. Make each *verifiable* and tag it
  `[test]` / `[behavior]` / `[metric]` / `[human_judgment]`. Avoid vague criteria. Mark the one
  that matters most as the HEADLINE.
- **Work units** — decompose into bounded, independently verifiable units; map each to the
  acceptance criteria it satisfies with `→`. Small enough to verify in one pass.
- **Decisions** — open product/intent calls needing the human. Each gets context, options, and
  your recommendation. Resolve nothing on intent by guessing.

## Hard rules

- **No estimation anywhere** — no story points, hours, or velocity.
- **Verifiable acceptance criteria only** — if you can't say how it's checked, it's not done.
- **Don't guess on intent** — raise a Decision instead.
- Keep it tight. A spec is a contract, not an essay.

## Output

- Write to `specs/NNNN-slug.md`. Choose the **next unused** 4-digit number — check `specs/`
  first, since some numbers are reserved by stubs (e.g. 0007).
- `slug` is a short kebab-case name from the title.
- Header fields: `initiative`, `stage`, `version` (start at `1`; `0` for an unshaped stub),
  and `depends on` if relevant.

> After the dogfood milestone (spec 0001, a6), specs live **inside Doen**, not in files. From
> that point, create the spec through Doen rather than writing to `specs/`.

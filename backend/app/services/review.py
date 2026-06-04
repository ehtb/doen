"""BD-14: Advisor-led verification synthesis.

When evidence is submitted against acceptance criteria, the Advisor performs a
preliminary per-criterion assessment before the human is asked to act. This keeps
the human in a correction-over-authoring role: they react to the Advisor's synthesis
rather than assembling judgment from raw evidence.

Stored inline on each criterion (advisor_preliminary_verdict + advisor_preliminary_notes)
and as a full synthesis on spec.verification_synthesis, which the frontend reads via
GET /specs/{initiative_id}.
"""

from __future__ import annotations

from typing import Any

from app.exceptions import NotFoundError
from app.models import AcceptanceCriterion, AdvisorVerdict, Spec
from app.providers.llm import LLMError, StructuredLLM, get_review_llm
from app.store import SpecStore

# Prompt evaluation harness: eval/promptfooconfig.yaml
VERIFICATION_SYNTHESIS_SYSTEM_PROMPT = """You are the Doen Advisor performing a \
preliminary verification review on submitted evidence.

For each criterion with submitted evidence, give a structured assessment using the \
exact format below. Use plain text — no markdown. Keep it short: your job is to \
reduce what the human must read, not add to it.

Verdict options:
  PASS           — evidence clearly satisfies the criterion
  NEEDS YOUR EYE — evidence is incomplete, raises a concern, or misses something
  BORDERLINE     — ambiguous; either verdict is defensible; human must decide

Format for PASS:
  PASS — [one-line reason]
  [optional: one bullet caveat starting with •, only if worth flagging]

Format for NEEDS YOUR EYE:
  NEEDS YOUR EYE — [one-line summary of the gap]

  Missing or concerning:
  • [specific gap — cite the criterion wording or evidence directly]
  • [additional gap if any]

  Your call: [one sentence framing what the human must decide]

Format for BORDERLINE:
  BORDERLINE — [one-line summary of the ambiguity]

  Supports passing:
  • [what the evidence does cover]

  Creates doubt:
  • [what the evidence doesn't cover or contradicts]

  Your call: [one sentence framing the judgment]

Rules:
• Use the exact verdict words above — they are rendered as labels.
• Don't re-quote the full criterion text — refer by key phrase only.
• Be specific: name the gap, the test that's missing, or the claim that's unverified.

Return every criterion you were given."""

VERIFICATION_SYNTHESIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "assessments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "criterion_id": {"type": "string"},
                    "verdict": {
                        "type": "string",
                        "enum": ["pass", "needs_your_eye", "borderline"],
                    },
                    "notes": {
                        "type": "string",
                        "description": (
                            "Specific detail for needs_your_eye and borderline. "
                            "A brief summary for pass."
                        ),
                    },
                },
                "required": ["criterion_id", "verdict", "notes"],
            },
        }
    },
    "required": ["assessments"],
}


def _build_verification_user_message(criteria: list[AcceptanceCriterion]) -> str:
    lines: list[str] = ["Criteria to assess:"]
    for c in criteria:
        lines.append(
            f"\n  criterion_id={c.id}\n"
            f"    text: {c.text}\n"
            f"    verify: [{c.verify.kind}] {c.verify.detail}\n"
            f"    evidence: {c.evidence or '(none submitted)'}"
        )
    return "\n".join(lines)


def _build_verification_synthesis(
    passed: list[AcceptanceCriterion],
    needs_eye: list[tuple[AcceptanceCriterion, str]],
    borderline: list[tuple[AcceptanceCriterion, str]],
) -> str:
    total = len(passed) + len(needs_eye) + len(borderline)
    if not total:
        return ""

    def _snippet(text: str) -> str:
        return '"' + text[:80].rstrip() + ("…" if len(text) > 80 else "") + '"'

    def _your_call(notes: str) -> str | None:
        for line in notes.split("\n"):
            stripped = line.strip()
            if stripped.startswith("Your call:"):
                return stripped[len("Your call:"):].strip()
        return None

    # Status header — quick scan of what needs attention
    parts: list[str] = []
    if passed:
        parts.append(f"{len(passed)} ready to approve")
    if needs_eye:
        parts.append(f"{len(needs_eye)} need{'s' if len(needs_eye) == 1 else ''} your eye")
    if borderline:
        parts.append(f"{len(borderline)} borderline")
    lines: list[str] = ["  ·  ".join(parts)]

    if needs_eye:
        lines.append("\nNeeds your eye:")
        for i, (c, notes) in enumerate(needs_eye):
            if i > 0:
                lines.append("")
            headline = notes.split("\n")[0].strip()
            your_call = _your_call(notes)
            lines.append(f"  {_snippet(c.text)}")
            lines.append(f"    {headline}")
            if your_call:
                lines.append(f"    → {your_call}")

    if borderline:
        lines.append("\nBorderline:")
        for i, (c, notes) in enumerate(borderline):
            if i > 0:
                lines.append("")
            headline = notes.split("\n")[0].strip()
            your_call = _your_call(notes)
            lines.append(f"  {_snippet(c.text)}")
            lines.append(f"    {headline}")
            if your_call:
                lines.append(f"    → {your_call}")

    return "\n".join(lines)


async def generate_verification_synthesis(
    store: SpecStore,
    initiative_id: str,
    *,
    llm: StructuredLLM | None = None,
) -> None:
    """BD-14: assess all evidence_submitted criteria and store preliminary verdicts.

    Non-fatal: if the LLM call fails, criteria are left without preliminary verdicts
    rather than blocking evidence submission. Reads and saves the spec in one round-trip."""
    spec = await store.get_spec(initiative_id)
    if spec is None:
        raise NotFoundError(f"no spec for initiative {initiative_id}")

    criteria_with_evidence = [
        c for c in spec.acceptance if c.verification_status == "evidence_submitted"
    ]
    if not criteria_with_evidence:
        return

    llm = llm or get_review_llm()
    try:
        raw = await llm.complete_structured(
            system=VERIFICATION_SYNTHESIS_SYSTEM_PROMPT,
            user=_build_verification_user_message(criteria_with_evidence),
            schema=VERIFICATION_SYNTHESIS_SCHEMA,
            schema_name="verify_criteria",
        )
    except Exception:
        return  # degraded but not blocking — evidence submission still succeeds

    assessment_map: dict[str, dict] = {
        a["criterion_id"]: a for a in raw.get("assessments", [])
    }

    passed: list[AcceptanceCriterion] = []
    needs_eye: list[tuple[AcceptanceCriterion, str]] = []
    borderline: list[tuple[AcceptanceCriterion, str]] = []

    for c in criteria_with_evidence:
        assessment = assessment_map.get(c.id)
        if assessment is None:
            c.advisor_preliminary_verdict = "needs_your_eye"
            c.advisor_preliminary_notes = "Not assessed — review manually"
            needs_eye.append((c, "Not assessed — review manually"))
            continue
        verdict: AdvisorVerdict = assessment.get("verdict", "needs_your_eye")
        notes: str = assessment.get("notes", "")
        c.advisor_preliminary_verdict = verdict
        c.advisor_preliminary_notes = notes
        if verdict == "pass":
            passed.append(c)
        elif verdict == "borderline":
            borderline.append((c, notes))
        else:
            needs_eye.append((c, notes))

    spec.verification_synthesis = _build_verification_synthesis(passed, needs_eye, borderline)
    await store.save_spec(spec)

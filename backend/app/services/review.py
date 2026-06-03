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

VERIFICATION_SYNTHESIS_SYSTEM_PROMPT = """You are the Doen Advisor performing a \
preliminary verification review on submitted evidence.

For each acceptance criterion with submitted evidence, assess the evidence and give a \
preliminary verdict:
- **pass**: The evidence clearly satisfies the criterion as written.
- **needs_your_eye**: The evidence is incomplete, doesn't fully address the criterion, \
or raises a concern the human should check. Explain specifically what needs attention.
- **borderline**: The evidence is ambiguous — you can read it as a pass or a fail. \
The human needs to make the call. Explain the ambiguity.

Be specific and actionable. The human reads your assessment before deciding their verdict — \
your job is to reduce how much raw evidence they need to read, not to make the decision for them.

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
    lines: list[str] = []
    total = len(passed) + len(needs_eye) + len(borderline)
    if not total:
        return ""

    if passed:
        n = len(passed)
        lines.append(f"{n} of {total} {'looks' if n == 1 else 'look'} like a clear pass.")
    if needs_eye:
        lines.append(f"\n{len(needs_eye)} need{'s' if len(needs_eye) == 1 else ''} your eye:")
        for c, notes in needs_eye:
            snippet = c.text[:80].rstrip() + ("…" if len(c.text) > 80 else "")
            lines.append(f"  • \"{snippet}\" — {notes}")
    if borderline:
        lines.append(f"\n{len(borderline)} borderline:")
        for c, notes in borderline:
            snippet = c.text[:80].rstrip() + ("…" if len(c.text) > 80 else "")
            lines.append(f"  • \"{snippet}\" — {notes}")
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

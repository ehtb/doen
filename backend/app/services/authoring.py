"""Spec-authoring service (spec 0002): add / confirm / edit / retire / confirm-all.

Every mutation reads the spec at the version the editor last saw, changes the doc, and
writes it back through the optimistic lock — so a stale edit is rejected rather than
silently clobbering a concurrent change. Framework-agnostic: raises domain exceptions
(app.exceptions), which the HTTP layer maps to status codes.
"""

from __future__ import annotations

from typing import Literal

from app.exceptions import ConflictError, NotFoundError, ValidationError
from app.models import AcceptanceCriterion, Section, Spec, SpecItem, Verify, _now
from app.store import SpecStore

_SECTIONS: tuple[Section, ...] = ("constraints", "discretion", "acceptance")

def _find_item(spec: Spec, item_id: str) -> SpecItem | None:
    for section in _SECTIONS:
        for it in getattr(spec, section):
            if it.id == item_id:
                return it
    return None


def _locate_item(spec: Spec, item_id: str) -> tuple[Section | None, SpecItem | None]:
    for section in _SECTIONS:
        for it in getattr(spec, section):
            if it.id == item_id:
                return section, it
    return None, None


async def _load_at(store: SpecStore, initiative_id: str, expected_version: int) -> Spec:
    spec = await store.get_spec(initiative_id)
    if spec is None:
        raise NotFoundError(f"no spec for initiative {initiative_id}")
    if spec.version != expected_version:
        raise ConflictError(
            f"stale version (spec is at v{spec.version}, you have v{expected_version})"
        )
    return spec


async def add_item(
    store: SpecStore,
    initiative_id: str,
    *,
    section: Section,
    text: str,
    version: int,
    verify: Verify | None,
    provenance: Literal["human", "ai_proposed"] = "human",
) -> Spec:
    """Add an item to the spec. A human authoring one is itself the act of confirmation
    (dec_726cb3ab8f15): it's born `human` + `confirmed`, governing immediately. Accepting one
    of the Advisor's proposal cards (0009 a3) instead lands it `ai_proposed` + `proposed` — a
    real spec item, but one the human still confirms via the normal flow before it governs
    (the Advisor never writes a governing item itself — 0009 constraint 4)."""
    if not text.strip():
        raise ValidationError("item text must not be empty")
    if section == "acceptance" and verify is None:
        raise ValidationError("an acceptance item needs a verify {kind, detail}")

    confirmed = provenance == "human"
    status: str = "confirmed" if confirmed else "proposed"
    confirmed_at = _now() if confirmed else None

    spec = await _load_at(store, initiative_id, version)
    if section == "acceptance":
        assert verify is not None  # guarded above
        item: SpecItem = AcceptanceCriterion(
            text=text, verify=verify,
            provenance=provenance, status=status, confirmed_at=confirmed_at,
        )
    else:
        item = SpecItem(
            text=text, provenance=provenance, status=status, confirmed_at=confirmed_at,
        )
    getattr(spec, section).append(item)
    return await store.save_spec(spec)


async def confirm_item(store: SpecStore, initiative_id: str, item_id: str, version: int) -> Spec:
    spec = await _load_at(store, initiative_id, version)
    it = _find_item(spec, item_id)
    if it is None:
        raise NotFoundError(f"no item {item_id} on this spec")
    if it.status != "proposed":
        raise ValidationError(f"only a proposed item can be confirmed (it is {it.status})")
    it.status = "confirmed"
    it.confirmed_at = _now()
    # Confirming the AI's exact wording records the human's endorsement in the provenance.
    if it.provenance == "ai_proposed":
        it.provenance = "ai_confirmed_by_human"
    return await store.save_spec(spec)


async def edit_item(
    store: SpecStore, initiative_id: str, item_id: str, *, text: str, version: int
) -> Spec:
    if not text.strip():
        raise ValidationError("item text must not be empty")
    spec = await _load_at(store, initiative_id, version)
    it = _find_item(spec, item_id)
    if it is None:
        raise NotFoundError(f"no item {item_id} on this spec")
    if it.status == "retired":
        raise ValidationError("cannot edit a retired item")
    # Editing the text is substantive: it reverts to `proposed` and must be re-confirmed
    # before it governs again (dec_557ca094fe3e). The human now owns the wording.
    it.text = text
    it.status = "proposed"
    it.confirmed_at = None
    it.provenance = "human"
    return await store.save_spec(spec)


async def retire_item(store: SpecStore, initiative_id: str, item_id: str, version: int) -> Spec:
    spec = await _load_at(store, initiative_id, version)
    it = _find_item(spec, item_id)
    if it is None:
        raise NotFoundError(f"no item {item_id} on this spec")
    if it.status == "retired":
        raise ValidationError("item is already retired")
    # Soft state: it stays in the document for history but no longer governs an executor.
    it.status = "retired"
    return await store.save_spec(spec)


async def reject_item(store: SpecStore, initiative_id: str, item_id: str, version: int) -> Spec:
    """Reject a proposed item (0011 C5/a6): remove it from the spec entirely. Per D1 -> c the
    spec stays a clean contract — the rejection isn't kept as a dimmed/retired row. Only a proposed
    item can be rejected; a confirmed item is governed and uses retire/edit instead. (The rejection
    used to be logged to the conversation rail as an advisor note; conversations are browser-local
    now — spec uvama — so the backend no longer writes that note.)"""
    spec = await _load_at(store, initiative_id, version)
    section, it = _locate_item(spec, item_id)
    if it is None or section is None:
        raise NotFoundError(f"no item {item_id} on this spec")
    if it.status != "proposed":
        raise ValidationError(f"only a proposed item can be rejected (it is {it.status})")
    getattr(spec, section).remove(it)
    return await store.save_spec(spec)


async def confirm_all(
    store: SpecStore, initiative_id: str, *, version: int, section: Section | None
) -> Spec:
    """Accept a draft in one gesture — confirm every proposed item at once, or just one
    section's. The common path: read the AI's draft, correct the exceptions (edit / retire),
    then confirm the rest as a batch instead of one micro-decision per item."""
    spec = await _load_at(store, initiative_id, version)
    sections = (section,) if section else _SECTIONS
    confirmed = 0
    for sec in sections:
        for it in getattr(spec, sec):
            if it.status == "proposed":
                it.status = "confirmed"
                it.confirmed_at = _now()
                if it.provenance == "ai_proposed":
                    it.provenance = "ai_confirmed_by_human"
                confirmed += 1
    if confirmed == 0:
        return spec  # nothing proposed; don't bump the version for a no-op
    return await store.save_spec(spec)

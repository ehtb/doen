"""u1 — spec authoring endpoints: confirm / add / edit / retire over save_spec.

Covers a1 (confirm transitions), a2 (human add), a3 (stale version -> 409),
a4 (retire soft-excludes from governing), the edit-reverts rule (dec_557ca094fe3e),
and a6 (a confirmation is visible on read-back — the MCP server reads the same store).
Integration tests over the real app; needs docker-compose Postgres + Redis.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from app.models import Spec


def _put_with_proposed(client: TestClient, iid: str) -> dict:
    """Seed a spec holding one ai_proposed constraint; return the saved spec (v1)."""
    body = {
        "initiative_id": iid, "title": "T", "version": 0,
        "constraints": [{"text": "ai says X", "provenance": "ai_proposed", "status": "proposed"}],
    }
    r = client.put(f"/specs/{iid}", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_add_item_is_human_and_confirmed(client: TestClient, make_initiative: Callable[[], str]):
    # a2 + D1 — a human-authored item is born human + confirmed (governs immediately).
    iid = make_initiative()
    spec = _put_with_proposed(client, iid)  # v1
    r = client.post(
        f"/specs/{iid}/items",
        json={"section": "constraints", "text": "human says Y", "version": spec["version"]},
    )
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["version"] == 2
    added = next(c for c in saved["constraints"] if c["text"] == "human says Y")
    assert added["provenance"] == "human"
    assert added["status"] == "confirmed"
    assert added["confirmed_at"] is not None


def test_accept_proposal_card_adds_ai_proposed_item(
    client: TestClient, make_initiative: Callable[[], str]
):
    # 0009 a3 — accepting the Advisor's proposal card adds the item via the SAME editing
    # endpoint, but born ai_proposed / proposed: a real spec item the human still confirms,
    # not a governing one (constraint 4).
    iid = make_initiative()
    spec = _put_with_proposed(client, iid)  # v1
    r = client.post(
        f"/specs/{iid}/items",
        json={
            "section": "constraints", "text": "Magic links expire in 15 minutes.",
            "version": spec["version"], "provenance": "ai_proposed",
        },
    )
    assert r.status_code == 200, r.text
    added = next(c for c in r.json()["constraints"] if c["text"].startswith("Magic links"))
    assert added["provenance"] == "ai_proposed"
    assert added["status"] == "proposed"          # does NOT govern yet
    assert added["confirmed_at"] is None
    # it then confirms through the normal flow (ai_proposed -> ai_confirmed_by_human)
    saved = r.json()
    c = client.post(
        f"/specs/{iid}/items/{added['id']}/confirm", json={"version": saved["version"]}
    )
    assert c.status_code == 200, c.text
    confirmed = next(x for x in c.json()["constraints"] if x["id"] == added["id"])
    assert confirmed["status"] == "confirmed" and confirmed["provenance"] == "ai_confirmed_by_human"


def test_add_acceptance_requires_verify(client: TestClient, make_initiative: Callable[[], str]):
    iid = make_initiative()
    spec = _put_with_proposed(client, iid)
    # acceptance without a verify -> 422 (and no write lands)
    r = client.post(
        f"/specs/{iid}/items",
        json={"section": "acceptance", "text": "must work", "version": spec["version"]},
    )
    assert r.status_code == 422
    # with a verify -> ok; human + confirmed
    r = client.post(
        f"/specs/{iid}/items",
        json={"section": "acceptance", "text": "must work", "version": spec["version"],
              "verify": {"kind": "test", "detail": "pytest"}},
    )
    assert r.status_code == 200, r.text
    acc = r.json()["acceptance"][0]
    assert acc["provenance"] == "human" and acc["status"] == "confirmed"
    assert acc["verify"]["kind"] == "test"


def test_confirm_flips_status_and_provenance(client: TestClient, make_initiative: Callable[[], str]):
    # a1 + a6 — confirming an ai_proposed item makes it govern, visible on a separate read.
    iid = make_initiative()
    spec = _put_with_proposed(client, iid)
    item_id = spec["constraints"][0]["id"]
    r = client.post(f"/specs/{iid}/items/{item_id}/confirm", json={"version": spec["version"]})
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["version"] == 2
    it = saved["constraints"][0]
    assert it["status"] == "confirmed"
    assert it["provenance"] == "ai_confirmed_by_human"
    assert it["confirmed_at"] is not None
    # a6 — a separate read sees it confirmed (the MCP server reads the same store)
    g = client.get(f"/specs/{iid}").json()
    assert g["constraints"][0]["status"] == "confirmed"


def test_confirm_only_proposed(client: TestClient, make_initiative: Callable[[], str]):
    iid = make_initiative()
    spec = _put_with_proposed(client, iid)
    item_id = spec["constraints"][0]["id"]
    assert client.post(f"/specs/{iid}/items/{item_id}/confirm", json={"version": 1}).status_code == 200
    # already confirmed -> 422
    assert client.post(f"/specs/{iid}/items/{item_id}/confirm", json={"version": 2}).status_code == 422


def test_edit_reverts_to_proposed(client: TestClient, make_initiative: Callable[[], str]):
    # dec_557ca094fe3e — editing a confirmed item's text reverts it to proposed.
    iid = make_initiative()
    spec = _put_with_proposed(client, iid)
    item_id = spec["constraints"][0]["id"]
    client.post(f"/specs/{iid}/items/{item_id}/confirm", json={"version": 1})  # -> v2, confirmed
    r = client.patch(f"/specs/{iid}/items/{item_id}", json={"text": "ai says X, refined", "version": 2})
    assert r.status_code == 200, r.text
    it = r.json()["constraints"][0]
    assert it["text"] == "ai says X, refined"
    assert it["status"] == "proposed"
    assert it["confirmed_at"] is None
    assert it["provenance"] == "human"


def test_stale_version_409(client: TestClient, make_initiative: Callable[[], str]):
    # a3 — an op built on a stale version is rejected; nothing from it lands.
    iid = make_initiative()
    spec = _put_with_proposed(client, iid)
    item_id = spec["constraints"][0]["id"]
    assert client.post(f"/specs/{iid}/items/{item_id}/confirm", json={"version": 1}).status_code == 200
    # a second op still claiming v1 is stale -> 409
    r = client.post(f"/specs/{iid}/items/{item_id}/retire", json={"version": 1})
    assert r.status_code == 409, r.text
    # the stale call left no trace: still confirmed at v2
    g = client.get(f"/specs/{iid}").json()
    assert g["version"] == 2
    assert g["constraints"][0]["status"] == "confirmed"


def test_retire_excludes_from_governing(client: TestClient, make_initiative: Callable[[], str]):
    # a4 — retire is soft: the item stays in the doc but no longer governs.
    iid = make_initiative()
    spec = _put_with_proposed(client, iid)
    item_id = spec["constraints"][0]["id"]
    client.post(f"/specs/{iid}/items/{item_id}/confirm", json={"version": 1})  # governs at v2
    r = client.post(f"/specs/{iid}/items/{item_id}/retire", json={"version": 2})
    assert r.status_code == 200, r.text
    saved = Spec.model_validate(r.json())
    assert saved.constraints[0].status == "retired"  # still present
    assert item_id not in [c.id for c in saved.confirmed_constraints()]  # no longer governs


def test_op_on_missing_item_404(client: TestClient, make_initiative: Callable[[], str]):
    iid = make_initiative()
    spec = _put_with_proposed(client, iid)
    assert client.post(
        f"/specs/{iid}/items/item_missing/confirm", json={"version": spec["version"]}
    ).status_code == 404


def test_confirm_all_batches_in_one_save(client: TestClient, make_initiative: Callable[[], str]):
    # Bulk confirm: accept the whole draft in one version bump; only proposed items flip.
    iid = make_initiative()
    body = {
        "initiative_id": iid, "title": "T", "version": 0,
        "constraints": [
            {"text": "c1", "provenance": "ai_proposed", "status": "proposed"},
            {"text": "c2", "provenance": "human", "status": "confirmed"},
        ],
        "discretion": [{"text": "d1", "provenance": "ai_proposed", "status": "proposed"}],
    }
    assert client.put(f"/specs/{iid}", json=body).status_code == 200  # v1

    r = client.post(f"/specs/{iid}/confirm-all", json={"version": 1})
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["version"] == 2  # one bump for the whole batch
    assert all(c["status"] == "confirmed" for c in saved["constraints"])
    assert saved["constraints"][0]["provenance"] == "ai_confirmed_by_human"  # was ai_proposed
    assert saved["constraints"][1]["provenance"] == "human"  # already confirmed, untouched
    assert saved["discretion"][0]["status"] == "confirmed"

    # idempotent no-op: nothing proposed -> no version bump
    r2 = client.post(f"/specs/{iid}/confirm-all", json={"version": 2})
    assert r2.status_code == 200
    assert r2.json()["version"] == 2


def test_confirm_all_scoped_to_one_section(client: TestClient, make_initiative: Callable[[], str]):
    # Per-section bulk confirm: only the named section's proposed items flip.
    iid = make_initiative()
    body = {
        "initiative_id": iid, "title": "T", "version": 0,
        "constraints": [{"text": "c1", "provenance": "ai_proposed", "status": "proposed"}],
        "discretion": [{"text": "d1", "provenance": "ai_proposed", "status": "proposed"}],
    }
    assert client.put(f"/specs/{iid}", json=body).status_code == 200  # v1

    r = client.post(f"/specs/{iid}/confirm-all", json={"version": 1, "section": "constraints"})
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["constraints"][0]["status"] == "confirmed"
    assert saved["discretion"][0]["status"] == "proposed"  # other section untouched


# --- 0011 a6 / D1 -> c: rejecting a proposed item deletes it + logs to the rail ---------
def test_reject_proposed_item_deletes_and_logs_to_rail(
    client: TestClient, make_initiative: Callable[[], str]
):
    iid = make_initiative()
    spec = _put_with_proposed(client, iid)  # v1, one ai_proposed constraint
    item = spec["constraints"][0]

    r = client.post(f"/specs/{iid}/items/{item['id']}/reject", json={"version": spec["version"]})
    assert r.status_code == 200, r.text
    after = r.json()
    # gone from the spec entirely (a clean contract, not a dimmed/retired row), version bumped
    assert after["version"] == spec["version"] + 1
    assert all(c["id"] != item["id"] for c in after["constraints"])

    # D1 -> c: the rejection is preserved in the conversation rail (the Advisor's history)
    msgs = client.get(f"/initiatives/{iid}/messages").json()
    assert any(
        m["role"] == "advisor" and "rejected" in m["content"] and item["text"] in m["content"]
        for m in msgs
    )


def test_reject_only_applies_to_proposed_items(
    client: TestClient, make_initiative: Callable[[], str]
):
    # a confirmed item is governed — it's retired/edited, never "rejected" (422); unknown -> 404
    iid = make_initiative()
    spec = _put_with_proposed(client, iid)  # v1
    item = spec["constraints"][0]
    confirmed = client.post(
        f"/specs/{iid}/items/{item['id']}/confirm", json={"version": spec["version"]}
    ).json()  # v2, now confirmed
    r = client.post(
        f"/specs/{iid}/items/{item['id']}/reject", json={"version": confirmed["version"]}
    )
    assert r.status_code == 422, r.text
    assert client.post(
        f"/specs/{iid}/items/nope/reject", json={"version": confirmed["version"]}
    ).status_code == 404

"""Acceptance coverage for u2: a1 (create/save), a2 (warm read), a3 (stale -> 409)."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient


def test_create_save_and_read(client: TestClient, make_initiative: Callable[[], str]):
    # a1 — a spec is created and saved (JSONB in PG, mirrored to Redis by the store).
    iid = make_initiative()
    body = {"initiative_id": iid, "title": "Test spec", "intent": "why", "version": 0}

    r = client.put(f"/specs/{iid}", json=body)
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["version"] == 1  # 0 (unsaved) -> 1 on first write
    assert saved["initiative_id"] == iid

    # a2 — the whole spec comes back in one call.
    g = client.get(f"/specs/{iid}")
    assert g.status_code == 200
    assert g.json()["title"] == "Test spec"


def test_warm_read_served_from_redis(
    client: TestClient,
    make_initiative: Callable[[], str],
    delete_spec_row: Callable[[str], None],
):
    # a2 — warm reads come from Redis: delete the PG row, the read still succeeds.
    iid = make_initiative()
    body = {"initiative_id": iid, "title": "Cached", "version": 0}
    assert client.put(f"/specs/{iid}", json=body).status_code == 200

    delete_spec_row(iid)  # source of truth gone; only the cache entry remains

    g = client.get(f"/specs/{iid}")
    assert g.status_code == 200, "expected the cached spec to be served from Redis"
    assert g.json()["title"] == "Cached"


def test_stale_version_conflicts(client: TestClient, make_initiative: Callable[[], str]):
    # a3 — saving on a stale version raises StaleSpecError -> HTTP 409.
    iid = make_initiative()
    body = {"initiative_id": iid, "title": "T", "version": 0}

    assert client.put(f"/specs/{iid}", json=body).status_code == 200  # now at v1

    # second write still claims v0 — stale.
    r = client.put(f"/specs/{iid}", json=body)
    assert r.status_code == 409, r.text


def test_get_missing_spec_is_404(client: TestClient, make_initiative: Callable[[], str]):
    iid = make_initiative()  # initiative exists, but no spec saved yet
    assert client.get(f"/specs/{iid}").status_code == 404

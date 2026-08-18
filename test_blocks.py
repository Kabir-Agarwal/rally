"""Prod-safe delivery checks (SPEC Y1) — feature-block registry + dummy-screen rendering.

blocks.py stages every feature-block off -> dummy -> live. This proves the guarantees that make
delivery safe: (1) the registry is consistent, (2) the five shipped tabs still serve — adding
blocks never breaks prod, (3) a block flipped to `dummy` renders a placeholder screen at /<id>
and is injected into the client, (4) an `off`/unknown block 404s instead of leaking a broken page.
"""
import blocks
from conftest import app_client   # noqa: F401  (pytest fixture)


def test_registry_valid():
    assert blocks.validate() is True


def test_shipped_tabs_stay_live():
    live = {b["id"] for b in blocks.REGISTRY if b["state"] == "live"}
    assert set(blocks.CORE) <= live


def test_validate_rejects_a_disabled_shipped_tab():
    live = next(b for b in blocks.REGISTRY if b["id"] == "live")
    old = live["state"]
    live["state"] = "off"
    try:
        try:
            blocks.validate()
            assert False, "validate() should reject a shipped tab that is not live"
        except ValueError:
            pass
    finally:
        live["state"] = old


def test_live_tabs_still_serve(app_client):
    for tab in ("", "live", "leaderboard", "log", "groups", "history"):
        assert app_client.get("/" + tab).status_code == 200   # prod never breaks


def test_dummy_block_renders_and_injects(app_client):
    b = next(x for x in blocks.REGISTRY if x["id"] == "tournaments")
    old = b["state"]
    b["state"] = "dummy"
    try:
        r = app_client.get("/tournaments")
        assert r.status_code == 200
        assert 'data-tab="tournaments"' in r.text          # dummy nav tab rendered server-side
        assert r.text.count("tournaments") >= 2            # nav button + window.DUMMY_BLOCKS payload
    finally:
        b["state"] = old


def test_off_and_unknown_blocks_404(app_client):
    off = next(b["id"] for b in blocks.REGISTRY if b["state"] == "off")   # e.g. messages/feed/orgs
    assert app_client.get("/" + off).status_code == 404    # declared but still `off`
    assert app_client.get("/nope").status_code == 404      # unknown segment

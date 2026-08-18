"""Theme lock check (SPEC Y2 — KEEP theme).

Proves the approved CLAY palette can't silently regress as Y3 features land: the live
static/style.css :root matches the frozen lock, and a recoloured or dropped token is caught.
"""
import pytest
import theme


def _bad_css(tmp_path, css):
    p = tmp_path / "style.css"
    p.write_text(css, encoding="utf-8")
    return str(p)


def test_live_css_matches_the_lock():
    assert theme.check() is True                       # the real guard: prod CSS == frozen palette


def test_lock_is_the_whole_root_palette():
    with open(theme.CSS, encoding="utf-8") as f:
        live = theme.root_tokens(f.read())
    assert set(live) == set(theme.TOKENS)              # lock stays complete — no unfrozen token


def test_recolour_is_caught(tmp_path):
    with open(theme.CSS, encoding="utf-8") as f:
        css = f.read().replace("--clay:#A94E2F", "--clay:#000000")
    with pytest.raises(ValueError):
        theme.check(_bad_css(tmp_path, css))


def test_dropped_token_is_caught(tmp_path):
    with open(theme.CSS, encoding="utf-8") as f:
        css = f.read().replace("--gold:#E9B949;", "")
    with pytest.raises(ValueError):
        theme.check(_bad_css(tmp_path, css))


def test_case_only_change_is_fine(tmp_path):
    with open(theme.CSS, encoding="utf-8") as f:
        css = f.read().replace("--clay:#A94E2F", "--clay:#a94e2f")
    assert theme.check(_bad_css(tmp_path, css)) is True  # same colour, reformatted — not a regression

"""Theme lock — the approved CLAY palette, frozen so it can't silently regress (SPEC Y2).

Y2 KEEP: theme. Rally is LIVE and Y3 features land block by block; nearly every one of them edits
static/style.css. This freezes the design tokens (the :root custom properties) at their approved
values, so a later feature block can't drop or recolour the palette by accident.

check() reads static/style.css, extracts the :root tokens, and fails loud if the live palette
drifts from the lock — same shape as blocks.validate(), wired into the same deploy.py preflight,
so "keep the theme" is enforced, not hoped for. A dropped token, a changed value, or a NEW :root
token that isn't in the lock all abort: any palette change has to be a deliberate edit here.
"""
import os
import re

CSS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "style.css")

# The approved CLAY theme — static/style.css :root, matching the approved mockup (docs/mockup-v9.jsx,
# "Palette/tokens already match" per docs/drift-inventory.md). A change HERE is a conscious
# re-approval of the palette; a change only in the CSS is a regression check() rejects.
TOKENS = {
    "clay": "#A94E2F", "clay-deep": "#7C371F", "sand": "#F6F0E9", "cream": "#FFFDF9",
    "ink": "#2B211C", "muted": "#8A7B70", "yellow": "#D6ED17", "line": "#EADFD2",
    "team1": "#C86A45", "team2": "#8A3B22", "live": "#2FB36B", "gold": "#E9B949",
    "radius": "16px",
}


def root_tokens(css_text):
    """Custom properties declared in any :root{...} block, name->value (CSS cascade: last wins)."""
    out = {}
    for block in re.findall(r":root\s*\{([^}]*)\}", css_text):
        for name, val in re.findall(r"--([\w-]+)\s*:\s*([^;]+);", block):
            out[name] = val.strip()
    return out


def check(css_path=CSS):
    """Fail loud if static/style.css :root drifts from the frozen theme lock (deploy.py preflight)."""
    with open(css_path, encoding="utf-8") as f:
        live = root_tokens(f.read())
    bad = []
    for name, want in TOKENS.items():
        got = live.get(name)
        if got is None:
            bad.append(f"--{name} dropped from :root (theme lock wants {want!r})")
        elif got.lower() != want.lower():   # colours compare case-insensitively; a real value change still bites
            bad.append(f"--{name} is {got!r}, theme lock wants {want!r}")
    extra = sorted(set(live) - set(TOKENS))
    if extra:
        bad.append(f"new :root token(s) not in the lock: {extra} — add them to theme.TOKENS to approve")
    if bad:
        raise ValueError("theme drift:\n  " + "\n  ".join(bad))
    return True


if __name__ == "__main__":
    check()
    print("theme OK:", ", ".join(f"--{k}={v}" for k, v in TOKENS.items()))

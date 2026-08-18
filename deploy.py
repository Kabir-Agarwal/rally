"""Deploy Rally to Vercel production by file upload (the repo is NOT git-connected).

Usage:  VERCEL_TOKEN=... python deploy.py
The token comes ONLY from the environment — never hard-code it here or commit it anywhere.

Uploads every git-tracked file PLUS static/mockup-v9.jsx (served live from /static/), then
polls the deployment until READY.
"""
import os
import sys
import json
import time
import base64
import subprocess
import urllib.request
import urllib.error

TOKEN = os.environ.get("VERCEL_TOKEN")
if not TOKEN:
    print("ERROR: set VERCEL_TOKEN in the environment.")
    sys.exit(1)

TEAM = "team_0zE1g36I2GS0ssWZe00gnSkK"
PROJECT_NAME = "rally-scorer"
BASE = os.path.dirname(os.path.abspath(__file__))
API = "https://api.vercel.com"
HDR = {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"}


def _read(local):
    with open(os.path.join(BASE, local), "rb") as f:
        return f.read()


def _b64(b):
    return base64.b64encode(b).decode()


def collect_files():
    tracked = subprocess.check_output(["git", "ls-files"], cwd=BASE, text=True).split()
    # The live app serves the approved design at /static/mockup-v9.jsx; ship it there.
    extra = [("static/mockup-v9.jsx", "docs/mockup-v9.jsx")]
    files = []
    for rel in tracked:
        p = os.path.join(BASE, rel)
        if os.path.isfile(p):
            files.append({"file": rel, "data": _b64(_read(rel)), "encoding": "base64"})
    for dep_path, local in extra:
        if os.path.exists(os.path.join(BASE, local)):
            files.append({"file": dep_path, "data": _b64(_read(local)), "encoding": "base64"})
    return files


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=HDR, method="POST")
    try:
        return json.loads(urllib.request.urlopen(req, timeout=120).read())
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read().decode()[:1000])
        raise


def get(url):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + TOKEN})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def preflight():
    """Prod-safe gate (SPEC Y1): never upload a build that can't boot, whose feature-block registry
    is inconsistent, or that regresses the approved theme, doubles chemistry, delete-past-matches or
    earned-from-0 card stats (SPEC Y2). Importing app runs db.init_db (fails loud if unmigrated); the
    block registry, theme palette, the pair-rating contract, the soft-delete contract and the card
    payload are validated. Any failure aborts the deploy before a single file is uploaded."""
    import importlib
    import blocks
    import theme
    import chemistry
    import deletion
    import cardstats
    import tournaments
    import leagues
    blocks.validate()
    theme.check()                    # SPEC Y2 KEEP theme: abort if static/style.css :root drifted
    chemistry.check()                # SPEC Y2 KEEP doubles chemistry: abort if the pair contract regressed
    deletion.check()                 # SPEC Y2 KEEP delete-past-matches: abort if soft delete / rollback regressed
    cardstats.check()                # SPEC Y2 KEEP earned-from-0 card stats: abort if the card is seeded / mis-counted
    tournaments.check()              # SPEC Y3 ADD tournaments: abort if the bracket engine (4–32, BYEs, live) regressed
    leagues.check()                  # SPEC Y3 ADD round-robin leagues: abort if the schedule/standings engine regressed
    importlib.import_module("app")   # boot check: raises if the app can't construct
    print("preflight OK")


def main():
    preflight()
    files = collect_files()
    print(f"uploading {len(files)} files…")
    body = {
        "name": PROJECT_NAME,
        "target": "production",
        "files": files,
        "projectSettings": {"framework": None},
    }
    dep = post(f"{API}/v13/deployments?forceNew=1&teamId={TEAM}", body)
    dep_id = dep.get("id")
    print("deployment id:", dep_id, "| initial:", dep.get("readyState"))
    poll = f"{API}/v13/deployments/{dep_id}?teamId={TEAM}"
    st = dep.get("readyState")
    for _ in range(150):
        r = get(poll)
        st = r.get("readyState")
        if st in ("READY", "ERROR", "CANCELED"):
            print("FINAL:", st, "| url:", r.get("url"))
            break
        time.sleep(3)
    else:
        print("timed out waiting; last state:", st)
    if st != "READY":
        sys.exit(2)


if __name__ == "__main__":
    main()

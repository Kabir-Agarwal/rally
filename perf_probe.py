"""Measure per-request latency against a running Rally (default: production).

Why this exists: the 2026-07-28 latency work was driven by measurement, not guesswork, and the
"after" numbers have to be taken the same way as the "before" numbers to be comparable. Run this
after a deploy and diff it against the numbers recorded in CONTEXT.md.

    python perf_probe.py                            # production
    python perf_probe.py http://127.0.0.1:7860      # local
    python perf_probe.py <base> <reps>

What the two columns mean:
  no-auth  no Authorization header -> verify_token() returns None immediately, so NO Supabase
           token-verification round trip happens. This is the DB/serverless cost alone.
  bad-tok  a syntactically-real but bogus bearer token -> _verify_supabase() DOES make the round
           trip (and then rejects it). bad-tok minus no-auth isolates the cost of verifying a
           token, which used to be paid on EVERY authenticated request.

A real signed-in user pays the auth cost PLUS more queries than the no-auth path (their player
row, their groups, their friendships), so treat no-auth as a floor, not as user-visible latency.

IMPORTANT — what this probe can and cannot show after the verification cache landed:
  * The cache only ever stores CONFIRMED tokens; rejections are never cached. bad-tok is rejected,
    so the `delta` column keeps showing the FULL round-trip cost on every run. That is the point:
    delta measures what one verification costs, which is the thing the cache avoids paying
    repeatedly. It is NOT a measure of the improvement.
  * To see the user-visible improvement you need a REAL, valid token (a signed-in session): hit
    /api/me twice within AUTH_VERIFY_TTL and compare. The first call pays the round trip, the
    second should not. A browser DevTools timing on two consecutive Live polls shows the same thing.
"""
from __future__ import annotations
import json
import statistics
import sys
import time
import urllib.error
import urllib.request

PATHS = [
    ("/static/style.css", "static file: pure network + edge baseline"),
    ("/api/auth/config", "python endpoint, no DB, no auth"),
    ("/api/me", "1 query + auth"),
    ("/api/live", "live feed"),
    ("/api/leaderboard", "ranks"),
]
# Shaped like a real JWT (header.payload.signature) but signed by nobody, so it is never a
# "mock." token and therefore takes the real Supabase verification path.
BAD_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJwcm9iZSIsImV4cCI6NDA3MDkwODgwMH0.notarealsignature"


def timed(url: str, token: str | None, timeout: int = 40):
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
            code = r.status
    except urllib.error.HTTPError as e:
        e.read()
        code = e.code
    except Exception:
        return None, "ERR"
    return time.perf_counter() - t0, code


def main():
    base = (sys.argv[1] if len(sys.argv) > 1 else "https://rally-scorer.vercel.app").rstrip("/")
    reps = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    print(f"base={base}  reps={reps}  (first call per row discarded: never report a cold start)\n")
    print(f"{'path':<22}{'no-auth':>10}{'bad-tok':>10}{'delta':>10}   note")
    print("-" * 78)
    out = {}
    for path, note in PATHS:
        url = base + path
        med = {}
        for label, tok in (("noauth", None), ("badtok", BAD_TOKEN)):
            timed(url, tok)                                   # warm-up, discarded
            samples = []
            for _ in range(reps):
                dt, code = timed(url, tok)
                if dt is not None:
                    samples.append(dt)
            med[label] = statistics.median(samples) if samples else float("nan")
        delta = med["badtok"] - med["noauth"]
        out[path] = {"noauth_s": round(med["noauth"], 3), "badtok_s": round(med["badtok"], 3),
                     "auth_delta_s": round(delta, 3)}
        print(f"{path:<22}{med['noauth']:>9.3f}s{med['badtok']:>9.3f}s{delta:>9.3f}s   {note}")
    print("\ndelta = cost of one Supabase token-verification round trip on that request.")
    print("With the verification cache (auth.AUTH_VERIFY_TTL) only the first request in the")
    print("window pays it; without the cache every authenticated request did.\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()

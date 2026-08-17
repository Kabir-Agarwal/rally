"""Free-tier headroom check for Rally going public (SPEC Y7).

Answers ONE question with a runnable model: does public traffic outgrow the Vercel
Hobby + Supabase Free tiers, and on WHICH resource first? This is a findings model,
not a billing simulator — the inputs are order-of-magnitude, but the *ranking* of
which limit binds first is robust across any sane input.

The whole result turns on one fact about Rally: Live views poll `/api/live` and
`/api/match/<id>` every 3 seconds (README "Screens"), and `vercel.json` rewrites every
dynamic path to ONE catch-all function (`api/index.py`). So each poll = 1 Vercel
function invocation + one Supabase egress payload. Polling, not data, is the cost.

Free-tier limits (verified via vendor-pricing writeups, 2026-08-18):
  Vercel Hobby : 1,000,000 function invocations / mo ; 100 GB fast data transfer / mo ;
                 pauses (no overage billing) at the cap ; PERSONAL / NON-COMMERCIAL only.
  Supabase Free: 500 MB database ; 5 GB egress / mo ; 50,000 MAU ; pauses after 7 days idle.

Run:  python freetier_check.py     (prints the table, then self-checks with asserts)
"""

# --- free-tier caps (the numbers a cost card would be measured against) ---
VERCEL_INVOCATIONS = 1_000_000     # per month
VERCEL_TRANSFER_GB = 100           # per month
SUPABASE_EGRESS_GB = 5             # per month
SUPABASE_DB_MB = 500

# --- Rally's request model ---
POLL_SECONDS = 3                   # Live + match pages poll every 3s
SECONDS_PER_MONTH = 30 * 24 * 3600 # 2,592,000
POLL_RESP_KB = 8                   # ponytail: est. /api/live JSON (players+sets+win_prob);
                                   # finding holds from ~1 KB up — see the assert below.
MATCH_ROW_KB = 1                   # a match + its sets + players, roughly


def monthly(avg_live_tabs, endpoints_per_tab=2, poll_seconds=POLL_SECONDS, resp_kb=POLL_RESP_KB):
    """Monthly (invocations, egress_GB) for `avg_live_tabs` continuously-polling live tabs.

    A live *match* page polls 2 endpoints (/api/live + /api/match/<id>); the Live *home*
    polls 1. `avg_live_tabs` is the month-averaged count of such open, visible tabs
    (hidden tabs pause polling), so 1.0 == one tab open and watching all month.
    """
    polls = avg_live_tabs * (SECONDS_PER_MONTH / poll_seconds) * endpoints_per_tab
    return polls, polls * resp_kb / 1_000_000   # 1 GB = 1,000,000 KB (decimal, as vendors bill)


def verdict(avg_live_tabs, **kw):
    """Which free-tier caps a scenario blows through. Empty list == fits free."""
    inv, egr = monthly(avg_live_tabs, **kw)
    over = []
    if inv > VERCEL_INVOCATIONS:
        over.append(f"Vercel invocations ({inv/VERCEL_INVOCATIONS:.1f}x cap)")
    if egr > SUPABASE_EGRESS_GB:
        over.append(f"Supabase egress ({egr/SUPABASE_EGRESS_GB:.1f}x cap)")
    if egr > VERCEL_TRANSFER_GB:
        over.append(f"Vercel transfer ({egr/VERCEL_TRANSFER_GB:.1f}x cap)")
    return over


def db_match_capacity():
    """How many matches fit in the 500 MB DB — to show DB size is NOT the binding limit."""
    return SUPABASE_DB_MB * 1000 // MATCH_ROW_KB   # MB -> KB / KB-per-match


SCENARIOS = [
    ("friend-group today", 0.02, 2),   # a match watched now and then; near-empty DB
    ("one dedicated live tab", 1.0, 2),  # a single always-open live match page
    ("public: ~10 live tabs", 10.0, 2),  # modest public concurrency
]


def report():
    print(f"Rally free-tier headroom - poll={POLL_SECONDS}s, resp~{POLL_RESP_KB}KB, "
          f"{SECONDS_PER_MONTH//86400}-day month\n")
    print(f"{'scenario':<26}{'invocations/mo':>16}{'egress GB/mo':>14}  verdict")
    for name, tabs, eps in SCENARIOS:
        inv, egr = monthly(tabs, endpoints_per_tab=eps)
        v = verdict(tabs, endpoints_per_tab=eps)
        print(f"{name:<26}{inv:>16,.0f}{egr:>14.2f}  "
              f"{'FITS free' if not v else 'OVER: ' + '; '.join(v)}")
    print(f"\ncaps: Vercel {VERCEL_INVOCATIONS:,} invocations & {VERCEL_TRANSFER_GB} GB; "
          f"Supabase {SUPABASE_EGRESS_GB} GB egress & {SUPABASE_DB_MB} MB db")
    print(f"DB holds ~{db_match_capacity():,} matches before 500 MB - not the binding limit.")


def _selfcheck():
    # 1) The headline: ONE always-open live-match tab alone exceeds the free monthly
    #    invocation budget. Public (many tabs) therefore cannot fit.
    inv1, egr1 = monthly(1.0)
    assert inv1 > VERCEL_INVOCATIONS, inv1
    assert egr1 > SUPABASE_EGRESS_GB, egr1

    # 2) Friend-group scale fits comfortably (real headroom exists TODAY).
    assert verdict(0.02) == [], "friend-group scale should fit the free tier"

    # 3) Public scale does not fit, and the FIRST binding limit is polling
    #    (invocations/egress), never DB size — matches are tiny and rebuilt on read.
    assert verdict(10.0), "public scale must outgrow the free tier"
    assert db_match_capacity() > 100_000, "DB is not the constraint; it holds 100k+ matches"

    # 4) The free mitigation works IN the model: 10x the poll interval => 1/10 the
    #    invocations. Dropping 3s -> 30s pulls one dedicated tab back under the cap.
    inv_30s, _ = monthly(1.0, poll_seconds=30)
    assert abs(inv_30s * 10 - inv1) < 1, (inv_30s, inv1)
    assert inv_30s < VERCEL_INVOCATIONS, "30s polling keeps one live tab within free invocations"

    # 5) Finding is robust to the response-size guess: even at 1 KB/poll, one always-open
    #    tab still blows invocations (egress just binds a bit later).
    _, egr_1kb = monthly(1.0, resp_kb=1)
    assert monthly(1.0, resp_kb=1)[0] > VERCEL_INVOCATIONS
    assert egr_1kb < egr1


if __name__ == "__main__":
    report()
    _selfcheck()
    print("\nself-check OK - public traffic outgrows the free tier; see STATUS.md cost card.")

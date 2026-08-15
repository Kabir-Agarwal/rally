# SPEC RALLY

Y1 LIVE app — prod never breaks; features land block by block; dummy UI on new screens.
Y2 KEEP: theme, doubles chemistry, delete-past-matches, earned-from-0 card stats. SKIP: self-rating slider onboarding.
Y3 ADD: tournaments (4–32 draws, BYEs, live brackets); round-robin leagues; practice-vs-rated split; competitions hub (Create/Manage/In-Queue/Scheduled); nearby players (50km + Connect); messenger + basic AI helper; highlights (landscape video upload, reputation stars, laurels); posts feed + followed players' matches; org/club accounts; public layer — privacy controls, block/report, location-permission handling, 16+ gate.
Y4 Numbers: TWO, separate — Elo-style skill rating on the FIFA card + activity/reputation form count.
Y5 Migrations: batched — one migrations\block-N.sql per feature-block → ONE planned ✋ → owner's chat-Claude applies via Supabase MCP → continue. No session ever applies schema.
Y6 Video tool: laptop-only processing; only stats JSON + highlight clips upload; Stage-0 accuracy test runs inside item #0 before any deeper vision work; post-video camera/tripod guidance; max stats.
Y7 Item #0: re-study current Playeri for new steal-worthy features; verify Vercel/Supabase free-tier headroom for public traffic (outgrowing free → cost card ✋).
OUT: live streaming (v2), advanced messenger AI, payments, mobile.

## Repo facts verified at bootstrap (14 Aug 2026)

- tennis-scores: `C:\Users\LENOVO\Desktop\tennis-scores`, remote `https://github.com/Kabir-Agarwal/rally.git` (PUBLIC), branch `master`, HEAD at bootstrap `ae7ad4e`. This is the LIVE app. Public repo → secret scan is mandatory before any push.
- tennis-video-analysis: never existed — it was always a plan to merge onto Rally, not a repo. The bootstrap WAITING-OWNER card is CLOSED by the owner's ruling below.

## Y6 RULING — owner, 14 Aug 2026 (binding; overrides the bootstrap card)

- BUILD Y6 FRESH inside the Rally work from free open-source vision libraries.
- Do NOT create a separate repo. Do NOT park Y6 as blocked.
- Y6 stays LAST within Rally: it needs the match pages (Y1–Y5) to exist first.
- Tier 1 now: rally segmentation, rally counts/lengths, highlight reel, movement heatmaps.
- Tier 2 only after the owner's real Stage-0 clip validates. Tier 3 far off.
- Proceed with Y1–Y5 and Y7 immediately.
- Money wall still applies: free open-source vision libraries only; anything paid → cost card ✋.

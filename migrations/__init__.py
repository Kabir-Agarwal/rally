# migrations is a package so deploy.py preflight can `from migrations import check_migrations`.
# The .sql files are owner-applied via the Supabase MCP — never by a build session (SPEC Y5).

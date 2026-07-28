"""Cross-dialect schema mirror for Rally (clean foundation). The LIVE Postgres schema is owned by
the migrations (rally_clean_foundation); this metadata exists so tests can compile it for the
Postgres dialect and a drift guard can check it stays in sync with db.SCHEMA (the SQLite string).
uuid columns are Text here (portable); the real PG columns are uuid.
"""
from sqlalchemy import MetaData, Table, Column, Integer, Text

metadata = MetaData()

players = Table(
    "players", metadata,
    Column("id", Text, primary_key=True),
    Column("code", Text, nullable=False, unique=True),
    Column("game_name", Text, nullable=False),
    Column("real_name", Text),
    Column("created_at", Text, nullable=False),
    Column("password_hash", Text),
)

groups = Table(
    "groups", metadata,
    Column("id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("code", Text, nullable=False, unique=True),
    Column("is_public", Integer, nullable=False, server_default="1"),
    Column("admin_id", Text),
    Column("created_at", Text, nullable=False),
)

group_members = Table(
    "group_members", metadata,
    Column("group_id", Text, primary_key=True),
    Column("player_id", Text, primary_key=True),
    Column("joined_at", Text, nullable=False),
)

group_join_requests = Table(
    "group_join_requests", metadata,
    Column("group_id", Text, primary_key=True),
    Column("player_id", Text, primary_key=True),
    Column("created_at", Text, nullable=False),
)

matches = Table(
    "matches", metadata,
    Column("id", Text, primary_key=True),
    Column("group_id", Text),
    Column("former_group_name", Text),
    Column("kind", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="live"),
    Column("logger_id", Text),
    Column("created_at", Text),
    Column("started_at", Text),
    Column("finished_at", Text),
)

match_players = Table(
    "match_players", metadata,
    Column("match_id", Text, primary_key=True),
    Column("player_id", Text, primary_key=True),
    Column("side", Integer, nullable=False),
    Column("rotation_pos", Integer),
)

match_sets = Table(
    "match_sets", metadata,
    Column("match_id", Text, primary_key=True),
    Column("set_no", Integer, primary_key=True),
    Column("games_side1", Integer, nullable=False, server_default="0"),
    Column("games_side2", Integer, nullable=False, server_default="0"),
)

point_logs = Table(
    "point_logs", metadata,
    Column("match_id", Text, primary_key=True),
    Column("seq", Integer, primary_key=True),
    Column("winner_side", Integer, nullable=False),
    Column("server_player_id", Text),
    Column("point_winner_player_id", Text),
)

tt_games = Table(
    "tt_games", metadata,
    Column("match_id", Text, primary_key=True),
    Column("game_no", Integer, primary_key=True),
    Column("round_no", Integer),
    Column("server_player_id", Text),
    Column("receiver_player_id", Text),
    Column("winner_player_id", Text),
)

friendships = Table(
    "friendships", metadata,
    Column("a_id", Text, primary_key=True),
    Column("b_id", Text, primary_key=True),
    Column("status", Text, nullable=False, server_default="pending"),
    Column("requested_by", Text, nullable=False),
    Column("created_at", Text, nullable=False),
)

name_history = Table(
    "name_history", metadata,
    Column("player_id", Text, nullable=False),
    Column("old_name", Text, nullable=False),
    Column("changed_at", Text, nullable=False),
)

approvals = Table(
    "approvals", metadata,
    Column("match_id", Text, primary_key=True),
    Column("player_id", Text, primary_key=True),
    Column("action", Text, nullable=False),
    Column("reason", Text),
    Column("approved_at", Text),
)

freeze_requests = Table(
    "freeze_requests", metadata,
    Column("match_id", Text, primary_key=True),
    Column("player_id", Text, primary_key=True),
    Column("kind", Text, primary_key=True),
    Column("approved_at", Text),
)

admin_log = Table(
    "admin_log", metadata,
    Column("id", Integer, primary_key=True),
    Column("at", Text, nullable=False),
    Column("action", Text, nullable=False),
    Column("target", Text),
)

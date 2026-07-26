"""Cross-dialect schema for Rally, defined once with SQLAlchemy Core.

Used to create tables on Postgres (via DATABASE_URL) and to prove the schema compiles
for the Postgres dialect in tests. The SQLite path still bootstraps from db.SCHEMA (the
raw string the in-memory test helpers depend on); a drift-guard test keeps the two in
sync (same tables + columns). Case-insensitive player-name uniqueness is expressed here
as a functional unique index on lower(name), which compiles on both dialects.
"""
from sqlalchemy import (
    MetaData, Table, Column, Integer, Text, Index, func,
)

metadata = MetaData()

groups = Table(
    "groups", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", Text, nullable=False),
    Column("code", Text, nullable=False, unique=True),
    Column("is_public", Integer, nullable=False, server_default="0"),
    Column("created_at", Text, nullable=False),
    Column("ratings_rev", Integer, nullable=False, server_default="0"),
)

players = Table(
    "players", metadata,
    Column("id", Integer, primary_key=True),
    Column("group_id", Integer, nullable=False),
    Column("name", Text, nullable=False),        # game name
    Column("real_name", Text),                   # optional real name (subtext)
    Column("created_at", Text, nullable=False),
    Column("code", Text),                        # permanent public player code (Name#CODE)
    Column("auth_id", Text),                     # immutable identity = auth.users(id)
    Column("password_set", Integer, nullable=False, server_default="0"),  # 1 once a password is set
)
# case-insensitive uniqueness per group (mirrors "UNIQUE(group_id, name COLLATE NOCASE)")
Index("ux_players_group_lower_name", players.c.group_id, func.lower(players.c.name), unique=True)

matches = Table(
    "matches", metadata,
    Column("id", Integer, primary_key=True),
    Column("group_id", Integer, nullable=False),
    Column("played_on", Text),
    Column("kind", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("logger_player_id", Integer),
    Column("created_at", Text),
    Column("started_at", Text),
    Column("finished_at", Text),
    Column("voided", Integer, nullable=False, server_default="0"),
    Column("deleted", Integer, nullable=False, server_default="0"),
)

match_players = Table(
    "match_players", metadata,
    Column("match_id", Integer, nullable=False),
    Column("player_id", Integer, nullable=False),
    Column("side", Integer, nullable=False),
    Column("rotation_pos", Integer),
)

match_sets = Table(
    "match_sets", metadata,
    Column("match_id", Integer, nullable=False),
    Column("set_no", Integer, nullable=False),
    Column("games_side1", Integer, nullable=False, server_default="0"),
    Column("games_side2", Integer, nullable=False, server_default="0"),
)

tt_games = Table(
    "tt_games", metadata,
    Column("match_id", Integer, nullable=False),
    Column("game_no", Integer, nullable=False),
    Column("server_player_id", Integer),
    Column("receiver_player_id", Integer),
    Column("winner_player_id", Integer),
)

point_logs = Table(
    "point_logs", metadata,
    Column("match_id", Integer, nullable=False),
    Column("seq", Integer, nullable=False),
    Column("winner_side", Integer, nullable=False),
    Column("server_player_id", Integer),
)

approvals = Table(
    "approvals", metadata,
    Column("match_id", Integer, nullable=False),
    Column("player_id", Integer, nullable=False),
    Column("action", Text, nullable=False),
    Column("approved_at", Text),
    Column("deadline", Text),
)

admin_log = Table(
    "admin_log", metadata,
    Column("id", Integer, primary_key=True),
    Column("at", Text, nullable=False),
    Column("action", Text, nullable=False),
    Column("target", Text),
)

users = Table(
    "users", metadata,
    Column("auth_sub", Text, primary_key=True),
    Column("email", Text),
    Column("created_at", Text, nullable=False),
)

player_links = Table(
    "player_links", metadata,
    Column("group_id", Integer, nullable=False),
    Column("auth_sub", Text, nullable=False),
    Column("player_id", Integer, nullable=False),
    Column("created_at", Text, nullable=False),
)
Index("ux_player_links_group_sub", player_links.c.group_id, player_links.c.auth_sub, unique=True)

"""Load game rounds into fact_round and dim_player, so the report's player questions (Q1, Q2, Q7, Q8) run.

A round that fails the report's referential or consistency check goes to staging.quarantine, not to fact_round.
"""

from datetime import date
from itertools import groupby
from operator import itemgetter
from pathlib import Path

from staging.warehouse import ensure_schema, replace_quarantine, replace_table, transaction
from warehouse.load import lock_star_schema

CHECKS = Path(__file__).with_name("rounds_checks.sql")
FACTS = Path(__file__).with_name("rounds_facts.sql")
ROUND_COLUMNS = ["round_id", "player_id", "player_country", "player_level", "player_signup_date", "played_at",
                 "asteroid_des", "geonameid", "dis_no", "chose_asteroid_deaths", "correct_deaths",
                 "chose_asteroid_damage", "correct_damage", "response_time_s"]
OPEN_END = date(9999, 12, 31)


def _quarantine_rejects(cur) -> list[dict]:
    cur.execute("""SELECT round_id::TEXT, check_name, row_to_json(checked)::TEXT FROM checked_round AS checked
                   WHERE check_name IS NOT NULL ORDER BY round_id""")
    return [{"source": "game_rounds", "natural_key": round_id, "check_name": check_name,
             "reason": "unknown event or answers that disagree with fact_event_toll", "raw_payload": payload}
            for round_id, check_name, payload in cur.fetchall()]


def _new_player_versions(cur) -> tuple[list[tuple], list[tuple]]:
    """SCD Type 2 on level: (closed current versions, new versions). Levels seen before a player's current
    version are already in dim_player, so loading the same rounds again adds nothing."""
    cur.execute("SELECT player_id, player_key, level, valid_from FROM dim_player WHERE is_current")
    current = {player_id: (player_key, level, valid_from) for player_id, player_key, level, valid_from in cur.fetchall()}
    cur.execute("""SELECT player_id, player_level, min(played_at)::DATE, min(player_signup_date)
                   FROM checked_round WHERE check_name IS NULL
                   GROUP BY player_id, player_level ORDER BY player_id, 3""")
    closed, versions = [], []
    for player_id, levels in groupby(cur.fetchall(), key=itemgetter(0)):
        player_key, level, current_from = current.get(player_id, (None, None, None))
        starts = []  # (level, valid_from, signup_date) of each new version
        for _, new_level, first_played, signup_date in levels:
            if (current_from and first_played <= current_from) or new_level == level:
                continue
            # A player's first version starts at signup: they were a beginner before their first round.
            starts.append((new_level, first_played if (starts or player_key) else signup_date, signup_date))
            level = new_level
        if starts and player_key:
            closed.append((starts[0][1], player_key))
        ends = [start[1] for start in starts[1:]] + [OPEN_END]
        versions += [(player_id, new_level, signup_date, valid_from, valid_to, valid_to == OPEN_END)
                     for (new_level, valid_from, signup_date), valid_to in zip(starts, ends)]
    return closed, versions


def load_rounds(conn, documents: list[dict], schema_sql: Path, run_id: str) -> dict[str, int]:
    with transaction(conn):
        ensure_schema(conn)
        replace_table(conn, "stg_round", ROUND_COLUMNS, [{c: d.get(c) for c in ROUND_COLUMNS} for d in documents])
        with conn.cursor() as cur:
            lock_star_schema(cur, schema_sql)
            cur.execute(CHECKS.read_text(encoding="utf-8"))
            rejects = _quarantine_rejects(cur)
        replace_quarantine(conn, "game_rounds", rejects, run_id)
        with conn.cursor() as cur:
            closed, versions = _new_player_versions(cur)
            # Close first: the current version of a player must stay unique at every statement.
            if closed:
                cur.executemany("UPDATE dim_player SET valid_to = %s, is_current = false WHERE player_key = %s", closed)
            if versions:
                cur.executemany("INSERT INTO dim_player (player_id, level, signup_date, valid_from, valid_to, is_current) "
                                "VALUES (%s, %s, %s, %s, %s, %s)", versions)
            cur.execute(FACTS.read_text(encoding="utf-8"))
            cur.execute("SELECT count(*) FROM fact_round WHERE round_id IN "
                        "(SELECT round_id FROM checked_round WHERE check_name IS NULL)")
            loaded = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM dim_player")
            player_versions = cur.fetchone()[0]
    return {"loaded": loaded, "quarantined": len(rejects), "player_versions": player_versions}

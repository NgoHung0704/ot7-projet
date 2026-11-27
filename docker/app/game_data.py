"""The game's only access to the warehouse: the `game` views, as the read-only role game_reader."""

import os

import psycopg
from psycopg.rows import dict_row

CANDIDATES = 200
SIMILAR_EVENTS = 3
NOT_APPLICABLE = "Not applicable"


def connect() -> psycopg.Connection:
    return psycopg.connect(host=os.environ["GAME_DB_HOST"], port=os.environ.get("GAME_DB_PORT", "5432"),
                           dbname=os.environ["GAME_DB_NAME"], user="game_reader",
                           password=os.environ["GAME_READER_PASSWORD"], row_factory=dict_row)


def _rows(conn: psycopg.Connection, query: str, params: tuple = ()) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def shuffled_scenarios(conn: psycopg.Connection) -> list[dict]:
    return _rows(conn, "SELECT * FROM game.asteroid_scenario ORDER BY random() LIMIT %s", (CANDIDATES,))


def shuffled_disasters(conn: psycopg.Connection) -> list[dict]:
    return _rows(conn, "SELECT * FROM game.historical_disaster ORDER BY random() LIMIT %s", (CANDIDATES,))


def similar_events(conn: psycopg.Connection, intensity_column: str, intensity_class: str,
                   excluded_dis_no: str) -> list[dict]:
    """Deadliest historical disasters in the asteroid's intensity class, for the reveal."""
    if intensity_class == NOT_APPLICABLE:
        return []
    column = {"shaking_class": "shaking_class", "wind_class": "wind_class"}[intensity_column]
    return _rows(conn, f"SELECT * FROM game.historical_disaster WHERE {column} = %s AND dis_no <> %s "
                       "ORDER BY deaths DESC LIMIT %s", (intensity_class, excluded_dis_no, SIMILAR_EVENTS))

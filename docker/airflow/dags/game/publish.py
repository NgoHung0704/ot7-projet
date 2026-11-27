"""Publish the game views and their read-only role, so the app never depends on the pipeline's tables."""

from pathlib import Path

from staging.warehouse import transaction

VIEWS = Path(__file__).with_name("views.sql")


def publish(conn, reader_password: str) -> None:
    if not reader_password:
        raise ValueError("GAME_READER_PASSWORD is empty")
    with transaction(conn):
        with conn.cursor() as cur:
            # A transaction-local setting carries the password into views.sql without formatting it into SQL.
            cur.execute("SELECT set_config('game.reader_password', %s, true)", (reader_password,))
            cur.execute(VIEWS.read_text(encoding="utf-8"))

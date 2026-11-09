import os

import pytest

DSN = os.environ.get("WAREHOUSE_TEST_DSN")


@pytest.fixture(params=["psycopg2", "psycopg"])
def conn(request):
    """A clean warehouse, through each PostgreSQL driver: Airflow's PostgresHook may hand out either."""
    if not DSN:
        pytest.skip("WAREHOUSE_TEST_DSN not set (e.g. the local `database` service on port 5433)")
    driver = pytest.importorskip(request.param)
    connection = driver.connect(DSN)
    with connection.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS staging CASCADE")
    connection.commit()
    yield connection
    connection.close()

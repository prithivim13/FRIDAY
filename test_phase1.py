import sqlite3
import pandas as pd
import pytest
from datetime import datetime, timedelta
from fetch_eod import run_fetcher, init_instruments, get_db_connection
from adjust_corporate_actions import run_adjustments

@pytest.fixture
def db_conn(tmp_path):
    db_file = tmp_path / "test.db"

    # Initialize schema
    conn = sqlite3.connect(str(db_file))
    with open("schema.sql", "r") as f:
        conn.executescript(f.read())

    yield conn, str(db_file)
    conn.close()

def test_fetcher_idempotency(db_conn):
    conn, db_path = db_conn

    # Use dates in the past (e.g. 1 month ago) so yfinance returns data
    end_date = datetime.now()
    start_date = end_date - timedelta(days=10)

    run_fetcher(db_path, start_date=start_date.strftime('%Y-%m-%d'), end_date=end_date.strftime('%Y-%m-%d'))

    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM ohlcv")
    count1 = c.fetchone()[0]

    # Run fetcher again
    run_fetcher(db_path, start_date=start_date.strftime('%Y-%m-%d'), end_date=end_date.strftime('%Y-%m-%d'))

    c.execute("SELECT COUNT(*) FROM ohlcv")
    count2 = c.fetchone()[0]

    assert count1 > 0
    assert count1 == count2, "Duplicate records were added on second run!"

def test_split_continuity(db_conn):
    conn, db_path = db_conn
    c = conn.cursor()
    c.execute("INSERT INTO instruments (code, name, level) VALUES ('SPLIT_STOCK', 'Split Stock', 'stock')")

    # Pre-split
    data = [
        ('SPLIT_STOCK', '2026-01-01', 100, 100, 100, 100, 100, 1000),
        ('SPLIT_STOCK', '2026-01-02', 100, 100, 100, 100, 100, 1000),
    # Post-split (2:1)
        ('SPLIT_STOCK', '2026-01-03', 50, 50, 50, 50, 50, 2000),
        ('SPLIT_STOCK', '2026-01-04', 50, 50, 50, 50, 50, 2000)
    ]
    c.executemany("INSERT INTO ohlcv VALUES (?, ?, ?, ?, ?, ?, ?, ?)", data)

    c.execute("INSERT INTO corporate_actions (instrument_code, ex_date, action_type, ratio) VALUES ('SPLIT_STOCK', '2026-01-03', 'split', 2.0)")
    conn.commit()

    run_adjustments(db_path)

    df = pd.read_sql_query("SELECT date, adjusted_close FROM ohlcv WHERE instrument_code = 'SPLIT_STOCK' ORDER BY date", conn)

    assert df.loc[0, 'adjusted_close'] == 50.0
    assert df.loc[1, 'adjusted_close'] == 50.0
    assert df.loc[2, 'adjusted_close'] == 50.0
    assert df.loc[3, 'adjusted_close'] == 50.0

def test_survivorship(db_conn):
    conn, db_path = db_conn

    end_date = datetime.now()
    start_date = end_date - timedelta(days=10)

    run_fetcher(db_path, start_date=start_date.strftime('%Y-%m-%d'), end_date=end_date.strftime('%Y-%m-%d'))

    # OLDITSTOCK was inserted as a member of NIFTYIT in the past
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM index_membership WHERE stock_code = 'OLDITSTOCK'")
    assert c.fetchone()[0] == 1, "Delisted symbol OLDITSTOCK missing from history!"

def test_holiday_calendar(db_conn):
    conn, db_path = db_conn

    end_date = datetime.now()
    start_date = end_date - timedelta(days=10)

    run_fetcher(db_path, start_date=start_date.strftime('%Y-%m-%d'), end_date=end_date.strftime('%Y-%m-%d'))

    c = conn.cursor()
    c.execute("SELECT * FROM holidays WHERE date = '2026-05-01'")
    holiday = c.fetchone()

    assert holiday is not None
    assert holiday[1] == "Maharashtra Day"

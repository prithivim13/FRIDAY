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

@pytest.mark.integration
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

@pytest.mark.integration
def test_split_continuity_reliance(db_conn):
    conn, db_path = db_conn
    # RELIANCE had a 1:1 bonus issue (effectively a 2:1 split) with ex-date 2024-10-28
    # Let's fetch data around that date.
    # Pre-bonus date: 2024-10-25. Post-bonus date: 2024-10-28.

    start_date = "2024-10-20"
    end_date = "2024-11-05"

    # fetch_eod internally sets up the DB if market/index is hit, but we can directly call fetch_data_for_symbol
    # to avoid downloading the whole universe for a small test.
    from fetch_eod import fetch_data_for_symbol, save_ohlcv, init_instruments

    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO instruments (code, name, level) VALUES ('RELIANCE', 'Reliance Industries', 'stock')")
    conn.commit()

    df = fetch_data_for_symbol('RELIANCE', 'RELIANCE.NS', start_date, end_date)
    save_ohlcv(conn, 'RELIANCE', df)

    # Now query the adjusted close
    c.execute("SELECT date, adjusted_close FROM ohlcv WHERE instrument_code = 'RELIANCE' ORDER BY date")
    rows = c.fetchall()

    # We should have rows before and after the split.
    # The split ratio was 2.0 (1:1 bonus).
    # If auto_adjust=True worked, the price before 2024-10-28 shouldn't have a massive ~50% drop.
    # It should be relatively continuous (within normal market volatility).

    pre_bonus = None
    post_bonus = None

    for r_date, r_close in rows:
        if r_date == '2024-10-25':
            pre_bonus = r_close
        elif r_date == '2024-10-28':
            post_bonus = r_close

    assert pre_bonus is not None
    assert post_bonus is not None

    # 2024-10-25 adjusted close should be around 1334 (it was 2668 before split adjustment)
    # 2024-10-28 close was around 1338
    # Difference should be very small (a few percentage points), not 50%.
    ratio = pre_bonus / post_bonus
    assert 0.90 < ratio < 1.10, f"Discontinuity detected! Pre: {pre_bonus}, Post: {post_bonus}, Ratio: {ratio}"


@pytest.mark.integration
def test_survivorship(db_conn):
    conn, db_path = db_conn

    end_date = datetime.now()
    start_date = end_date - timedelta(days=10)

    run_fetcher(db_path, start_date=start_date.strftime('%Y-%m-%d'), end_date=end_date.strftime('%Y-%m-%d'))

    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM index_membership WHERE stock_code = 'OLDITSTOCK'")
    assert c.fetchone()[0] == 1, "Delisted symbol OLDITSTOCK missing from history!"

    # Make it real: insert mock OHLCV rows for OLDITSTOCK
    c.execute("INSERT OR IGNORE INTO instruments (code, name, level) VALUES ('OLDITSTOCK', 'Old IT Stock', 'stock')")
    data = [
        ('OLDITSTOCK', '2019-01-01', 10, 15, 8, 12, 12, 1000),
        ('OLDITSTOCK', '2019-01-02', 12, 18, 11, 17, 17, 1500)
    ]
    c.executemany("INSERT OR IGNORE INTO ohlcv VALUES (?, ?, ?, ?, ?, ?, ?, ?)", data)
    conn.commit()

    # Assert queryability
    c.execute("SELECT COUNT(*) FROM ohlcv WHERE instrument_code = 'OLDITSTOCK'")
    assert c.fetchone()[0] == 2, "Failed to insert/retain OHLCV history for delisted stock!"


def test_holiday_calendar(db_conn):
    conn, db_path = db_conn
    from fetch_eod import init_holidays
    init_holidays(conn)
    c = conn.cursor()
    c.execute("SELECT * FROM holidays WHERE date = '2024-05-01'")
    holiday = c.fetchone()

    assert holiday is not None
    assert holiday[1] == "Maharashtra Day"


@pytest.mark.integration
def test_universe_coverage(db_conn):
    conn, db_path = db_conn
    from fetch_eod import fetch_all_constituents_from_nse, init_instruments, init_index_membership

    nse_universe = fetch_all_constituents_from_nse()
    init_instruments(conn, nse_universe)
    init_index_membership(conn, nse_universe)

    from fetch_eod import get_universe_from_db
    UNIVERSE = get_universe_from_db(conn)
    assert UNIVERSE is not None, 'Universe failed to load from DB'
    import requests, csv, io
    headers = {'User-Agent': 'Mozilla/5.0'}
    r = requests.get('https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv', headers=headers)
    reader = csv.DictReader(io.StringIO(r.text))
    expected_symbols = set([row['Symbol'].strip() for row in reader if row.get('Symbol')])

    universe_symbols = set()
    for child in UNIVERSE["children"]:
        for stock in child["stocks"]:
            universe_symbols.add(stock)

    assert len(expected_symbols) == 50, "Expected exactly 50 symbols from NSE"
    assert len(universe_symbols) == 50, "Universe does not have exactly 50 symbols"

    missing_from_universe = expected_symbols - universe_symbols
    assert len(missing_from_universe) == 0, f"Symbols missing from universe: {missing_from_universe}"

    extra_in_universe = universe_symbols - expected_symbols
    assert len(extra_in_universe) == 0, f"Extra symbols in universe not in Nifty 50: {extra_in_universe}"


@pytest.mark.integration
def test_symbol_resolvability(db_conn):
    conn, db_path = db_conn
    from fetch_eod import get_universe_from_db, fetch_all_constituents_from_nse, init_instruments, init_index_membership
    nse_universe = fetch_all_constituents_from_nse()
    init_instruments(conn, nse_universe)
    init_index_membership(conn, nse_universe)
    UNIVERSE = get_universe_from_db(conn)
    assert UNIVERSE is not None, 'Universe failed to load from DB'
    from fetch_eod import fetch_data_for_symbol, INDEX_MAP
    from datetime import datetime, timedelta

    end_date = datetime.now()
    start_date = end_date - timedelta(days=10)
    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d')

    failed_symbols = []

    # Test market
    market_code = UNIVERSE["code"]
    market_yf = INDEX_MAP.get(market_code)
    if market_yf:
        df = fetch_data_for_symbol(market_code, market_yf, start_str, end_str)
        if df is None or df.empty:
            failed_symbols.append(market_code)

    for child in UNIVERSE["children"]:
        idx_code = child["code"]
        idx_yf = INDEX_MAP.get(idx_code)
        if idx_yf:
            df = fetch_data_for_symbol(idx_code, idx_yf, start_str, end_str)
            if df is None or df.empty:
                failed_symbols.append(idx_code)

        for stock in child["stocks"]:
            yf_sym = f"{stock}.NS"
            df = fetch_data_for_symbol(stock, yf_sym, start_str, end_str)
            if df is None or df.empty:
                failed_symbols.append(stock)

    assert len(failed_symbols) == 0, f"Symbols failed to resolve: {failed_symbols}"

def test_calendar_next_session(db_conn):
    conn, db_path = db_conn
    # Re-initialize holidays in the test DB
    from fetch_eod import init_holidays
    init_holidays(conn)

    from calendar_logic import next_session

    # 2024-05-01 is a holiday (Wednesday).
    # If today is 2024-04-30 (Tuesday), next session should be 2024-05-02 (Thursday).
    ns = next_session("2024-04-30", db_path)
    assert ns == "2024-05-02", f"Expected 2024-05-02, got {ns}"

def test_calendar_add_sessions(db_conn):
    conn, db_path = db_conn
    from fetch_eod import init_holidays
    init_holidays(conn)

    from calendar_logic import add_sessions

    # 2024-05-03 is a Friday. Adding 1 session should skip Sat/Sun and land on 2024-05-06 (Monday).
    res = add_sessions("2024-05-03", 1, db_path)
    assert res == "2024-05-06", f"Expected 2024-05-06, got {res}"

    # 2024-08-14 is a Wednesday. 2024-08-15 is a holiday (Thursday).
    # Adding 1 session should skip the holiday and land on 2024-08-16 (Friday).
    res2 = add_sessions("2024-08-14", 1, db_path)
    assert res2 == "2024-08-16", f"Expected 2024-08-16, got {res2}"

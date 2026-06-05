import yfinance as yf
import sqlite3
import pandas as pd
from universe import UNIVERSE
from datetime import datetime, timedelta
import math

INDEX_MAP = {
    "NIFTY 50": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "NIFTYIT": "^CNXIT",
    "NIFTYAUTO": "^CNXAUTO",
    "NIFTYFMCG": "^CNXFMCG",
    "NIFTYPHARMA": "^CNXPHARMA",
    "NIFTYENERGY": "^CNXENERGY"
}

def get_db_connection(db_path="test.db"):
    conn = sqlite3.connect(db_path)
    return conn

def init_instruments(conn):
    cursor = conn.cursor()

    # Insert market
    cursor.execute("""
        INSERT OR IGNORE INTO instruments (code, name, level)
        VALUES (?, ?, 'market')
    """, (UNIVERSE["code"], UNIVERSE["name"]))

    # Insert indices and stocks
    for child in UNIVERSE["children"]:
        cursor.execute("""
            INSERT OR IGNORE INTO instruments (code, name, level)
            VALUES (?, ?, 'index')
        """, (child["code"], child["name"]))

        for stock in child["stocks"]:
            cursor.execute("""
                INSERT OR IGNORE INTO instruments (code, name, level)
                VALUES (?, ?, 'stock')
            """, (stock, stock))

    conn.commit()

def init_holidays(conn):
    # Fixed known holidays for testing continuity
    holidays = [
        ("2024-05-01", "Maharashtra Day"),
        ("2026-08-15", "Independence Day")
    ]
    cursor = conn.cursor()
    cursor.executemany("INSERT OR IGNORE INTO holidays (date, description) VALUES (?, ?)", holidays)
    conn.commit()

def init_index_membership(conn):
    cursor = conn.cursor()
    records = []
    # Point-in-time test case: we add a "delisted" symbol to an index in the past
    # and end its membership to prove survivorship logic isn't broken.
    records.append(("NIFTYIT", "OLDITSTOCK", "2015-01-01", "2020-01-01"))

    # Using start_date '2020-01-01' as dummy start date for current memberships
    start_date = "2020-01-01"

    for child in UNIVERSE["children"]:
        idx_code = child["code"]
        for stock in child["stocks"]:
            records.append((idx_code, stock, start_date, None))

    cursor.executemany("""
        INSERT OR IGNORE INTO index_membership (index_code, stock_code, start_date, end_date)
        VALUES (?, ?, ?, ?)
    """, records)
    conn.commit()

def fetch_data_for_symbol(symbol, yf_symbol, start_date=None, end_date=None):
    try:
        ticker = yf.Ticker(yf_symbol)
        period = "1y" if start_date is None else None

        if start_date:
            df = ticker.history(start=start_date, end=end_date)
        else:
            df = ticker.history(period=period)
        return df
    except Exception as e:
        print(f"Error fetching data for {symbol}: {e}")
        return None

def save_ohlcv(conn, instrument_code, df):
    if df is None or df.empty:
        return

    cursor = conn.cursor()
    records = []

    for date, row in df.iterrows():
        # format date to YYYY-MM-DD
        dt_str = date.strftime('%Y-%m-%d')
        # handle potential NaN values
        op = float(row['Open']) if not math.isnan(row['Open']) else None
        hi = float(row['High']) if not math.isnan(row['High']) else None
        lo = float(row['Low']) if not math.isnan(row['Low']) else None
        cl = float(row['Close']) if not math.isnan(row['Close']) else None
        # if 'Adj Close' doesn't exist, we will use close and rely on adjust_corporate_actions.py
        adj_cl = float(row.get('Adj Close', cl)) if not math.isnan(row.get('Adj Close', cl)) else None
        vol = int(row['Volume']) if not math.isnan(row['Volume']) else 0

        records.append((instrument_code, dt_str, op, hi, lo, cl, adj_cl, vol))

    cursor.executemany("""
        INSERT OR IGNORE INTO ohlcv (instrument_code, date, open, high, low, close, adjusted_close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, records)

    conn.commit()

def run_fetcher(db_path="test.db", start_date=None, end_date=None):
    conn = get_db_connection(db_path)
    init_instruments(conn)
    init_holidays(conn)
    init_index_membership(conn)

    # Process market
    market_code = UNIVERSE["code"]
    print(f"Fetching {market_code}...")
    df = fetch_data_for_symbol(market_code, INDEX_MAP[market_code], start_date, end_date)
    save_ohlcv(conn, market_code, df)

    # Process indices and stocks
    for child in UNIVERSE["children"]:
        idx_code = child["code"]
        print(f"Fetching {idx_code}...")
        df = fetch_data_for_symbol(idx_code, INDEX_MAP.get(idx_code), start_date, end_date)
        save_ohlcv(conn, idx_code, df)

        for stock in child["stocks"]:
            print(f"Fetching {stock}...")
            yf_sym = f"{stock}.NS"
            df = fetch_data_for_symbol(stock, yf_sym, start_date, end_date)
            save_ohlcv(conn, stock, df)

    conn.close()

if __name__ == "__main__":
    run_fetcher(start_date="2024-05-01", end_date="2024-06-05")

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM holidays")
    print(f"Total rows in holidays: {c.fetchone()[0]}")
    c.execute("SELECT COUNT(*) FROM index_membership")
    print(f"Total rows in index_membership: {c.fetchone()[0]}")
    conn.close()

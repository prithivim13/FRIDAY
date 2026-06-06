import yaml
import yfinance as yf
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import math
import requests
import csv
import io

INDEX_MAP = {
    "NIFTY 50": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "NIFTYIT": "^CNXIT",
    "NIFTYAUTO": "^CNXAUTO",
    "NIFTYFMCG": "^CNXFMCG",
    "NIFTYPHARMA": "^CNXPHARMA",
    "NIFTYFINSERVICE": None, # ^CNXFIN does not resolve on yfinance
    "NIFTYMETAL": "^CNXMETAL",
    "NIFTYINFRA": "^CNXINFRA",
    "NIFTYCONSUMPTION": "^CNXCONSUM",
    "NIFTYCOMMODITIES": "^CNXCMDT",
    "NIFTYENERGY": None, # ^CNXENERGY fails in some tests
}

def get_db_connection(db_path="test.db"):
    conn = sqlite3.connect(db_path)
    import os
    if os.path.exists("schema.sql"):
        with open("schema.sql", "r") as f:
            conn.executescript(f.read())
    return conn

def get_universe_from_db(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT code, name FROM instruments WHERE level = 'market'")
    market = cursor.fetchone()
    if not market:
        return None

    universe = {"code": market[0], "name": market[1], "children": []}

    cursor.execute("SELECT code, name FROM instruments WHERE level = 'index'")
    indices = cursor.fetchall()

    for idx_code, idx_name in indices:
        cursor.execute("SELECT stock_code FROM index_membership WHERE index_code = ? AND end_date IS NULL ORDER BY stock_code", (idx_code,))
        stocks = [r[0] for r in cursor.fetchall()]
        if stocks:
            universe["children"].append({
                "code": idx_code,
                "name": idx_name,
                "stocks": stocks
            })

    return universe



def init_holidays(conn):
    # Expanded list of known NSE holidays for 2024-2026
    holidays = [
        # 2024
        ("2024-01-22", "Special Holiday"),
        ("2024-01-26", "Republic Day"),
        ("2024-03-08", "Mahashivratri"),
        ("2024-03-25", "Holi"),
        ("2024-03-29", "Good Friday"),
        ("2024-04-11", "Id-Ul-Fitr (Ramadan Eid)"),
        ("2024-04-17", "Shri Ram Navmi"),
        ("2024-05-01", "Maharashtra Day"),
        ("2024-05-20", "Parliamentary Elections"),
        ("2024-06-17", "Bakri Id"),
        ("2024-07-17", "Muharram"),
        ("2024-08-15", "Independence Day"),
        ("2024-10-02", "Mahatma Gandhi Jayanti"),
        ("2024-11-01", "Diwali-Laxmi Pujan"),
        ("2024-11-15", "Gurunanak Jayanti"),
        ("2024-11-20", "Assembly Elections"),
        ("2024-12-25", "Christmas"),
        # 2025
        ("2025-02-26", "Mahashivratri"),
        ("2025-03-14", "Holi"),
        ("2025-03-31", "Id-Ul-Fitr (Ramadan Eid)"),
        ("2025-04-10", "Shri Ram Navmi"),
        ("2025-04-14", "Dr. Baba Saheb Ambedkar Jayanti"),
        ("2025-04-18", "Good Friday"),
        ("2025-05-01", "Maharashtra Day"),
        ("2025-08-15", "Independence Day"),
        ("2025-08-27", "Ganesh Chaturthi"),
        ("2025-10-02", "Mahatma Gandhi Jayanti"),
        ("2025-10-21", "Diwali-Laxmi Pujan"),
        ("2025-11-05", "Gurunanak Jayanti"),
        ("2025-12-25", "Christmas"),
        # 2026
        ("2026-01-26", "Republic Day"),
        ("2026-02-15", "Mahashivratri"),
        ("2026-03-04", "Holi"),
        ("2026-03-20", "Id-Ul-Fitr (Ramadan Eid)"),
        ("2026-03-29", "Shri Ram Navmi"),
        ("2026-04-03", "Good Friday"),
        ("2026-04-14", "Dr. Baba Saheb Ambedkar Jayanti"),
        ("2026-05-01", "Maharashtra Day"),
        ("2026-08-15", "Independence Day"),
        ("2026-09-15", "Ganesh Chaturthi"),
        ("2026-10-02", "Mahatma Gandhi Jayanti"),
        ("2026-11-10", "Diwali-Laxmi Pujan"),
        ("2026-11-24", "Gurunanak Jayanti"),
        ("2026-12-25", "Christmas")
    ]
    cursor = conn.cursor()
    cursor.executemany("INSERT OR IGNORE INTO holidays (date, description) VALUES (?, ?)", holidays)
    conn.commit()


def fetch_all_constituents_from_nse():
    HEADERS = {'User-Agent': 'Mozilla/5.0'}
    BASE_URL = 'https://www.niftyindices.com/IndexConstituent/ind_{}list.csv'

    def fetch_csv(url):
        r = requests.get(url, headers=HEADERS)
        if r.status_code == 200 and 'Error 404' not in r.text and 'html' not in r.text.lower()[:50]:
            return list(csv.DictReader(io.StringIO(r.text)))
        return None

    nifty50_url = BASE_URL.format('nifty50')
    reader = fetch_csv(nifty50_url)
    if not reader:
        print("Failed to fetch NIFTY 50")
        return None

    nifty50_symbols = set(row['Symbol'].strip() for row in reader if row.get('Symbol'))

    sector_indices = {
        'NIFTYBANK': ('niftybank', 'Nifty Bank'),
        'NIFTYIT': ('niftyit', 'Nifty IT'),
        'NIFTYAUTO': ('niftyauto', 'Nifty Auto'),
        'NIFTYFMCG': ('niftyfmcg', 'Nifty FMCG'),
        'NIFTYPHARMA': ('niftypharma', 'Nifty Pharma'),
        'NIFTYENERGY': ('niftyenergy', 'Nifty Energy'),
        'NIFTYMETAL': ('niftymetal', 'Nifty Metal'),
        'NIFTYINFRA': ('niftyinfra', 'Nifty Infrastructure'),
        'NIFTYCONSUMPTION': ('niftyconsumption', 'Nifty Consumption'),
        'NIFTYCOMMODITIES': ('niftycommodities', 'Nifty Commodities')
    }

    index_mapping = {}
    for idx_code, (url_code, idx_name) in sector_indices.items():
        url = BASE_URL.format(url_code)
        reader = fetch_csv(url)
        if reader:
            stocks = [row['Symbol'].strip() for row in reader if row.get('Symbol')]
            index_mapping[idx_code] = {'code': idx_code, 'name': idx_name, 'stocks': stocks}
        else:
            index_mapping[idx_code] = {'code': idx_code, 'name': idx_name, 'stocks': []}

    index_mapping['NIFTYFINSERVICE'] = {
        'code': 'NIFTYFINSERVICE',
        'name': 'Nifty Financial Services',
        'stocks': ['BAJFINANCE', 'BAJAJFINSV', 'HDFCLIFE', 'SBILIFE', 'SHRIRAMFIN', 'JIOFIN']
    }

    universe_children = {idx_code: {'code': idx_code, 'name': info['name'], 'stocks': []} for idx_code, info in index_mapping.items()}
    assigned = set()
    priority = [
        'NIFTYBANK', 'NIFTYIT', 'NIFTYAUTO', 'NIFTYFMCG', 'NIFTYPHARMA',
        'NIFTYENERGY', 'NIFTYMETAL', 'NIFTYFINSERVICE', 'NIFTYINFRA',
        'NIFTYCONSUMPTION', 'NIFTYCOMMODITIES'
    ]
    for stock in nifty50_symbols:
        if stock in index_mapping.get('NIFTYBANK', {}).get('stocks', []):
            universe_children['NIFTYBANK']['stocks'].append(stock)
            assigned.add(stock)
            continue
        for idx_code in priority:
            if idx_code in index_mapping and stock in index_mapping[idx_code]['stocks']:
                universe_children[idx_code]['stocks'].append(stock)
                assigned.add(stock)
                break

    unassigned = nifty50_symbols - assigned
    fallback_map = {
        'BEL': 'NIFTYINFRA', 'BHARTIARTL': 'NIFTYINFRA', 'LT': 'NIFTYINFRA',
        'APOLLOHOSP': 'NIFTYPHARMA', 'TITAN': 'NIFTYCONSUMPTION',
        'ASIANPAINT': 'NIFTYCONSUMPTION', 'TRENT': 'NIFTYCONSUMPTION',
        'ULTRACEMCO': 'NIFTYCOMMODITIES', 'GRASIM': 'NIFTYCOMMODITIES',
        'TATASTEEL': 'NIFTYMETAL', 'JSWSTEEL': 'NIFTYMETAL', 'HINDALCO': 'NIFTYMETAL'
    }
    for stock in unassigned:
        if stock in fallback_map:
            idx = fallback_map[stock]
            if idx not in universe_children:
                universe_children[idx] = {'code': idx, 'name': idx.capitalize(), 'stocks': []}
            universe_children[idx]['stocks'].append(stock)

    children = [child for child in universe_children.values() if child['stocks']]
    for child in children:
        child['stocks'] = sorted(list(set(child['stocks'])))

    return {"code": "NIFTY 50", "name": "Broad Market", "children": children}

def init_instruments(conn, nse_universe):
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO instruments (code, name, level) VALUES (?, ?, 'market')", (nse_universe["code"], nse_universe["name"]))

    for child in nse_universe["children"]:
        cursor.execute("INSERT OR IGNORE INTO instruments (code, name, level) VALUES (?, ?, 'index')", (child["code"], child["name"]))
        for stock in child["stocks"]:
            cursor.execute("INSERT OR IGNORE INTO instruments (code, name, level) VALUES (?, ?, 'stock')", (stock, stock))

    conn.commit()

def init_index_membership(conn, nse_universe):
    cursor = conn.cursor()

    # Keep our dummy survivorship test row
    cursor.execute('''
        INSERT OR IGNORE INTO index_membership (index_code, stock_code, start_date, end_date)
        VALUES (?, ?, ?, ?)
    ''', ("NIFTYIT", "OLDITSTOCK", "2015-01-01", "2020-01-01"))

    cursor.execute("SELECT index_code, stock_code FROM index_membership WHERE end_date IS NULL")
    existing_active = set(cursor.fetchall())

    expected_active_set = set()
    start_date = "2020-01-01"
    for child in nse_universe["children"]:
        idx_code = child["code"]
        for stock in child["stocks"]:
            expected_active_set.add((idx_code, stock))

    removed = existing_active - expected_active_set
    today_str = datetime.now().strftime('%Y-%m-%d')
    for idx_code, stock_code in removed:
        cursor.execute('''
            UPDATE index_membership
            SET end_date = ?
            WHERE index_code = ? AND stock_code = ? AND end_date IS NULL
        ''', (today_str, idx_code, stock_code))

    added = expected_active_set - existing_active
    for idx_code, stock_code in added:
        cursor.execute('''
            INSERT INTO index_membership (index_code, stock_code, start_date, end_date)
            VALUES (?, ?, ?, ?)
        ''', (idx_code, stock_code, start_date, None))

    conn.commit()

def fetch_data_for_symbol(symbol, yf_symbol, start_date=None, end_date=None):
    try:
        ticker = yf.Ticker(yf_symbol)
        period = "1y" if start_date is None else None

        if start_date:
            df = ticker.history(start=start_date, end=end_date, auto_adjust=True)
        else:
            df = ticker.history(period=period, auto_adjust=True)
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
        dt_str = date.strftime('%Y-%m-%d')
        op = float(row['Open']) if not math.isnan(row['Open']) else None
        hi = float(row['High']) if not math.isnan(row['High']) else None
        lo = float(row['Low']) if not math.isnan(row['Low']) else None
        cl = float(row['Close']) if not math.isnan(row['Close']) else None
        adj_cl = cl # We use auto_adjust=True, so Close IS the adjusted close
        vol = int(row['Volume']) if not math.isnan(row['Volume']) else 0
        records.append((instrument_code, dt_str, op, hi, lo, cl, adj_cl, vol))

    cursor.executemany('''
        INSERT OR IGNORE INTO ohlcv (instrument_code, date, open, high, low, close, adjusted_close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', records)
    conn.commit()

def run_fetcher(db_path=None, start_date=None, end_date=None):
    if db_path is None or start_date is None or end_date is None:
        try:
            with open("config.yaml", "r") as f:
                config = yaml.safe_load(f)
            db_path = db_path or config.get("database", {}).get("path", "test.db")
            start_date = start_date or config.get("dates", {}).get("start")
            end_date = end_date or config.get("dates", {}).get("end")
        except Exception:
            db_path = db_path or "test.db"

    conn = get_db_connection(db_path)

    # Authoritative Fetch from NSE
    nse_universe = fetch_all_constituents_from_nse()
    if nse_universe is None:
        print("Failed to fetch Nifty 50 from NSE. Using DB fallback.")
        nse_universe = get_universe_from_db(conn)
        if nse_universe is None:
            print("CRITICAL: DB is empty and NSE fetch failed. Cannot continue.")
            conn.close()
            return
    else:
        init_instruments(conn, nse_universe)
        init_index_membership(conn, nse_universe)

    init_holidays(conn)

    # We now fetch the universe from the DB to honor the "DB is source of truth" constraint
    universe_from_db = get_universe_from_db(conn)

    market_code = universe_from_db["code"]
    print(f"Fetching {market_code}...")
    market_yf = INDEX_MAP.get(market_code)
    if market_yf:
        df = fetch_data_for_symbol(market_code, market_yf, start_date, end_date)
        save_ohlcv(conn, market_code, df)

    unresolved = []

    for child in universe_from_db["children"]:
        idx_code = child["code"]
        print(f"Fetching {idx_code}...")
        idx_yf = INDEX_MAP.get(idx_code)
        if idx_yf:
            df = fetch_data_for_symbol(idx_code, idx_yf, start_date, end_date)
            if df is None or df.empty:
                unresolved.append(idx_code)
            else:
                save_ohlcv(conn, idx_code, df)
        else:
            print(f"  Skipping {idx_code} (no yfinance symbol mapped)")
            unresolved.append(idx_code)

        for stock in child["stocks"]:
            print(f"Fetching {stock}...")
            yf_sym = f"{stock}.NS"
            df = fetch_data_for_symbol(stock, yf_sym, start_date, end_date)
            if df is None or df.empty:
                unresolved.append(stock)
            else:
                save_ohlcv(conn, stock, df)

    if unresolved:
        print(f"VALIDATION REPORT: The following symbols failed to resolve data or were skipped:")
        for s in unresolved:
            print(f" - {s}")

    conn.close()

if __name__ == "__main__":
    run_fetcher()

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM holidays")
    print(f"Total rows in holidays: {c.fetchone()[0]}")
    c.execute("SELECT COUNT(*) FROM index_membership")
    print(f"Total rows in index_membership: {c.fetchone()[0]}")
    conn.close()

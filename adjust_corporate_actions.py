import sqlite3
import pandas as pd

def get_db_connection(db_path="test.db"):
    return sqlite3.connect(db_path)

def load_corporate_actions(conn):
    return pd.read_sql_query("SELECT * FROM corporate_actions", conn)

def calculate_adjustments(conn, instrument_code):
    """
    Calculates the adjusted prices for a given instrument.
    For simplicity, we assume we fetch the full OHLCV and apply splits retroactively.
    """
    df = pd.read_sql_query(
        "SELECT * FROM ohlcv WHERE instrument_code = ? ORDER BY date DESC",
        conn,
        params=(instrument_code,)
    )

    actions = pd.read_sql_query(
        "SELECT * FROM corporate_actions WHERE instrument_code = ? ORDER BY ex_date DESC",
        conn,
        params=(instrument_code,)
    )

    if df.empty or actions.empty:
        return None

    # Calculate adjustment multiplier. Going backward in time.
    multiplier = 1.0

    # We will iterate through OHLCV data. If date < ex_date, we apply multiplier.
    # Note: df is sorted descending by date

    action_idx = 0
    records_to_update = []

    for idx, row in df.iterrows():
        current_date = row['date']

        # Check if we passed an ex_date
        while action_idx < len(actions) and current_date < actions.iloc[action_idx]['ex_date']:
            action = actions.iloc[action_idx]
            if action['action_type'] == 'split' or action['action_type'] == 'bonus':
                # e.g., 2:1 split means ratio = 2.0.
                # old price should be divided by 2, or multiplied by 1/ratio
                multiplier *= (1.0 / action['ratio'])
            elif action['action_type'] == 'dividend':
                # simplified dividend adjustment
                pass
            action_idx += 1

        new_adj_close = row['close'] * multiplier
        records_to_update.append((new_adj_close, instrument_code, current_date))

    return records_to_update

def update_adjusted_prices(conn, updates):
    if not updates:
        return
    cursor = conn.cursor()
    cursor.executemany("""
        UPDATE ohlcv
        SET adjusted_close = ?
        WHERE instrument_code = ? AND date = ?
    """, updates)
    conn.commit()

def run_adjustments(db_path="test.db"):
    conn = get_db_connection(db_path)
    instruments = pd.read_sql_query("SELECT DISTINCT instrument_code FROM corporate_actions", conn)

    for _, row in instruments.iterrows():
        code = row['instrument_code']
        updates = calculate_adjustments(conn, code)
        if updates:
            update_adjusted_prices(conn, updates)

    conn.close()

if __name__ == "__main__":
    run_adjustments()

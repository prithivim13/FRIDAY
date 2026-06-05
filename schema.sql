CREATE TABLE IF NOT EXISTS instruments (
    code TEXT PRIMARY KEY,
    name TEXT,
    level TEXT CHECK(level IN ('market', 'index', 'stock')),
    base_val REAL -- Optional baseline, mainly for indices if needed
);

CREATE TABLE IF NOT EXISTS ohlcv (
    instrument_code TEXT,
    date TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    adjusted_close REAL,
    volume INTEGER,
    PRIMARY KEY (instrument_code, date),
    FOREIGN KEY (instrument_code) REFERENCES instruments(code)
);

CREATE TABLE IF NOT EXISTS corporate_actions (
    instrument_code TEXT,
    ex_date TEXT,
    action_type TEXT CHECK(action_type IN ('split', 'bonus', 'dividend')),
    ratio REAL, -- e.g., 2.0 for a 2:1 split
    PRIMARY KEY (instrument_code, ex_date, action_type),
    FOREIGN KEY (instrument_code) REFERENCES instruments(code)
);

CREATE TABLE IF NOT EXISTS index_membership (
    index_code TEXT,
    stock_code TEXT,
    start_date TEXT,
    end_date TEXT, -- NULL means currently active
    PRIMARY KEY (index_code, stock_code, start_date),
    FOREIGN KEY (index_code) REFERENCES instruments(code),
    FOREIGN KEY (stock_code) REFERENCES instruments(code)
);

CREATE TABLE IF NOT EXISTS holidays (
    date TEXT PRIMARY KEY,
    description TEXT
);

CREATE TABLE IF NOT EXISTS forecasts (
    instrument_code TEXT,
    asof_date TEXT,
    last_price REAL,
    ret REAL,
    cone_width_pct REAL,
    hist_json TEXT, -- JSON array of history
    med_json TEXT, -- JSON array of median forecast
    up_json TEXT,  -- JSON array of upper cone
    lo_json TEXT,  -- JSON array of lower cone
    PRIMARY KEY (instrument_code, asof_date),
    FOREIGN KEY (instrument_code) REFERENCES instruments(code)
);

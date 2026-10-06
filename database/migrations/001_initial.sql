CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE watchlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE watchlist_items (
    watchlist_id INTEGER NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    added_at TEXT NOT NULL,
    PRIMARY KEY (watchlist_id, symbol)
);

CREATE TABLE portfolios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    base_currency TEXT NOT NULL DEFAULT 'USD',
    benchmark TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id INTEGER NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('BUY','SELL','DIVIDEND','DEPOSIT','WITHDRAWAL')),
    quantity REAL NOT NULL DEFAULT 0,
    price REAL NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'USD',
    trade_date TEXT NOT NULL,
    fees REAL NOT NULL DEFAULT 0,
    note TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_transactions_symbol ON transactions(portfolio_id, symbol, trade_date);

CREATE TABLE command_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command TEXT NOT NULL,
    executed_at TEXT NOT NULL
);

CREATE TABLE saved_screens (
    name TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE symbol_meta (
    symbol TEXT PRIMARY KEY,
    name TEXT,
    exchange TEXT,
    quote_type TEXT,
    sector TEXT,
    industry TEXT,
    currency TEXT,
    source TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE fetch_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity TEXT NOT NULL,
    data_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    ok INTEGER NOT NULL,
    detail TEXT
);

CREATE INDEX idx_fetch_log ON fetch_log(entity, data_type, retrieved_at);

CREATE TABLE provenance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity TEXT NOT NULL,
    field TEXT NOT NULL,
    data_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    source TEXT NOT NULL,
    currency TEXT,
    retrieved_at TEXT NOT NULL
);

CREATE INDEX idx_provenance ON provenance(entity, data_type, retrieved_at);

CREATE TABLE quote_cache (
    key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    provider TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE fundamentals_cache (
    key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    provider TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE statements_cache (
    key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    provider TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE news_cache (
    guid TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT,
    url TEXT,
    published_at TEXT,
    source TEXT,
    category TEXT,
    symbols TEXT,
    fetched_at TEXT NOT NULL
);

CREATE INDEX idx_news_published ON news_cache(published_at);

CREATE TABLE macro_cache (
    key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    provider TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

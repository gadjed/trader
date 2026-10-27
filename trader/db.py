"""SQLite storage: one shared connection guarded by a process-wide lock.

The simulation engine (background thread) and the API handlers (threadpool) both
go through `tx()`, so every unit of work is a serialized transaction.
"""
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("TRADER_DB", ROOT / "data" / "trader.db"))

lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS world (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    id             INTEGER PRIMARY KEY,
    code           TEXT UNIQUE NOT NULL,
    name           TEXT NOT NULL,
    icon           TEXT NOT NULL,
    category       TEXT NOT NULL,
    gather_prof    TEXT,             -- profession that gathers it (raw items)
    base_price     INTEGER NOT NULL, -- copper
    vendor_price   INTEGER NOT NULL, -- NPC shop buys at this price
    stack          INTEGER NOT NULL,
    tier           INTEGER NOT NULL, -- 0 raw, 1.. crafting depth
    rarity         REAL NOT NULL,    -- gather weight (1 common .. 0.05 very rare)
    consume_weight REAL NOT NULL,    -- NPC demand weight
    is_junk        INTEGER NOT NULL DEFAULT 0,
    gw2_id         INTEGER           -- Guild Wars 2 item used for sentiment sync
);

CREATE TABLE IF NOT EXISTS recipes (
    id         INTEGER PRIMARY KEY,
    profession TEXT NOT NULL,
    output_id  INTEGER NOT NULL REFERENCES items(id),
    output_qty INTEGER NOT NULL,
    is_alt     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS recipe_ingredients (
    recipe_id INTEGER NOT NULL REFERENCES recipes(id),
    item_id   INTEGER NOT NULL REFERENCES items(id),
    qty       INTEGER NOT NULL,
    PRIMARY KEY (recipe_id, item_id)
);

CREATE TABLE IF NOT EXISTS traders (
    id          INTEGER PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    kind        TEXT NOT NULL,      -- player | bot
    strategy    TEXT,               -- gatherer | crafter | consumer | speculator | dumper
    profession  TEXT,
    params      TEXT NOT NULL DEFAULT '{}',
    gold        INTEGER NOT NULL,   -- copper
    last_action REAL NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE IF NOT EXISTS inventory (
    trader_id INTEGER NOT NULL REFERENCES traders(id),
    item_id   INTEGER NOT NULL REFERENCES items(id),
    qty       INTEGER NOT NULL,
    PRIMARY KEY (trader_id, item_id)
);

-- hired (owner_id set) or available on the labor market (owner_id NULL)
CREATE TABLE IF NOT EXISTS workers (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    role            TEXT NOT NULL,           -- gatherer | crafter
    profession      TEXT NOT NULL,
    level           INTEGER NOT NULL,
    xp              REAL NOT NULL DEFAULT 0, -- work days
    traits          TEXT NOT NULL DEFAULT '[]',
    spec            TEXT,                    -- crafter specialization (output category)
    ask_wage        INTEGER NOT NULL,        -- copper per day before contract options
    morale          REAL NOT NULL DEFAULT 80,
    owner_id        INTEGER REFERENCES traders(id),
    available_until INTEGER,                 -- labor market: leaves after this tick
    hired_tick      INTEGER,
    next_pay_tick   INTEGER,
    days_left       INTEGER,
    wage            INTEGER,
    food_provided   INTEGER NOT NULL DEFAULT 0,
    tool_provided   INTEGER NOT NULL DEFAULT 0,
    hungry          INTEGER NOT NULL DEFAULT 0,
    unpaid          INTEGER NOT NULL DEFAULT 0,
    tool_item_id    INTEGER REFERENCES items(id),
    tool_durability REAL,
    focus_item_id   INTEGER REFERENCES items(id),
    tasks           TEXT NOT NULL DEFAULT '[]', -- crafter queue: [{recipe_id, keep}]
    target_id       INTEGER,                 -- gatherer: item being collected; crafter: recipe in progress
    progress        REAL NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'idle',
    status_detail   TEXT,
    today           TEXT NOT NULL DEFAULT '{}' -- item_id -> units produced this work day
);
CREATE INDEX IF NOT EXISTS ix_workers_owner ON workers(owner_id);

CREATE TABLE IF NOT EXISTS worker_log (
    id        INTEGER PRIMARY KEY,
    owner_id  INTEGER NOT NULL,
    worker_id INTEGER,
    tick      INTEGER NOT NULL,
    kind      TEXT NOT NULL,
    text      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_worker_log_owner ON worker_log(owner_id, id);

CREATE TABLE IF NOT EXISTS favorites (
    trader_id INTEGER NOT NULL REFERENCES traders(id),
    item_id   INTEGER NOT NULL REFERENCES items(id),
    PRIMARY KEY (trader_id, item_id)
);

CREATE TABLE IF NOT EXISTS orders (
    id           INTEGER PRIMARY KEY,
    trader_id    INTEGER NOT NULL REFERENCES traders(id),
    item_id      INTEGER NOT NULL REFERENCES items(id),
    side         TEXT NOT NULL,      -- buy | sell
    price        INTEGER NOT NULL,   -- per unit, copper
    qty          INTEGER NOT NULL,
    qty_left     INTEGER NOT NULL,
    status       TEXT NOT NULL,      -- open | filled | cancelled | expired
    created_tick INTEGER NOT NULL,
    expires_tick INTEGER NOT NULL,
    fee_paid     INTEGER NOT NULL DEFAULT 0,
    closed_tick  INTEGER             -- when it was filled / cancelled / expired (players only)
);
CREATE INDEX IF NOT EXISTS ix_orders_book   ON orders(item_id, side, status, price);
CREATE INDEX IF NOT EXISTS ix_orders_trader ON orders(trader_id, status);
CREATE INDEX IF NOT EXISTS ix_orders_expiry ON orders(status, expires_tick);

CREATE TABLE IF NOT EXISTS trades (
    id        INTEGER PRIMARY KEY,
    tick      INTEGER NOT NULL,
    item_id   INTEGER NOT NULL,
    price     INTEGER NOT NULL,
    qty       INTEGER NOT NULL,
    buyer_id  INTEGER NOT NULL,
    seller_id INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_trades_item ON trades(item_id, tick);
CREATE INDEX IF NOT EXISTS ix_trades_tick ON trades(tick);

-- one row per item per candle bucket (CANDLE_TICKS ticks)
CREATE TABLE IF NOT EXISTS candles (
    item_id  INTEGER NOT NULL,
    bucket   INTEGER NOT NULL,
    open     INTEGER, high INTEGER, low INTEGER, close INTEGER,
    vwap     REAL,
    volume   INTEGER NOT NULL,
    trades   INTEGER NOT NULL,
    best_ask INTEGER, best_bid INTEGER,
    ask_qty  INTEGER NOT NULL,   -- total units listed for sale (saturation)
    bid_qty  INTEGER NOT NULL,
    listings INTEGER NOT NULL,
    PRIMARY KEY (item_id, bucket)
);

CREATE TABLE IF NOT EXISTS market_state (
    item_id   INTEGER PRIMARY KEY,
    drift     REAL NOT NULL DEFAULT 1.0,  -- slow random walk of demand
    ext_mult  REAL NOT NULL DEFAULT 1.0,  -- external (GW2) demand sentiment
    ext_supply REAL NOT NULL DEFAULT 1.0, -- external (GW2) supply sentiment
    gw2_base_price REAL,                  -- baseline captured on first sync
    gw2_base_ratio REAL
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY,
    tick        INTEGER NOT NULL,
    end_tick    INTEGER NOT NULL,
    kind        TEXT NOT NULL,     -- demand | supply | corner | info
    target_type TEXT NOT NULL,     -- item | category | all
    target      TEXT,
    mult        REAL NOT NULL,
    title       TEXT NOT NULL,
    text        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_end ON events(end_tick);
"""


def connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.executescript(SCHEMA)
        _migrate(c)
        _conn = c
    return _conn


def _migrate(c):
    """Bring databases created by older versions up to the current schema."""
    cols = {r["name"] for r in c.execute("PRAGMA table_info(orders)")}
    if "closed_tick" not in cols:
        c.execute("ALTER TABLE orders ADD COLUMN closed_tick INTEGER")
    c.execute("CREATE INDEX IF NOT EXISTS ix_orders_closed ON orders(trader_id, closed_tick)")
    if "license" not in {r["name"] for r in c.execute("PRAGMA table_info(traders)")}:
        c.execute("ALTER TABLE traders ADD COLUMN license INTEGER NOT NULL DEFAULT 0")


@contextmanager
def tx():
    """Serialized transaction. Nested use re-enters without a new BEGIN."""
    with lock:
        c = connect()
        if c.in_transaction:
            yield c
            return
        c.execute("BEGIN IMMEDIATE")
        try:
            yield c
        except BaseException:
            c.execute("ROLLBACK")
            raise
        else:
            c.execute("COMMIT")


def reset_db():
    global _conn
    with lock:
        if _conn is not None:
            _conn.close()
            _conn = None
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(DB_PATH) + suffix)
            if p.exists():
                p.unlink()
        connect()


def get_setting(c, key, default=None):
    row = c.execute("SELECT value FROM world WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(c, key, value):
    c.execute(
        "INSERT INTO world(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )

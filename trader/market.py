"""Order book mechanics: escrow, price-time matching, fees, crafting, NPC vendor.

All functions take an open connection inside a `tx()` and raise MarketError on
invalid actions, which rolls the whole transaction back.
"""
from .settings import S


class MarketError(Exception):
    pass


GOLD, SILVER = 10000, 100


def fmt_money(c: int) -> str:
    g, rest = divmod(abs(int(c)), GOLD)
    s, cu = divmod(rest, SILVER)
    parts = [f"{g}з"] * bool(g) + [f"{s}с"] * bool(s) + [f"{cu}м"] * bool(cu or not (g or s))
    return ("-" if c < 0 else "") + " ".join(parts)


def sale_cut(amount: int) -> int:
    return int(amount * S["ah_cut_pct"] / 100)


def listing_deposit(price: int, qty: int, ttl: int) -> int:
    if S["deposit_pct"] <= 0:
        return 0
    # longer listings cost proportionally more (base = 24 game hours = 144 ticks)
    return max(1, int(price * qty * S["deposit_pct"] / 100 * max(0.5, ttl / 144)))


# ---------------------------------------------------------------- balances

def gold_of(c, trader_id) -> int:
    return c.execute("SELECT gold FROM traders WHERE id=?", (trader_id,)).fetchone()["gold"]


def add_gold(c, trader_id, amount):
    c.execute("UPDATE traders SET gold = gold + ? WHERE id=?", (int(amount), trader_id))


def take_gold(c, trader_id, amount):
    cur = c.execute("UPDATE traders SET gold = gold - ? WHERE id=? AND gold >= ?", (int(amount), trader_id, int(amount)))
    if cur.rowcount == 0:
        raise MarketError(f"Недостатньо золота (потрібно {fmt_money(amount)})")


def qty_of(c, trader_id, item_id) -> int:
    row = c.execute("SELECT qty FROM inventory WHERE trader_id=? AND item_id=?", (trader_id, item_id)).fetchone()
    return row["qty"] if row else 0


def add_items(c, trader_id, item_id, qty):
    if qty <= 0:
        return
    c.execute(
        "INSERT INTO inventory(trader_id, item_id, qty) VALUES(?,?,?) "
        "ON CONFLICT(trader_id, item_id) DO UPDATE SET qty = qty + excluded.qty",
        (trader_id, item_id, int(qty)),
    )


def take_items(c, trader_id, item_id, qty):
    cur = c.execute(
        "UPDATE inventory SET qty = qty - ? WHERE trader_id=? AND item_id=? AND qty >= ?",
        (int(qty), trader_id, item_id, int(qty)),
    )
    if cur.rowcount == 0:
        raise MarketError("Недостатньо предметів в інвентарі")
    c.execute("DELETE FROM inventory WHERE trader_id=? AND item_id=? AND qty <= 0", (trader_id, item_id))


# ---------------------------------------------------------------- book queries

def best_ask(c, item_id, exclude=None):
    row = c.execute(
        "SELECT MIN(price) p FROM orders WHERE item_id=? AND side='sell' AND status='open' AND trader_id != ?",
        (item_id, exclude or -1),
    ).fetchone()
    return row["p"]


def best_bid(c, item_id, exclude=None):
    row = c.execute(
        "SELECT MAX(price) p FROM orders WHERE item_id=? AND side='buy' AND status='open' AND trader_id != ?",
        (item_id, exclude or -1),
    ).fetchone()
    return row["p"]


def sweep_cost(c, item_id, qty, exclude=None):
    """Cost of buying `qty` from current asks. Returns (cost, filled_qty, worst_price)."""
    cost = filled = 0
    worst = None
    for o in c.execute(
        "SELECT price, qty_left FROM orders WHERE item_id=? AND side='sell' AND status='open' AND trader_id != ? "
        "ORDER BY price, id LIMIT 50",
        (item_id, exclude or -1),
    ):
        take = min(qty - filled, o["qty_left"])
        cost += take * o["price"]
        filled += take
        worst = o["price"]
        if filled >= qty:
            break
    return cost, filled, worst


def bid_sweep(c, item_id, qty, exclude=None):
    """Gross proceeds of selling `qty` into current bids. Returns (proceeds, filled_qty)."""
    proceeds = filled = 0
    for o in c.execute(
        "SELECT price, qty_left FROM orders WHERE item_id=? AND side='buy' AND status='open' AND trader_id != ? "
        "ORDER BY price DESC, id LIMIT 50",
        (item_id, exclude or -1),
    ):
        take = min(qty - filled, o["qty_left"])
        proceeds += take * o["price"]
        filled += take
        if filled >= qty:
            break
    return proceeds, filled


# ---------------------------------------------------------------- orders

def _close_order(c, order_id, status, is_bot):
    if is_bot:
        c.execute("DELETE FROM orders WHERE id=?", (order_id,))
    else:
        c.execute("UPDATE orders SET status=?, closed_tick=(SELECT CAST(value AS INTEGER) FROM world WHERE key='tick') "
                  "WHERE id=?", (status, order_id))


def _is_bot(c, trader_id, cache={}):
    if trader_id not in cache:
        cache[trader_id] = c.execute("SELECT kind FROM traders WHERE id=?", (trader_id,)).fetchone()["kind"] == "bot"
    return cache[trader_id]


def _trade(c, tick, item_id, price, qty, buyer, seller):
    proceeds = price * qty
    add_gold(c, seller, proceeds - sale_cut(proceeds))
    add_items(c, buyer, item_id, qty)
    c.execute(
        "INSERT INTO trades(tick, item_id, price, qty, buyer_id, seller_id) VALUES(?,?,?,?,?,?)",
        (tick, item_id, price, qty, buyer, seller),
    )


def place_order(c, trader_id, item_id, side, price, qty, tick, ttl=144):
    """Limit order. Matches immediately against the opposite side, the rest rests
    in the book for `ttl` ticks (ttl=0 → immediate-or-cancel).
    Returns {filled, spent/earned, avg, order_id}."""
    price, qty = int(price), int(qty)
    if qty <= 0 or price <= 0:
        raise MarketError("Ціна та кількість мають бути більші за нуль")
    if side not in ("buy", "sell"):
        raise MarketError("Невідома сторона ордера")

    if side == "sell":
        take_items(c, trader_id, item_id, qty)
        book = c.execute(
            "SELECT id, trader_id, price, qty_left FROM orders "
            "WHERE item_id=? AND side='buy' AND status='open' AND price >= ? AND trader_id != ? "
            "ORDER BY price DESC, id",
            (item_id, price, trader_id),
        ).fetchall()
    else:
        take_gold(c, trader_id, price * qty)
        book = c.execute(
            "SELECT id, trader_id, price, qty_left FROM orders "
            "WHERE item_id=? AND side='sell' AND status='open' AND price <= ? AND trader_id != ? "
            "ORDER BY price, id",
            (item_id, price, trader_id),
        ).fetchall()

    filled = value = 0
    for o in book:
        if filled >= qty:
            break
        q = min(qty - filled, o["qty_left"])
        p = o["price"]  # resting order sets the price
        if side == "sell":
            _trade(c, tick, item_id, p, q, buyer=o["trader_id"], seller=trader_id)
        else:
            _trade(c, tick, item_id, p, q, buyer=trader_id, seller=o["trader_id"])
            add_gold(c, trader_id, (price - p) * q)  # refund reserved difference
        filled += q
        value += p * q
        left = o["qty_left"] - q
        if left == 0:
            _close_order(c, o["id"], "filled", _is_bot(c, o["trader_id"]))
        else:
            c.execute("UPDATE orders SET qty_left=? WHERE id=?", (left, o["id"]))

    remaining = qty - filled
    order_id = None
    if remaining > 0:
        if ttl > 0:
            fee = listing_deposit(price, remaining, ttl) if side == "sell" else 0
            if fee:
                if gold_of(c, trader_id) < fee:
                    raise MarketError(f"Недостатньо золота на депозит лоту ({fmt_money(fee)})")
                take_gold(c, trader_id, fee)
            order_id = c.execute(
                "INSERT INTO orders(trader_id, item_id, side, price, qty, qty_left, status, created_tick, expires_tick, fee_paid) "
                "VALUES(?,?,?,?,?,?,'open',?,?,?)",
                (trader_id, item_id, side, price, qty, remaining, tick, tick + ttl, fee),
            ).lastrowid
        else:
            _refund(c, trader_id, item_id, side, price, remaining)
    elif not _is_bot(c, trader_id):
        # keep a record of fully-filled player orders for history
        order_id = c.execute(
            "INSERT INTO orders(trader_id, item_id, side, price, qty, qty_left, status, created_tick, expires_tick,"
            " closed_tick) VALUES(?,?,?,?,?,0,'filled',?,?,?)",
            (trader_id, item_id, side, price, qty, tick, tick, tick),
        ).lastrowid
    return {"filled": filled, "value": value, "avg": (value / filled) if filled else None, "order_id": order_id}


def _refund(c, trader_id, item_id, side, price, qty):
    if side == "sell":
        add_items(c, trader_id, item_id, qty)
    else:
        add_gold(c, trader_id, price * qty)


def cancel_order(c, order_id, trader_id=None, status="cancelled"):
    o = c.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not o or o["status"] != "open":
        raise MarketError("Ордер не знайдено або вже закритий")
    if trader_id is not None and o["trader_id"] != trader_id:
        raise MarketError("Це не ваш ордер")
    _refund(c, o["trader_id"], o["item_id"], o["side"], o["price"], o["qty_left"])
    _close_order(c, order_id, status, _is_bot(c, o["trader_id"]))


def expire_orders(c, tick):
    rows = c.execute("SELECT id FROM orders WHERE status='open' AND expires_tick <= ?", (tick,)).fetchall()
    for r in rows:
        cancel_order(c, r["id"], status="expired")
    return len(rows)


def market_buy(c, trader_id, item_id, qty, max_price, tick):
    """Buy up to `qty` from the cheapest listings not above max_price."""
    return place_order(c, trader_id, item_id, "buy", max_price, qty, tick, ttl=0)


def market_sell(c, trader_id, item_id, qty, min_price, tick):
    return place_order(c, trader_id, item_id, "sell", max(1, min_price), qty, tick, ttl=0)


def vendor_sell(c, trader_id, item_id, qty):
    item = c.execute("SELECT vendor_price FROM items WHERE id=?", (item_id,)).fetchone()
    take_items(c, trader_id, item_id, qty)
    amount = item["vendor_price"] * qty
    add_gold(c, trader_id, amount)
    return amount


# ---------------------------------------------------------------- crafting

def recipe_ingredients(c, recipe_id):
    return c.execute("SELECT item_id, qty FROM recipe_ingredients WHERE recipe_id=?", (recipe_id,)).fetchall()


def max_crafts(c, trader_id, recipe_id):
    n = None
    for ing in recipe_ingredients(c, recipe_id):
        k = qty_of(c, trader_id, ing["item_id"]) // ing["qty"]
        n = k if n is None else min(n, k)
    return n or 0


def craft(c, trader_id, recipe_id, times=1):
    r = c.execute("SELECT * FROM recipes WHERE id=?", (recipe_id,)).fetchone()
    if not r:
        raise MarketError("Рецепт не знайдено")
    if times <= 0:
        raise MarketError("Кількість має бути більшою за нуль")
    if max_crafts(c, trader_id, recipe_id) < times:
        raise MarketError("Не вистачає інгредієнтів")
    for ing in recipe_ingredients(c, recipe_id):
        take_items(c, trader_id, ing["item_id"], ing["qty"] * times)
    add_items(c, trader_id, r["output_id"], r["output_qty"] * times)
    return r["output_qty"] * times

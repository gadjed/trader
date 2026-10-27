"""HTTP API for the web client."""

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from . import catalog as cat
from . import gw2
from . import market as m
from . import settings
from . import workers
from .db import tx
from .engine import CANDLE_TICKS, TICKS_PER_DAY, day_cycle, engine, game_time
from .seed import starter_kit

router = APIRouter(prefix="/api")

STARTING_GOLD = 25 * m.GOLD
DAY_BUCKETS = TICKS_PER_DAY // CANDLE_TICKS


def player_id(x_player: int | None) -> int:
    if not x_player:
        raise HTTPException(401, "Потрібен вхід")
    return x_player


def run(fn):
    """Execute a market action in a transaction, mapping MarketError to HTTP 400."""
    try:
        with tx() as c:
            return fn(c)
    except m.MarketError as e:
        raise HTTPException(400, str(e))


GRADE_CAPS = [40, 150, 700, 3000]  # base price thresholds for grades 1..4, above → 5


def item_grade(it):
    """0 junk, 1 common … 5 legendary — by base value."""
    if it["is_junk"]:
        return 0
    return 1 + sum(it["base_price"] >= cap for cap in GRADE_CAPS)


def item_view(i):
    it = engine.items[i]
    return {"id": i, "code": it["code"], "name": it["name"], "icon": it["icon"], "category": it["category"],
            "base_price": it["base_price"], "vendor_price": it["vendor_price"], "stack": it["stack"],
            "tier": it["tier"], "grade": item_grade(it), "is_junk": bool(it["is_junk"]), "gather_prof": it["gather_prof"],
            "ref": round(engine.ref[i], 1)}


def recipe_view(r):
    return {"id": r["id"], "profession": r["profession"], "profession_name": cat.CRAFT_PROFS[r["profession"]],
            "output": item_view(r["output_id"]), "output_qty": r["output_qty"], "is_alt": bool(r["is_alt"]),
            "ingredients": [{"item": item_view(i), "qty": q} for i, q in r["ings"]]}


# ---------------------------------------------------------------- session

class Login(BaseModel):
    name: str = Field(min_length=2, max_length=24)


@router.post("/login")
def login(body: Login):
    name = body.name.strip()

    def go(c):
        row = c.execute("SELECT * FROM traders WHERE name=?", (name,)).fetchone()
        if row and row["kind"] != "player":
            raise m.MarketError("Це ім'я зайняте ботом")
        if not row:
            tid = c.execute("INSERT INTO traders(name, kind, gold) VALUES(?, 'player', ?)",
                            (name, STARTING_GOLD)).lastrowid
            starter_kit(c, tid)
            row = c.execute("SELECT * FROM traders WHERE id=?", (tid,)).fetchone()
        return {"id": row["id"], "name": row["name"]}
    return run(go)


@router.get("/state")
def state():
    with tx() as c:
        events = c.execute("SELECT * FROM events WHERE end_tick > ? AND kind != 'corner' ORDER BY id DESC",
                           (engine.tick,)).fetchall()
    return {"tick": engine.tick, "time": game_time(engine.tick), "prewarming": engine.prewarming(),
            "tick_ms": round(engine.tick_ms, 1), "settings": settings.S,
            "active_events": [dict(e) for e in events],
            "gw2": {k: gw2.status[k] for k in ("last_sync", "error", "mapped")}}


# ---------------------------------------------------------------- catalog

@router.get("/catalog")
def catalog():
    return {"items": [item_view(i) for i in engine.items],
            "categories": sorted({it["category"] for it in engine.items.values()}),
            "gather_profs": cat.GATHER_PROFS, "craft_profs": cat.CRAFT_PROFS}


@router.get("/market")
def market_overview():
    b = engine.tick // CANDLE_TICKS
    with tx() as c:
        spark, vol, prev = {}, {}, {}
        for r in c.execute("SELECT item_id, bucket, close, volume FROM candles WHERE bucket > ? ORDER BY bucket",
                           (b - DAY_BUCKETS - 1,)):
            spark.setdefault(r["item_id"], []).append(r["close"])
            vol[r["item_id"]] = vol.get(r["item_id"], 0) + r["volume"]
            prev.setdefault(r["item_id"], r["close"])
        book = {}
        for r in c.execute("SELECT item_id, side, MIN(price) lo, MAX(price) hi, SUM(qty_left) q, COUNT(*) n "
                           "FROM orders WHERE status='open' GROUP BY item_id, side"):
            book[(r["item_id"], r["side"])] = r
    out = []
    for i in engine.items:
        ask, bid = book.get((i, "sell")), book.get((i, "buy"))
        last = engine.last_close.get(i)
        p0 = prev.get(i)
        out.append({**item_view(i), "last": last,
                    "change": (last / p0 - 1) if last and p0 else None,
                    "best_ask": ask["lo"] if ask else None, "ask_qty": ask["q"] if ask else 0,
                    "listings": ask["n"] if ask else 0,
                    "best_bid": bid["hi"] if bid else None, "bid_qty": bid["q"] if bid else 0,
                    "volume": vol.get(i, 0), "spark": spark.get(i, [])[-48:]})
    return out


def recipe_economics(c, r, pid=None):
    """One craft batch at current book depth: ingredient cost vs. buying / selling the result."""
    keep = 1 - settings.S["ah_cut_pct"] / 100
    ings, cost_ask, cost_ref, missing = [], 0, 0, False
    for i, q in r["ings"]:
        sc, filled, _ = m.sweep_cost(c, i, q, exclude=pid)
        ref = engine.ref[i] * q
        short = filled < q
        missing |= short
        cost_ask += sc + (q - filled) * engine.ref[i]  # unavailable part valued at reference price
        cost_ref += ref
        ings.append({"item_id": i, "qty": q, "have": m.qty_of(c, pid, i) if pid else 0,
                     "cost_ask": sc if not short else None, "cost_ref": round(ref)})

    out, n = r["output_id"], r["output_qty"]
    buy_cost, buy_filled, _ = m.sweep_cost(c, out, n, exclude=pid)
    bids, bid_filled = m.bid_sweep(c, out, n, exclude=pid)
    ask = m.best_ask(c, out, exclude=pid)
    if ask:
        list_price = max(1, ask - 1)  # undercut the cheapest lot
    else:  # no competition: at least the reference price, never below the best bid
        list_price = max(round(engine.ref[out]), (m.best_bid(c, out, exclude=pid) or 0) + 1)
    sell_list = list_price * n * keep - m.listing_deposit(list_price, n, 144)
    sell_now = bids * keep if bid_filled >= n else None
    cost = round(cost_ask)
    return {
        "ingredients": ings, "cost_ask": cost, "cost_ref": round(cost_ref), "missing": missing,
        "out_buy": buy_cost if buy_filled >= n else None,
        "out_sell_now": round(sell_now) if sell_now is not None else None,
        "out_list_price": list_price, "out_sell_list": round(sell_list),
        "out_ref": round(engine.ref[out] * n * keep),
        "profit_list": round(sell_list - cost),
        "profit_now": round(sell_now - cost) if sell_now is not None else None,
        "saving": buy_cost - cost if buy_filled >= n else None,
    }


@router.get("/items/{item_id}")
def item_detail(item_id: int, x_player: int | None = Header(None)):
    if item_id not in engine.items:
        raise HTTPException(404, "Немає такого предмета")
    used_in = [recipe_view(r) for r in engine.recipes if any(i == item_id for i, _ in r["ings"])]
    with tx() as c:
        made_by = [dict(recipe_view(r), econ=recipe_economics(c, r, x_player))
                   for r in engine.recipes if r["output_id"] == item_id]
        ask = m.best_ask(c, item_id)
        bid = m.best_bid(c, item_id)
    return {**item_view(item_id), "best_ask": ask, "best_bid": bid, "made_by": made_by, "used_in": used_in,
            "demand_mult": round(engine.demand[item_id], 3), "supply_mult": round(engine.supply[item_id], 3),
            "popularity": round(engine.popularity[item_id], 2),
            "buyers_day": round(engine.arrivals(item_id, cycle=1.0) * TICKS_PER_DAY, 1),
            "demand_day": round(engine.expected_demand(item_id) * TICKS_PER_DAY, 1),
            "sold_day": round(engine.velocity[item_id] * TICKS_PER_DAY, 1),
            "activity_now": round(engine.cycle, 2)}


@router.get("/items/{item_id}/profile")
def demand_profile(item_id: int, days: int = 7):
    """Average units sold per game hour over recent days vs. the expected intraday demand curve."""
    if item_id not in engine.items:
        raise HTTPException(404, "Немає такого предмета")
    days = max(1, min(days, 30))
    b = engine.tick // CANDLE_TICKS
    first = max(0, b - days * TICKS_PER_DAY // CANDLE_TICKS)
    sold = [0] * 24
    with tx() as c:
        for r in c.execute("SELECT bucket, volume FROM candles WHERE item_id=? AND bucket > ?", (item_id, first)):
            sold[(r["bucket"] * CANDLE_TICKS * 10 % 1440) // 60] += r["volume"]
    span_days = max(1.0, (b - first) * CANDLE_TICKS / TICKS_PER_DAY)
    per_hour = engine.expected_demand(item_id) * 6  # 6 ticks per game hour
    now_hour = game_time(engine.tick)["hour"]
    return {"days": round(span_days, 1), "now_hour": now_hour,
            "hours": [{"hour": h, "sold": round(sold[h] / span_days, 2),
                       "expected": round(per_hour * day_cycle(h * 6), 2)} for h in range(24)]}


@router.get("/items/{item_id}/candles")
def candles(item_id: int, tf: int = 1, limit: int = 200):
    tf = max(1, min(tf, 96))
    limit = max(10, min(limit, 500))
    with tx() as c:
        rows = c.execute("SELECT * FROM candles WHERE item_id=? ORDER BY bucket DESC LIMIT ?",
                         (item_id, tf * limit)).fetchall()
    groups = {}
    for r in reversed(rows):
        groups.setdefault(r["bucket"] // tf, []).append(r)
    out = []
    for g, rs in groups.items():
        priced = [r for r in rs if r["close"] is not None]
        traded = [r for r in rs if r["volume"]]
        vol = sum(r["volume"] for r in rs)
        last = rs[-1]
        out.append({
            "bucket": g * tf, "time": game_time(g * tf * CANDLE_TICKS)["label"],
            "open": priced[0]["open"] if priced else None, "close": priced[-1]["close"] if priced else None,
            "high": max((r["high"] for r in priced), default=None),
            "low": min((r["low"] for r in priced), default=None),
            "vwap": sum(r["vwap"] * r["volume"] for r in traded) / vol if vol else None,
            "volume": vol, "trades": sum(r["trades"] for r in rs),
            "best_ask": last["best_ask"], "best_bid": last["best_bid"],
            "ask_qty": last["ask_qty"], "bid_qty": last["bid_qty"], "listings": last["listings"],
        })
    return out


@router.get("/items/{item_id}/book")
def order_book(item_id: int, x_player: int | None = Header(None)):
    """Price levels with time-to-expiry: the soonest-expiring order of each level, and the player's own one."""
    now = engine.tick
    with tx() as c:
        def levels(side, desc):
            out = {}
            for o in c.execute("SELECT trader_id, price, qty_left, created_tick, expires_tick FROM orders "
                               "WHERE item_id=? AND side=? AND status='open'", (item_id, side)):
                lvl = out.setdefault(o["price"], {"price": o["price"], "qty": 0, "orders": 0, "mine": 0,
                                                  "soon_left": None, "soon_total": None,
                                                  "own_left": None, "own_total": None})
                lvl["qty"] += o["qty_left"]
                lvl["orders"] += 1
                left, total = o["expires_tick"] - now, max(1, o["expires_tick"] - o["created_tick"])
                if lvl["soon_left"] is None or left < lvl["soon_left"]:
                    lvl["soon_left"], lvl["soon_total"] = left, total
                if o["trader_id"] == x_player:
                    lvl["mine"] += 1
                    if lvl["own_left"] is None or left < lvl["own_left"]:
                        lvl["own_left"], lvl["own_total"] = left, total
            return sorted(out.values(), key=lambda l: l["price"], reverse=desc)[:40]
        return {"asks": levels("sell", False), "bids": levels("buy", True), "tick": now}


@router.get("/items/{item_id}/trades")
def item_trades(item_id: int, limit: int = 50):
    with tx() as c:
        recent = c.execute(
            "SELECT t.tick, t.price, t.qty, b.name buyer, s.name seller FROM trades t "
            "JOIN traders b ON b.id = t.buyer_id JOIN traders s ON s.id = t.seller_id "
            "WHERE t.item_id=? ORDER BY t.id DESC LIMIT ?", (item_id, min(limit, 200))).fetchall()
        day = c.execute("SELECT price, qty FROM trades WHERE item_id=? AND tick > ?",
                        (item_id, engine.tick - TICKS_PER_DAY)).fetchall()
    # distribution of traded units by price over the last game day
    hist = []
    if day:
        lo, hi = min(r["price"] for r in day), max(r["price"] for r in day)
        bins = min(20, hi - lo + 1)
        width = (hi - lo + 1) / bins
        counts = [0] * bins
        for r in day:
            counts[min(bins - 1, int((r["price"] - lo) / width))] += r["qty"]
        hist = [{"from": int(lo + k * width), "to": int(lo + (k + 1) * width) - 1 if bins > 1 else hi, "qty": n}
                for k, n in enumerate(counts)]
    return {"recent": [dict(r, time=game_time(r["tick"])["label"]) for r in recent], "histogram": hist}


@router.get("/indices")
def indices(limit: int = 200):
    """Category price index: mean(close / base) per category over time."""
    b = engine.tick // CANDLE_TICKS
    with tx() as c:
        rows = c.execute(
            "SELECT c.bucket, i.category, AVG(c.close * 1.0 / i.base_price) idx, SUM(c.volume * c.vwap) turnover "
            "FROM candles c JOIN items i ON i.id = c.item_id WHERE c.bucket > ? AND c.close IS NOT NULL "
            "GROUP BY c.bucket, i.category ORDER BY c.bucket", (b - limit,)).fetchall()
    series = {}
    for r in rows:
        series.setdefault(r["category"], []).append({"bucket": r["bucket"], "idx": round(r["idx"], 4),
                                                     "turnover": r["turnover"] or 0})
    return {"series": series, "labels": sorted({r["bucket"] for r in rows})}


# ---------------------------------------------------------------- crafting tree

def _tree(c, item_id, qty, depth, seen, recipe_id=None):
    it = engine.items[item_id]
    ask_cost, filled, _ = m.sweep_cost(c, item_id, qty)
    node = {"item": item_view(item_id), "qty": qty,
            "buy_cost": ask_cost if filled >= qty else None,
            "ref_cost": round(engine.ref[item_id] * qty), "recipe": None, "craft_cost": None}
    recs = [r for r in engine.recipes if r["output_id"] == item_id
            and (r["id"] == recipe_id if recipe_id is not None else not r["is_alt"])]
    if recs and depth < 7 and item_id not in seen:
        r = recs[0]
        batches = -(-qty // r["output_qty"])
        children = [_tree(c, i, q * batches, depth + 1, seen | {item_id}) for i, q in r["ings"]]
        craft_cost = sum(ch["best_cost"] for ch in children)
        node["recipe"] = {"id": r["id"], "profession": cat.CRAFT_PROFS[r["profession"]],
                          "output_qty": r["output_qty"], "batches": batches, "children": children}
        node["craft_cost"] = craft_cost
    options = [x for x in (node["buy_cost"], node["craft_cost"]) if x is not None]
    node["best_cost"] = min(options) if options else node["ref_cost"]
    node["gather"] = cat.GATHER_PROFS.get(it["gather_prof"]) if it["gather_prof"] else None
    return node


@router.get("/craft/tree/{item_id}")
def craft_tree(item_id: int, qty: int = 1, recipe_id: int | None = None):
    with tx() as c:
        return _tree(c, item_id, max(1, min(qty, 1000)), 0, frozenset(), recipe_id)


@router.get("/craft/recipes")
def recipes(x_player: int | None = Header(None)):
    with tx() as c:
        inv = {r["item_id"]: r["qty"] for r in c.execute("SELECT item_id, qty FROM inventory WHERE trader_id=?",
                                                         (x_player or -1,))}
        asks = {r["item_id"]: r["p"] for r in c.execute(
            "SELECT item_id, MIN(price) p FROM orders WHERE side='sell' AND status='open' GROUP BY item_id")}
        # which of my hired crafters can make each recipe
        known = {}
        for w in c.execute("SELECT name, profession, level FROM workers WHERE owner_id=? AND role='crafter'",
                           (x_player or -1,)):
            for r in workers.known_recipes(engine, w["profession"], w["level"]):
                known.setdefault(r["id"], []).append(w["name"])
    out = []
    cut = 1 - settings.S["ah_cut_pct"] / 100
    for r in engine.recipes:
        v = recipe_view(r)
        cost_ref = sum(engine.ref[i] * q for i, q in r["ings"])
        cost_ask = sum((asks.get(i) or engine.ref[i]) * q for i, q in r["ings"])
        value = engine.ref[r["output_id"]] * r["output_qty"] * cut
        v.update(cost_ref=round(cost_ref), cost_ask=round(cost_ask), value=round(value),
                 profit=round(value - cost_ask), margin=round(value / cost_ask - 1, 3) if cost_ask else None,
                 can_craft=min((inv.get(i, 0) // q for i, q in r["ings"]), default=0),
                 have=[min(inv.get(i, 0), q) for i, q in r["ings"]],
                 sold_day=round(engine.velocity[r["output_id"]] * TICKS_PER_DAY, 1), known_by=known.get(r["id"], []))
        out.append(v)
    return out


class CraftReq(BaseModel):
    recipe_id: int
    times: int = Field(1, ge=1, le=1000)


@router.post("/craft")
def do_craft(body: CraftReq, x_player: int | None = Header(None)):
    pid = player_id(x_player)
    return run(lambda c: {"crafted": m.craft(c, pid, body.recipe_id, body.times)})


# ---------------------------------------------------------------- player

def net_worth(c, trader_id, gold):
    inv = sum(engine.ref[r["item_id"]] * r["qty"] for r in
              c.execute("SELECT item_id, qty FROM inventory WHERE trader_id=?", (trader_id,)))
    esc = 0
    for o in c.execute("SELECT item_id, side, price, qty_left FROM orders WHERE trader_id=? AND status='open'",
                       (trader_id,)):
        esc += o["price"] * o["qty_left"] if o["side"] == "buy" else engine.ref[o["item_id"]] * o["qty_left"]
    return round(gold + inv + esc)


@router.get("/me")
def me(x_player: int | None = Header(None)):
    pid = player_id(x_player)
    with tx() as c:
        t = c.execute("SELECT * FROM traders WHERE id=? AND kind='player'", (pid,)).fetchone()
        if not t:
            raise HTTPException(401, "Гравця не знайдено")
        inv = [dict(item=item_view(r["item_id"]), qty=r["qty"], value=round(engine.ref[r["item_id"]] * r["qty"]),
                    sold_day=round(engine.velocity[r["item_id"]] * TICKS_PER_DAY, 1))
               for r in c.execute("SELECT item_id, qty FROM inventory WHERE trader_id=? ORDER BY item_id", (pid,))]
        escrow = c.execute("SELECT COALESCE(SUM(price*qty_left),0) v FROM orders WHERE trader_id=? AND side='buy' "
                           "AND status='open'", (pid,)).fetchone()["v"]
        worth = net_worth(c, pid, t["gold"])
        favorites = [r["item_id"] for r in c.execute("SELECT item_id FROM favorites WHERE trader_id=?", (pid,))]
    return {"id": pid, "name": t["name"], "gold": t["gold"], "escrow": escrow, "net_worth": worth,
            "favorites": favorites,
            "start_gold": STARTING_GOLD, "inventory": inv}


@router.post("/favorites/{item_id}")
def toggle_favorite(item_id: int, x_player: int | None = Header(None)):
    pid = player_id(x_player)
    if item_id not in engine.items:
        raise HTTPException(404, "Немає такого предмета")
    with tx() as c:
        removed = c.execute("DELETE FROM favorites WHERE trader_id=? AND item_id=?", (pid, item_id)).rowcount
        if not removed:
            c.execute("INSERT INTO favorites(trader_id, item_id) VALUES(?,?)", (pid, item_id))
        favorites = [r["item_id"] for r in c.execute("SELECT item_id FROM favorites WHERE trader_id=?", (pid,))]
    return {"favorite": not removed, "favorites": favorites}


@router.get("/me/orders")
def my_orders(x_player: int | None = Header(None)):
    pid = player_id(x_player)
    with tx() as c:
        rows = c.execute("SELECT * FROM orders WHERE trader_id=? ORDER BY status='open' DESC, id DESC LIMIT 200",
                         (pid,)).fetchall()
    return [dict(r, item=item_view(r["item_id"]), created=game_time(r["created_tick"])["label"],
                 expires_in=r["expires_tick"] - engine.tick) for r in rows]


@router.get("/me/feed")
def my_feed(after_trade: int | None = None, after_tick: int | None = None, after_wlog: int | None = None,
            x_player: int | None = Header(None)):
    """What happened to the player's orders since the given cursors. Without cursors only returns them,
    so a freshly opened page doesn't replay old history."""
    pid = player_id(x_player)
    with tx() as c:
        last_trade = c.execute("SELECT COALESCE(MAX(id), 0) m FROM trades WHERE buyer_id=? OR seller_id=?",
                               (pid, pid)).fetchone()["m"]
        last_log = c.execute("SELECT COALESCE(MAX(id), 0) m FROM worker_log WHERE owner_id=?", (pid,)).fetchone()["m"]
        out = {"cursor": {"trade": last_trade, "tick": engine.tick, "wlog": last_log},
               "trades": [], "expired": [], "workers": []}
        if after_trade is None or after_tick is None:
            return out
        out["workers"] = [dict(r) for r in c.execute(
            "SELECT id, worker_id, kind, text FROM worker_log WHERE owner_id=? AND id > ? ORDER BY id LIMIT 50",
            (pid, after_wlog or 0))]
        trades = c.execute("SELECT * FROM trades WHERE (buyer_id=? OR seller_id=?) AND id > ? ORDER BY id LIMIT 200",
                           (pid, pid, after_trade)).fetchall()
        expired = c.execute("SELECT * FROM orders WHERE trader_id=? AND status='expired' AND closed_tick > ? "
                            "ORDER BY id LIMIT 50", (pid, after_tick)).fetchall()
    cut = settings.S["ah_cut_pct"] / 100
    out["trades"] = [{"id": t["id"], "item": item_view(t["item_id"]), "price": t["price"], "qty": t["qty"],
                      "side": "buy" if t["buyer_id"] == pid else "sell",
                      "net": t["price"] * t["qty"] - (int(t["price"] * t["qty"] * cut) if t["seller_id"] == pid else 0)}
                     for t in trades]
    out["expired"] = [{"id": o["id"], "item": item_view(o["item_id"]), "side": o["side"], "price": o["price"],
                       "qty": o["qty"], "qty_left": o["qty_left"]} for o in expired]
    return out


@router.get("/me/trades")
def my_trades(x_player: int | None = Header(None)):
    pid = player_id(x_player)
    with tx() as c:
        rows = c.execute(
            "SELECT t.*, b.name buyer, s.name seller FROM trades t JOIN traders b ON b.id=t.buyer_id "
            "JOIN traders s ON s.id=t.seller_id WHERE buyer_id=? OR seller_id=? ORDER BY t.id DESC LIMIT 200",
            (pid, pid)).fetchall()
    return [dict(r, item=item_view(r["item_id"]), side="buy" if r["buyer_id"] == pid else "sell",
                 time=game_time(r["tick"])["label"]) for r in rows]


class OrderReq(BaseModel):
    item_id: int
    side: str
    price: int = Field(ge=1)
    qty: int = Field(ge=1, le=100000)
    hours: int = Field(24, ge=0, le=72)  # game hours; 0 = immediate-or-cancel


@router.post("/orders")
def place(body: OrderReq, x_player: int | None = Header(None)):
    pid = player_id(x_player)
    return run(lambda c: m.place_order(c, pid, body.item_id, body.side, body.price, body.qty, engine.tick,
                                       ttl=body.hours * 6))


@router.post("/orders/{order_id}/cancel")
def cancel(order_id: int, x_player: int | None = Header(None)):
    pid = player_id(x_player)
    return run(lambda c: m.cancel_order(c, order_id, pid) or {"ok": True})


@router.get("/quote")
def quote(item_id: int, side: str, qty: int, price: int | None = None, hours: int = 24,
          x_player: int | None = Header(None)):
    """Preview of fees and immediate fill for an order form."""
    with tx() as c:
        if side == "buy":
            cost, filled, worst = m.sweep_cost(c, item_id, qty)
            return {"instant_qty": filled, "instant_cost": cost, "worst_price": worst}
        bids = c.execute("SELECT price, qty_left FROM orders WHERE item_id=? AND side='buy' AND status='open' "
                         "AND price >= ? ORDER BY price DESC", (item_id, price or 1)).fetchall()
    filled = proceeds = 0
    for b in bids:
        q = min(qty - filled, b["qty_left"])
        filled += q
        proceeds += q * b["price"]
        if filled >= qty:
            break
    rest = qty - filled
    eta = None
    if rest and price:
        with tx() as c:
            eta = engine.sell_eta(c, item_id, price, rest, exclude=x_player)
    return {"instant_qty": filled, "instant_proceeds": proceeds - m.sale_cut(proceeds),
            "eta_hours": round(eta / 6, 1) if eta is not None else None,
            "deposit": m.listing_deposit(price or 1, rest, hours * 6) if rest and hours else 0,
            "cut_pct": settings.S["ah_cut_pct"],
            "net_if_sold": (price or 0) * qty - m.sale_cut((price or 0) * qty)}


class VendorReq(BaseModel):
    item_id: int
    qty: int = Field(ge=1)


@router.post("/vendor")
def vendor(body: VendorReq, x_player: int | None = Header(None)):
    pid = player_id(x_player)
    return run(lambda c: {"earned": m.vendor_sell(c, pid, body.item_id, body.qty)})


# ---------------------------------------------------------------- workers

def wrun(fn):
    try:
        with tx() as c:
            return fn(c)
    except (m.MarketError, KeyError, ValueError) as e:
        raise HTTPException(400, str(e))


@router.get("/workers")
def workers_overview(x_player: int | None = Header(None)):
    pid = player_id(x_player)
    with tx() as c:
        return workers.overview(c, engine, pid)


class HireReq(BaseModel):
    days: int = 3
    food: bool = False
    tool: bool = False


@router.post("/workers/{worker_id}/hire")
def hire_worker(worker_id: int, body: HireReq, x_player: int | None = Header(None)):
    pid = player_id(x_player)
    return wrun(lambda c: {"wage": workers.hire(c, engine, pid, worker_id, body.days, body.food, body.tool)})


@router.post("/workers/{worker_id}/fire")
def fire_worker(worker_id: int, x_player: int | None = Header(None)):
    pid = player_id(x_player)
    return wrun(lambda c: {"penalty": workers.fire(c, engine, pid, worker_id)})


class RenewReq(BaseModel):
    days: int = 3


@router.post("/workers/{worker_id}/renew")
def renew_worker(worker_id: int, body: RenewReq, x_player: int | None = Header(None)):
    pid = player_id(x_player)
    return wrun(lambda c: {"wage": workers.renew(c, engine, pid, worker_id, body.days)})


class EquipReq(BaseModel):
    item_id: int


@router.post("/workers/{worker_id}/equip")
def equip_worker(worker_id: int, body: EquipReq, x_player: int | None = Header(None)):
    pid = player_id(x_player)
    return wrun(lambda c: workers.equip(c, engine, pid, worker_id, body.item_id) or {"ok": True})


@router.post("/workers/{worker_id}/unequip")
def unequip_worker(worker_id: int, x_player: int | None = Header(None)):
    pid = player_id(x_player)
    return wrun(lambda c: {"returned": workers.unequip(c, engine, pid, worker_id)})


class FocusReq(BaseModel):
    item_id: int | None = None


@router.post("/workers/{worker_id}/focus")
def focus_worker(worker_id: int, body: FocusReq, x_player: int | None = Header(None)):
    pid = player_id(x_player)
    return wrun(lambda c: workers.set_focus(c, engine, pid, worker_id, body.item_id) or {"ok": True})


class TasksReq(BaseModel):
    tasks: list[dict]


@router.post("/workers/{worker_id}/tasks")
def tasks_worker(worker_id: int, body: TasksReq, x_player: int | None = Header(None)):
    pid = player_id(x_player)
    return wrun(lambda c: workers.set_tasks(c, engine, pid, worker_id, body.tasks) or {"ok": True})


@router.post("/license/upgrade")
def license_upgrade(x_player: int | None = Header(None)):
    pid = player_id(x_player)
    return wrun(lambda c: {"slots": workers.upgrade_license(c, pid)})


# ---------------------------------------------------------------- world

@router.get("/news")
def news(limit: int = 60):
    with tx() as c:
        rows = c.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r, time=game_time(r["tick"])["label"], active=r["end_tick"] > engine.tick) for r in rows]


@router.get("/leaderboard")
def leaderboard():
    with tx() as c:
        traders = c.execute("SELECT id, name, kind, strategy, profession, gold FROM traders "
                            "WHERE strategy IS NULL OR strategy NOT IN ('consumer')").fetchall()
        rows = [dict(t, net_worth=net_worth(c, t["id"], t["gold"]),
                     profession_name=(cat.GATHER_PROFS | cat.CRAFT_PROFS).get(t["profession"] or "", ""))
                for t in traders]
    rows.sort(key=lambda r: -r["net_worth"])
    return rows[:40]


@router.get("/settings")
def get_settings():
    return settings.describe()


@router.post("/settings")
def set_settings(body: dict):
    try:
        with tx() as c:
            settings.save(c, body)
    except KeyError as e:
        raise HTTPException(400, f"Невідомий параметр {e}")
    if "gw2_sync" in body:
        if settings.S["gw2_sync"]:
            gw2_syncer.wake.set()
        else:
            gw2.disable(engine)
    return settings.describe()


@router.post("/settings/preset/{name}")
def preset(name: str):
    if name not in settings.PRESETS:
        raise HTTPException(404, "Невідомий пресет")
    with tx() as c:
        settings.apply_preset(c, name)
    return settings.describe()


class EventReq(BaseModel):
    kind: str


@router.post("/admin/event")
def trigger_event(body: EventReq):
    if body.kind not in ("demand_up", "demand_down", "supply_up", "supply_down", "corner"):
        raise HTTPException(400, "Невідомий тип події")
    with tx() as c:
        title = engine._maybe_event(c, force_kind=body.kind)
    if not title:
        raise HTTPException(400, "Подію не вдалося створити (немає відповідних лотів)")
    return {"title": title}


@router.get("/gw2")
def gw2_status():
    return gw2.status


@router.post("/gw2/sync")
def gw2_sync_now():
    try:
        gw2.sync_once(engine)
    except Exception as e:
        raise HTTPException(502, f"GW2 API недоступне: {e}")
    return gw2.status


@router.post("/gw2/rebase")
def gw2_rebase():
    gw2.reset_baseline(engine)
    return {"ok": True}


gw2_syncer = gw2.Syncer(engine)

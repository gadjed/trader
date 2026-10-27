"""Market life simulator.

Every tick (10 game minutes) bots act on the shared order book:
  * gatherers  – produce raw materials of their profession and list them,
                 competing on price and dumping when overstocked;
  * crafters   – buy ingredients when a recipe is profitable, craft, sell output,
                 and post standing buy orders for missing ingredients;
  * consumers  – NPC demand (taverns, army, court...) buying below their valuation
                 and removing goods from the economy;
  * speculators– buy listings far below the reference price and relist higher;
  * dumpers    – "newbies" who liquidate loot cheaply or to the NPC vendor.
Random events shift demand/supply (wars, patches, bot farms, cartels), creating
deficits, oversaturation and price shocks. Candles are aggregated every CANDLE_TICKS.

To look like people rather than a script:
  * player bots play in sessions (log in, act, log off) and more of them are online
    in the evening than at night (`day_cycle`);
  * sellers have pricing styles – undercutters, matchers and "I know my price" –
    and only fight for the top of the book when the item actually sells;
  * before listing, a seller estimates whether the lot will sell before it expires
    (queue of cheaper lots vs. observed sales velocity) and otherwise keeps the stock;
  * NPC demand arrives per item as a Poisson stream whose rate depends on item
    popularity, demand drift, events and time of day.
"""
import json
import logging
import math
import random
import threading
import time
from contextlib import contextmanager

from . import catalog as cat
from . import market as m
from . import workers
from .db import get_setting, set_setting, tx
from .settings import S, load as load_settings

log = logging.getLogger("trader.engine")

CANDLE_TICKS = 3          # 30 game minutes per candle
TICKS_PER_DAY = 144       # 10 game minutes per tick
PREWARM_TICKS = 6 * TICKS_PER_DAY
KEEP_CANDLES = 4000
KEEP_TRADE_TICKS = 3000

# chance to act per tick while online
ACTIVITY = {"gatherer": 0.95, "crafter": 0.9, "speculator": 0.6, "dumper": 0.8}
SESSION_TICKS = 40        # mean session length (~7 game hours)
OFFLINE_TICKS = 35        # mean time offline at an average hour of day
CONSUMER_PICKS = 3.4      # NPC buyer arrivals per consumer per tick (on average)
VELOCITY_WINDOW = TICKS_PER_DAY
STYLES = (("undercut", 35), ("match", 25), ("value", 40))


def day_cycle(tick):
    """Share of players online by game hour: peak ~20:00, trough ~08:00, mean 1."""
    hour = (tick * 10 % 1440) / 60
    return 1 + 0.55 * math.cos(2 * math.pi * (hour - 20) / 24)


def poisson(rng, lam):
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    k, p, limit = 0, 1.0, math.exp(-lam)
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def game_time(tick):
    minutes = tick * 10
    day, rem = divmod(minutes, 1440)
    return {"day": day + 1, "hour": rem // 60, "minute": rem % 60,
            "label": f"День {day + 1}, {rem // 60:02d}:{rem % 60:02d}"}


@contextmanager
def savepoint(c):
    """Isolate one bot action: a failed action is rolled back without losing the tick."""
    c.execute("SAVEPOINT act")
    try:
        yield
    except m.MarketError:
        c.execute("ROLLBACK TO act")
    finally:
        c.execute("RELEASE act")


class Engine:
    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.tick = 0
        self.items: dict[int, dict] = {}
        self.by_code: dict[str, int] = {}
        self.recipes: list[dict] = []
        self.recipes_by_prof: dict[str, list[dict]] = {}
        self.keep_by_prof: dict[str, dict[int, int]] = {}
        self.gather_pool: dict[str, list[int]] = {}
        self.junk: list[int] = []
        self.bots: list[dict] = []
        self.ref: dict[int, float] = {}
        self.last_close: dict[int, int | None] = {}
        self.drift: dict[int, float] = {}
        self.ext: dict[int, tuple[float, float]] = {}
        self.demand: dict[int, float] = {}
        self.supply: dict[int, float] = {}
        self.recipe_score: dict[int, float] = {}
        self.popularity: dict[int, float] = {}
        self.base_arrivals: dict[int, float] = {}   # NPC buyers per tick at neutral conditions
        self.buyers_of: dict[int, list[dict]] = {}  # consumer bots interested in the item
        self.velocity: dict[int, float] = {}        # observed units sold per tick (EMA over a day)
        self.cycle = 1.0
        self.tick_ms = 0.0
        self._stop = threading.Event()
        self._thread = None

    # ------------------------------------------------------------ loading

    def load(self, c):
        load_settings(c)
        self.tick = int(get_setting(c, "tick", 0))
        for r in c.execute("SELECT * FROM items"):
            self.items[r["id"]] = dict(r)
            self.by_code[r["code"]] = r["id"]
        self.junk = [i for i, it in self.items.items() if it["is_junk"]]
        for prof in cat.GATHER_PROFS:
            self.gather_pool[prof] = [i for i, it in self.items.items() if it["gather_prof"] == prof]

        ings = {}
        for r in c.execute("SELECT * FROM recipe_ingredients"):
            ings.setdefault(r["recipe_id"], []).append((r["item_id"], r["qty"]))
        for r in c.execute("SELECT * FROM recipes ORDER BY id"):
            rec = dict(r, ings=ings[r["id"]])
            self.recipes.append(rec)
            self.recipes_by_prof.setdefault(r["profession"], []).append(rec)
            keep = self.keep_by_prof.setdefault(r["profession"], {})
            for i, q in rec["ings"]:
                keep[i] = max(keep.get(i, 0), q * 3)  # enough for a few batches of own recipes
            self.recipe_score[r["id"]] = 0.0

        # item popularity: a stable per-item trait (some goods are hot, some niche)
        for i, it in self.items.items():
            self.popularity[i] = math.exp(random.Random(it["code"]).gauss(0, 0.5) - 0.125)

        self.bots = []
        self.base_arrivals = {i: 0.0 for i in self.items}
        self.buyers_of = {i: [] for i in self.items}
        for r in c.execute("SELECT * FROM traders WHERE kind='bot'"):
            b = dict(r)
            b["p"] = json.loads(b["params"])
            self.bots.append(b)
            if b["strategy"] == "consumer":
                cats = b["p"]["categories"]
                pool = [i for i, it in self.items.items() if cats is None or it["category"] in cats]
                weights = [self.items[i]["consume_weight"] * (1.0 if cats else 0.4) for i in pool]
                total = sum(weights)
                for i, w in zip(pool, weights):
                    self.base_arrivals[i] += CONSUMER_PICKS * w / total
                    self.buyers_of[i].append(b)
            else:
                brng = random.Random(b["id"])
                b["p"].setdefault("style", brng.choices([s for s, _ in STYLES], [w for _, w in STYLES])[0])
                b["online"] = brng.random() < SESSION_TICKS / (SESSION_TICKS + OFFLINE_TICKS)
                b["markdown"] = {}  # item -> price factor learned from lots that expired unsold
        self.base_arrivals = {i: a * self.popularity[i] for i, a in self.base_arrivals.items()}
        self.consumer_ids = [b["id"] for b in self.bots if b["strategy"] == "consumer"]
        self.players = [b for b in self.bots if b["strategy"] != "consumer"]
        self.bot_by_id = {b["id"]: b for b in self.bots}

        sold = {r["item_id"]: r["q"] for r in c.execute(
            "SELECT item_id, SUM(qty) q FROM trades WHERE tick > ? GROUP BY item_id", (self.tick - VELOCITY_WINDOW,))}
        self.velocity = {i: sold.get(i, 0) / VELOCITY_WINDOW for i in self.items}

        for r in c.execute("SELECT * FROM market_state"):
            self.drift[r["item_id"]] = r["drift"]
            self.ext[r["item_id"]] = (r["ext_mult"], r["ext_supply"])

        # reference prices from recent candles, else base price
        for i, it in self.items.items():
            self.ref[i] = float(it["base_price"])
            self.last_close[i] = None
        rows = c.execute(
            "SELECT item_id, close, vwap FROM candles WHERE bucket >= ? AND close IS NOT NULL ORDER BY bucket",
            (self.tick // CANDLE_TICKS - 20,),
        ).fetchall()
        for r in rows:
            self.ref[r["item_id"]] = r["vwap"] or r["close"]
            self.last_close[r["item_id"]] = r["close"]
        last = c.execute(
            "SELECT item_id, close FROM candles c1 WHERE bucket = "
            "(SELECT MAX(bucket) FROM candles c2 WHERE c2.item_id = c1.item_id AND c2.close IS NOT NULL)"
        ).fetchall()
        for r in last:
            self.last_close[r["item_id"]] = r["close"]
        self._compute_modifiers(c)
        workers.refresh_market(c, self)  # an old world shouldn't wait hours for its first job seekers

    # ------------------------------------------------------------ thread

    def start(self):
        self._thread = threading.Thread(target=self._run, name="market-engine", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def prewarming(self):
        return self.tick < PREWARM_TICKS

    def _run(self):
        while not self._stop.is_set():
            started = time.monotonic()
            if S["paused"] and not self.prewarming():
                self._stop.wait(0.3)
                continue
            try:
                self.step()
            except Exception:
                log.exception("tick %s failed", self.tick)
            if self.prewarming():
                time.sleep(0.001)  # let API requests in between fast-forward ticks
                continue
            self._stop.wait(max(0.0, S["tick_seconds"] - (time.monotonic() - started)))

    def step(self):
        t0 = time.perf_counter()
        with tx() as c:
            self._tick(c)
        self.tick_ms = (time.perf_counter() - t0) * 1000

    # ------------------------------------------------------------ tick

    def _tick(self, c):
        self.tick += 1
        set_setting(c, "tick", self.tick)
        self._learn_from_expired(c)
        m.expire_orders(c, self.tick)
        self._compute_modifiers(c)
        self._maybe_event(c)

        rng = self.rng
        self.cycle = day_cycle(self.tick)
        act_mult = S["bot_activity"]
        bots = self.players[:]
        rng.shuffle(bots)
        for b in bots:
            if b["online"]:
                if rng.random() < 1 / SESSION_TICKS:
                    b["online"] = False
                    continue
            elif rng.random() < self.cycle * act_mult / OFFLINE_TICKS:
                b["online"] = True
                self._reprice(c, b, n=3, on_login=True)  # first look at the market after logging in
            else:
                continue
            p = ACTIVITY[b["strategy"]]
            if rng.random() < p:
                getattr(self, "_act_" + b["strategy"])(c, b)

        self._npc_demand(c)
        workers.tick(c, self)

        # consumers use up what they bought
        c.execute(f"DELETE FROM inventory WHERE trader_id IN ({','.join(map(str, self.consumer_ids))})")
        self._update_refs(c)
        if self.tick % 10 == 0:
            self._housekeeping(c)
        if self.tick % CANDLE_TICKS == CANDLE_TICKS - 1:
            self._build_candles(c, self.tick // CANDLE_TICKS)

    # ------------------------------------------------------------ fundamentals

    def _compute_modifiers(self, c):
        demand = {i: self.drift[i] * self.ext[i][0] for i in self.items}
        supply = {i: self.ext[i][1] for i in self.items}
        for ev in c.execute("SELECT * FROM events WHERE end_tick > ? AND kind IN ('demand','supply')", (self.tick,)):
            dur = max(1, ev["end_tick"] - ev["tick"])
            fade = min(1.0, (ev["end_tick"] - self.tick) / (0.3 * dur))
            eff = 1 + (ev["mult"] - 1) * fade
            target = demand if ev["kind"] == "demand" else supply
            if ev["target_type"] == "category":
                cats = set(json.loads(ev["target"]))
                hit = [i for i, it in self.items.items() if it["category"] in cats]
            else:
                hit = [self.by_code[ev["target"]]]
            for i in hit:
                target[i] *= eff
        self.demand, self.supply = demand, supply

    def _maybe_event(self, c, force_kind=None):
        if not force_kind and self.rng.random() > S["event_rate"] / 110:
            return None
        rng = self.rng
        kind = force_kind or rng.choices(
            ["demand_up", "demand_down", "supply_up", "supply_down", "corner"], [30, 15, 25, 20, 10])[0]
        dur = rng.randint(72, 288)
        version = f"1.{rng.randint(2, 40)}.{rng.randint(0, 9)}"
        if kind in ("demand_up", "demand_down"):
            cats, title, text = rng.choice(cat.DEMAND_UP if kind == "demand_up" else cat.DEMAND_DOWN)
            mult = rng.uniform(1.5, 2.3) if kind == "demand_up" else rng.uniform(0.35, 0.65)
            row = ("demand", "category", json.dumps(cats, ensure_ascii=False), mult, title, text)
        elif kind in ("supply_up", "supply_down"):
            pool = [i for i, it in self.items.items() if it["gather_prof"]]
            item = self.items[rng.choice(pool)]
            title, text = rng.choice(cat.SUPPLY_UP if kind == "supply_up" else cat.SUPPLY_DOWN)
            mult = rng.uniform(2.0, 4.0) if kind == "supply_up" else rng.uniform(0.1, 0.35)
            row = ("supply", "item", item["code"], mult, title.format(item=item["name"], v=version), text)
        else:
            item_id = self._corner(c)
            if item_id is None:
                return None
            title, text = cat.CORNER
            row = ("corner", "item", self.items[item_id]["code"], 1.0,
                   title.format(item=self.items[item_id]["name"]), text)
            dur = 1
        c.execute(
            "INSERT INTO events(tick, end_tick, kind, target_type, target, mult, title, text) VALUES(?,?,?,?,?,?,?,?)",
            (self.tick, self.tick + dur, *row),
        )
        return row[4]

    def _corner(self, c):
        """A speculator buys out the cheap end of a book and relists at a double price."""
        specs = [b for b in self.bots if b["strategy"] == "speculator"]
        cands = [r["item_id"] for r in c.execute(
            "SELECT item_id, SUM(qty_left*price) v FROM orders WHERE side='sell' AND status='open' "
            "GROUP BY item_id HAVING v BETWEEN 2000 AND 400000")]
        if not specs or not cands:
            return None
        b = self.rng.choice(specs)
        item_id = self.rng.choice(cands)
        ref = self.ref[item_id]
        m.add_gold(c, b["id"], 50 * m.GOLD)
        with savepoint(c):
            res = m.market_buy(c, b["id"], item_id, 10_000, int(ref * 1.3), self.tick)
            if res["filled"]:
                m.place_order(c, b["id"], item_id, "sell", int(ref * 2), res["filled"], self.tick, ttl=288)
        return item_id

    def _update_refs(self, c):
        rows = c.execute(
            "SELECT item_id, SUM(price*qty) v, SUM(qty) q FROM trades WHERE tick=? GROUP BY item_id", (self.tick,))
        sold = {}
        for r in rows:
            i = r["item_id"]
            sold[i] = r["q"]
            vwap = r["v"] / r["q"]
            a = min(0.5, 0.08 + 0.3 * r["q"] / self.items[i]["stack"])
            self.ref[i] = self.ref[i] * (1 - a) + vwap * a
        k = 1 / VELOCITY_WINDOW
        for i in self.items:
            self.velocity[i] = self.velocity[i] * (1 - k) + sold.get(i, 0) * k
        # lots that sit far below the reference slowly pull it down
        for r in c.execute("SELECT item_id, MIN(price) p FROM orders WHERE side='sell' AND status='open' GROUP BY item_id"):
            i = r["item_id"]
            if r["p"] < self.ref[i]:
                self.ref[i] = self.ref[i] * 0.996 + r["p"] * 0.004

    def _learn_from_expired(self, c):
        """A lot that sat unsold until expiry means the price was too high – for that seller and the market."""
        for o in c.execute("SELECT trader_id, item_id, price, qty, qty_left FROM orders "
                           "WHERE status='open' AND side='sell' AND expires_tick <= ?", (self.tick,)):
            i = o["item_id"]
            if o["price"] >= self.ref[i] * 0.9:
                self.ref[i] *= 0.98 if o["qty_left"] == o["qty"] else 0.995
            b = self.bot_by_id.get(o["trader_id"])
            if b and "markdown" in b:
                b["markdown"][i] = max(0.5, b["markdown"].get(i, 1.0) * 0.88)

    def value_of(self, item_id):
        it = self.items[item_id]
        return it["base_price"] * S["demand_mult"] * self.demand[item_id]

    def arrivals(self, item_id, cycle=None):
        """Expected NPC buyers per tick for the item right now."""
        return self.base_arrivals[item_id] * self.demand[item_id] * (self.cycle if cycle is None else cycle)

    def expected_demand(self, item_id):
        """Expected units NPCs want per tick at fair prices (buyers × typical purchase × ~50% acceptance)."""
        it = self.items[item_id]
        units = min(300 / it["base_price"], 2 * it["stack"])
        return self.arrivals(item_id, cycle=1.0) * units * 0.5

    def sell_rate(self, item_id):
        """Units per tick a seller can count on: observed sales, or a cautious share of expected demand."""
        return max(self.velocity[item_id], 0.3 * self.expected_demand(item_id))

    def sell_eta(self, c, item_id, price, qty, exclude=None):
        """Estimated ticks until a lot at `price` sells out, given cheaper lots queued ahead of it."""
        ahead = c.execute(
            "SELECT COALESCE(SUM(qty_left), 0) q FROM orders WHERE item_id=? AND side='sell' AND status='open' "
            "AND price <= ? AND trader_id != ?", (item_id, price, exclude or -1)).fetchone()["q"]
        rate = self.sell_rate(item_id)
        # buyers with lower valuations ignore expensive lots
        rate *= min(1.0, (self.ref[item_id] / max(1, price)) ** 2)
        return (ahead + qty) / rate if rate > 1e-9 else None

    # ------------------------------------------------------------ selling helpers

    def _open_sells(self, c, bot_id, item_id=None):
        if item_id is None:
            return c.execute("SELECT COUNT(*) n FROM orders WHERE trader_id=? AND side='sell' AND status='open'",
                             (bot_id,)).fetchone()["n"]
        return c.execute("SELECT COUNT(*) n FROM orders WHERE trader_id=? AND item_id=? AND side='sell' AND status='open'",
                         (bot_id, item_id)).fetchone()["n"]

    def _liquid(self, item_id, qty, ttl):
        """Does the item sell fast enough that being first in the queue matters?"""
        return self.sell_rate(item_id) * ttl >= qty * 1.5

    def _list(self, c, b, item_id, qty, dump=False, min_price=None):
        """Decide a price and put `qty` up for sale (or hit bids / vendor it)."""
        it, p, rng = self.items[item_id], b["p"], self.rng
        ref = self.ref[item_id]
        la = m.best_ask(c, item_id, exclude=b["id"])
        bb = m.best_bid(c, item_id, exclude=b["id"])
        floor = it["vendor_price"]
        noise = math.exp(rng.gauss(0, 0.05 * S["volatility"]))
        ttl = rng.randint(72, 216)
        md = b.get("markdown", {}).get(item_id, 1.0)
        if md < 1.0:
            b["markdown"][item_id] = min(1.0, md * 1.02)  # confidence slowly comes back
        own = ref * md * rng.uniform(0.95, 1.2) * noise  # the seller's own idea of a fair price

        if dump:
            # liquidation is priced off what the seller believes the item is worth, not off the book
            price = ref * (1 - p.get("discount", 0.25) * rng.uniform(0.6, 1.3)) * noise
        elif la is None:
            price = max(ref, self.value_of(item_id) * 0.9) * rng.uniform(1.08, 1.35) * noise
        elif p["style"] == "undercut" and self._liquid(item_id, qty, ttl):
            price = la - max(1, la * p["undercut"] * rng.random())
        elif p["style"] == "match" and la >= ref * 0.85:
            price = la  # join the queue at the best price
        else:
            price = max(own, la * 0.97) if la < own * 0.8 else own
        if not dump and min_price is None:
            price = max(price, ref * md * (1 - p["patience"]) * noise)  # never below what they accept
        if min_price is not None:
            price = max(price, min_price)
        price = int(price)

        if not dump and la is not None and not (bb and bb >= price * 0.97):
            # would this lot sell before it expires? The slower it would go, the more likely the
            # seller keeps the stock for later instead of joining a saturated / dead book
            eta = self.sell_eta(c, item_id, price, qty, exclude=b["id"])
            hold = 0.9 if eta is None else min(0.9, max(0.0, (eta / ttl - 1) * 0.6))
            if rng.random() < hold:
                return

        with savepoint(c):
            if bb and bb >= max(floor, price * (0.9 if dump else 0.97)):
                res = m.market_sell(c, b["id"], item_id, qty, max(floor, int(bb * 0.9) if dump else price), self.tick)
                qty -= res["filled"]
            if qty <= 0:
                return
            if price <= floor:
                if dump or rng.random() < 0.3:
                    m.vendor_sell(c, b["id"], item_id, qty)
                return
            m.place_order(c, b["id"], item_id, "sell", price, qty, self.tick, ttl=ttl)

    def _sell_inventory(self, c, b, keep=None, max_items=3):
        rows = c.execute("SELECT item_id, qty FROM inventory WHERE trader_id=? ORDER BY random() LIMIT ?",
                         (b["id"], max_items * 2)).fetchall()
        if self._open_sells(c, b["id"]) > 30:
            return
        done = 0
        for r in rows:
            if done >= max_items:
                break
            it = self.items[r["item_id"]]
            qty = r["qty"]
            if keep:
                qty -= keep.get(r["item_id"], 0)
            if qty <= 0 or self._open_sells(c, b["id"], r["item_id"]) >= 3:
                continue
            dump = r["qty"] > 4 * it["stack"]
            self._list(c, b, r["item_id"], min(qty, it["stack"]), dump=dump)
            done += 1

    def _reprice(self, c, b, n=2, on_login=False):
        """Relist lots that were undercut – mostly when logging in, and only where the item really sells."""
        if not on_login and self.rng.random() > 0.25:
            return
        rows = c.execute(
            "SELECT id, item_id, price, qty_left FROM orders WHERE trader_id=? AND side='sell' AND status='open' "
            "AND created_tick <= ? ORDER BY random() LIMIT ?",
            (b["id"], self.tick - 2 * b["p"]["reprice_age"], n)).fetchall()
        for o in rows:
            if b["p"]["style"] == "value" or not self._liquid(o["item_id"], o["qty_left"], 144):
                continue
            la = m.best_ask(c, o["item_id"], exclude=b["id"])
            if la is not None and la < o["price"] * 0.98:
                with savepoint(c):
                    m.cancel_order(c, o["id"])
                self._list(c, b, o["item_id"], o["qty_left"])

    # ------------------------------------------------------------ strategies

    def gather_yield(self, prof, skill=1.0):
        """Random haul for one gathering action: [(item_id, qty), ...]."""
        rng = self.rng
        pool = self.gather_pool[prof]
        weights = []
        for i in pool:
            it = self.items[i]
            attractiveness = min(3.0, max(0.3, (self.ref[i] / it["base_price"]) ** 1.5))
            weights.append(it["rarity"] * self.supply[i] * attractiveness)
        item_id = rng.choices(pool, weights)[0]
        it = self.items[item_id]
        raw = rng.uniform(0.5, 1.5) * 230 / it["base_price"] * skill * S["supply_mult"] * self.supply[item_id] ** 0.5
        qty = int(raw) + (rng.random() < raw - int(raw))
        haul = [(item_id, max(1, qty))]
        if rng.random() < 0.12:
            haul.append((rng.choice(self.junk), rng.randint(1, 4)))
        return haul

    def _act_gatherer(self, c, b):
        inv = {r["item_id"]: r["qty"] for r in
               c.execute("SELECT item_id, qty FROM inventory WHERE trader_id=?", (b["id"],))}
        for item_id, qty in self.gather_yield(b["profession"], b["p"]["skill"]):
            if inv.get(item_id, 0) < 6 * self.items[item_id]["stack"]:
                m.add_items(c, b["id"], item_id, qty)
        self._sell_inventory(c, b)
        self._reprice(c, b)

    def _act_crafter(self, c, b):
        recipes = self.recipes_by_prof[b["profession"]]
        weights = [math.exp(max(-1.0, min(1.5, self.recipe_score[r["id"]])) * 2) for r in recipes]
        for r in self.rng.choices(recipes, weights, k=3):
            self._try_craft(c, b, r)
        self._sell_inventory(c, b, keep=self.keep_by_prof[b["profession"]])
        self._reprice(c, b)

    def _sale_estimate(self, c, item_id, bot_id):
        ref = self.ref[item_id]
        la = m.best_ask(c, item_id, exclude=bot_id)
        if la:
            return min(la, ref * 1.25)
        return max(ref, self.value_of(item_id)) * 1.15

    def _try_craft(self, c, b, r):
        rng, p = self.rng, b["p"]
        out = r["output_id"]
        out_it = self.items[out]
        if m.qty_of(c, b["id"], out) > 3 * out_it["stack"]:
            return
        revenue = self._sale_estimate(c, out, b["id"]) * r["output_qty"] * (1 - S["ah_cut_pct"] / 100)

        # craft what we already hold (e.g. ingredients from filled buy orders)
        have_n = m.max_crafts(c, b["id"], r["id"])
        if have_n:
            with savepoint(c):
                m.craft(c, b["id"], r["id"], min(have_n, 5))
            return

        n = rng.randint(1, max(1, min(5, out_it["stack"] // r["output_qty"])))
        cost = 0.0
        buys, missing = [], []
        for ing, q in r["ings"]:
            need = q * n
            have = min(m.qty_of(c, b["id"], ing), need)
            cost += have * self.ref[ing] * 0.9
            to_buy = need - have
            if to_buy <= 0:
                continue
            sc, filled, worst = m.sweep_cost(c, ing, to_buy, exclude=b["id"])
            cost += sc
            if filled < to_buy:
                missing.append((ing, to_buy - filled, q))
                cost += (to_buy - filled) * self.ref[ing]
            else:
                buys.append((ing, to_buy, worst, sc))

        ratio = revenue * n / max(1.0, cost)
        self.recipe_score[r["id"]] = self.recipe_score[r["id"]] * 0.9 + (ratio - 1) * 0.1
        if ratio < 1 + p["margin"]:
            return

        if not missing:
            if sum(x[3] for x in buys) > m.gold_of(c, b["id"]) * 0.6:
                return
            with savepoint(c):
                for ing, qty, worst, _sc in buys:
                    m.market_buy(c, b["id"], ing, qty, worst, self.tick)
                k = m.max_crafts(c, b["id"], r["id"])
                if k:
                    m.craft(c, b["id"], r["id"], min(k, n))
            return

        # post standing buy orders for missing ingredients at a price that keeps the margin
        batch_rev = revenue / (1 + p["margin"])
        total_ref = sum(self.ref[i] * q for i, q in r["ings"]) or 1
        open_bids = c.execute("SELECT item_id FROM orders WHERE trader_id=? AND side='buy' AND status='open'",
                              (b["id"],)).fetchall()
        bid_items = {x["item_id"] for x in open_bids}
        for ing, miss, q in missing:
            if ing in bid_items or len(bid_items) >= 8:
                continue
            max_unit = batch_rev * (self.ref[ing] * q / total_ref) / q
            bid = int(min(max_unit, self.ref[ing] * rng.uniform(0.85, 1.05)))
            if bid >= 1 and bid * miss < m.gold_of(c, b["id"]) * 0.3:
                with savepoint(c):
                    m.place_order(c, b["id"], ing, "buy", bid, miss, self.tick, ttl=rng.randint(36, 96))
                bid_items.add(ing)

    def _npc_demand(self, c):
        """NPC buyers arrive per item as a Poisson stream (popularity × demand × time of day)."""
        rng = self.rng
        for item_id, buyers in self.buyers_of.items():
            if buyers:
                for _ in range(poisson(rng, self.arrivals(item_id))):
                    self._consumer_buy(c, rng.choice(buyers), item_id)

    def _consumer_buy(self, c, b, item_id):
        rng = self.rng
        scale = b["p"]["scale"]
        it = self.items[item_id]
        v = self.value_of(item_id) * math.exp(rng.gauss(0, 0.2 * max(0.2, S["volatility"])))
        la = m.best_ask(c, item_id)
        if la and la <= v:
            units = rng.uniform(100, 500) * scale / it["base_price"] * (v / la) ** 1.5
            units = min(units, 2 * it["stack"])
            qty = int(units) + (rng.random() < units - int(units))
            if qty:
                with savepoint(c):
                    m.market_buy(c, b["id"], item_id, qty, int(v), self.tick)
        elif rng.random() < 0.15:
            if c.execute("SELECT 1 FROM orders WHERE trader_id=? AND item_id=? AND side='buy' AND status='open'",
                         (b["id"], item_id)).fetchone():
                return
            units = max(1, int(rng.uniform(50, 250) * scale / it["base_price"]))
            with savepoint(c):
                m.place_order(c, b["id"], item_id, "buy", max(1, int(v * 0.8)), min(units, it["stack"]),
                              self.tick, ttl=72)

    def _act_speculator(self, c, b):
        rng, p = self.rng, b["p"]
        active = [r["item_id"] for r in c.execute(
            "SELECT DISTINCT item_id FROM trades WHERE tick > ? ORDER BY random() LIMIT 8", (self.tick - 60,))]
        gold = m.gold_of(c, b["id"])
        for item_id in active:
            ref = self.ref[item_id]
            la = m.best_ask(c, item_id, exclude=b["id"])
            limit = int(ref * (1 - p["discount"]))
            if la and la <= limit and limit > self.items[item_id]["vendor_price"]:
                qty = min(int(gold * 0.25 // la), 3 * self.items[item_id]["stack"])
                if qty:
                    with savepoint(c):
                        m.market_buy(c, b["id"], item_id, qty, limit, self.tick)
        for r in c.execute("SELECT item_id, qty FROM inventory WHERE trader_id=? ORDER BY random() LIMIT 2",
                           (b["id"],)).fetchall():
            if self._open_sells(c, b["id"], r["item_id"]) < 2:
                it = self.items[r["item_id"]]
                self._list(c, b, r["item_id"], min(r["qty"], it["stack"]),
                           min_price=self.ref[r["item_id"]] * (1 + p["markup"] * rng.random()))
        self._reprice(c, b, n=1)

    def _act_dumper(self, c, b):
        rng = self.rng
        if rng.random() < 0.2:
            for _ in range(rng.randint(2, 5)):
                if rng.random() < 0.35:
                    item_id = rng.choice(self.junk)
                else:
                    item_id = rng.choice(list(self.items))
                it = self.items[item_id]
                qty = max(1, int(rng.uniform(0.2, 1.0) * 400 / it["base_price"]))
                m.add_items(c, b["id"], item_id, min(qty, it["stack"]))
        for r in c.execute("SELECT item_id, qty FROM inventory WHERE trader_id=? LIMIT 4", (b["id"],)).fetchall():
            if self._open_sells(c, b["id"], r["item_id"]) == 0:
                self._list(c, b, r["item_id"], r["qty"], dump=True)
        self._reprice(c, b, n=1)

    # ------------------------------------------------------------ maintenance

    def _housekeeping(self, c):
        G = m.GOLD
        bounds = {"consumer": (1000 * G, 1000 * G), "crafter": (15 * G, 300 * G), "speculator": (50 * G, 400 * G),
                  "gatherer": (2 * G, 80 * G), "dumper": (1 * G, 5 * G)}
        for strategy, (lo, hi) in bounds.items():
            c.execute("UPDATE traders SET gold = MIN(MAX(gold, ?), ?) WHERE kind='bot' AND strategy=?", (lo, hi, strategy))
        # bots never hoard more than 10 stacks of anything: the excess is thrown away
        c.execute(
            "UPDATE inventory SET qty = (SELECT stack * 10 FROM items WHERE items.id = inventory.item_id) "
            "WHERE trader_id IN (SELECT id FROM traders WHERE kind='bot') "
            "AND qty > (SELECT stack * 10 FROM items WHERE items.id = inventory.item_id)")

    def _build_candles(self, c, bucket):
        t0, t1 = bucket * CANDLE_TICKS, bucket * CANDLE_TICKS + CANDLE_TICKS - 1
        agg = {}
        for t in c.execute("SELECT item_id, price, qty FROM trades WHERE tick BETWEEN ? AND ? ORDER BY id", (t0, t1)):
            a = agg.get(t["item_id"])
            if a is None:
                agg[t["item_id"]] = a = {"o": t["price"], "h": t["price"], "l": t["price"], "v": 0, "n": 0, "pv": 0}
            a["h"], a["l"], a["c"] = max(a["h"], t["price"]), min(a["l"], t["price"]), t["price"]
            a["v"] += t["qty"]
            a["n"] += 1
            a["pv"] += t["price"] * t["qty"]
        book = {}
        for r in c.execute("SELECT item_id, side, MIN(price) lo, MAX(price) hi, SUM(qty_left) q, COUNT(*) n "
                           "FROM orders WHERE status='open' GROUP BY item_id, side"):
            book[(r["item_id"], r["side"])] = r
        rows = []
        for i in self.items:
            a = agg.get(i)
            ask, bid = book.get((i, "sell")), book.get((i, "buy"))
            if a:
                o, h, lo, cl, vw, v, n = a["o"], a["h"], a["l"], a["c"], a["pv"] / a["v"], a["v"], a["n"]
                self.last_close[i] = cl
            else:
                o = h = lo = cl = self.last_close[i]
                vw, v, n = None, 0, 0
            rows.append((i, bucket, o, h, lo, cl, vw, v, n,
                         ask["lo"] if ask else None, bid["hi"] if bid else None,
                         ask["q"] if ask else 0, bid["q"] if bid else 0, ask["n"] if ask else 0))
        c.executemany("INSERT OR REPLACE INTO candles VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)

        # demand drift: slow mean-reverting random walk per item
        vol = S["volatility"]
        for i in self.items:
            d = 1 + (self.drift[i] - 1) * 0.97 + self.rng.gauss(0, 0.02 * vol)
            self.drift[i] = min(1.8, max(0.5, d))
        c.executemany("UPDATE market_state SET drift=? WHERE item_id=?", [(d, i) for i, d in self.drift.items()])

        if bucket % 200 == 0:
            c.execute("DELETE FROM candles WHERE bucket < ?", (bucket - KEEP_CANDLES,))
            c.execute("DELETE FROM trades WHERE tick < ?", (self.tick - KEEP_TRADE_TICKS,))
            c.execute("DELETE FROM events WHERE end_tick < ?", (self.tick - 30 * TICKS_PER_DAY,))


engine = Engine()

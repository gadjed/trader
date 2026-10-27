"""Optional sentiment sync with the Guild Wars 2 Trading Post (public API, no key).

GW2 exposes only *current* prices, so we capture a baseline on the first sync and
then translate relative moves into our market:
  * mid-price change vs. baseline        -> demand multiplier (ext_mult)
  * sell/buy order quantity ratio change -> supply multiplier (ext_supply)
Items without a GW2 mapping inherit a damped average of their category.
"""
import json
import logging
import math
import threading
import time
import urllib.request

from .db import set_setting, tx
from .settings import S

log = logging.getLogger("trader.gw2")
API = "https://api.guildwars2.com/v2/commerce/prices?ids="
INTERVAL = 300

status = {"last_sync": None, "error": None, "mapped": 0, "sample": []}


def fetch(ids):
    with urllib.request.urlopen(API + ",".join(map(str, ids)), timeout=15) as r:
        return {p["id"]: p for p in json.load(r)}


def sync_once(engine):
    with tx() as c:
        rows = c.execute(
            "SELECT i.id, i.gw2_id, i.category, ms.gw2_base_price, ms.gw2_base_ratio FROM items i "
            "JOIN market_state ms ON ms.item_id = i.id WHERE i.gw2_id IS NOT NULL").fetchall()
    prices = fetch([r["gw2_id"] for r in rows])
    w = S["gw2_weight"]
    updates, by_cat, sample = {}, {}, []
    with tx() as c:
        for r in rows:
            p = prices.get(r["gw2_id"])
            if not p or not p["buys"]["unit_price"] or not p["sells"]["unit_price"]:
                continue
            mid = (p["buys"]["unit_price"] + p["sells"]["unit_price"]) / 2
            ratio = p["sells"]["quantity"] / max(1, p["buys"]["quantity"])
            if r["gw2_base_price"] is None:
                c.execute("UPDATE market_state SET gw2_base_price=?, gw2_base_ratio=? WHERE item_id=?",
                          (mid, ratio, r["id"]))
                base_mid, base_ratio = mid, ratio
            else:
                base_mid, base_ratio = r["gw2_base_price"], r["gw2_base_ratio"]
            dm = min(2.0, max(0.5, (mid / base_mid) ** (2 * w)))
            sm = min(2.0, max(0.5, (ratio / base_ratio) ** w))
            updates[r["id"]] = (dm, sm)
            by_cat.setdefault(r["category"], []).append((dm, sm))
            sample.append({"item_id": r["id"], "gw2_id": r["gw2_id"], "mid": mid, "demand": round(dm, 3),
                           "supply": round(sm, 3)})
        for item_id, it in engine.items.items():
            if item_id in updates or it["category"] not in by_cat:
                continue
            vals = by_cat[it["category"]]
            gd = math.exp(sum(math.log(d) for d, _ in vals) / len(vals)) ** 0.5
            gs = math.exp(sum(math.log(s) for _, s in vals) / len(vals)) ** 0.5
            updates[item_id] = (gd, gs)
        for item_id, (dm, sm) in updates.items():
            c.execute("UPDATE market_state SET ext_mult=?, ext_supply=? WHERE item_id=?", (dm, sm, item_id))
            engine.ext[item_id] = (dm, sm)
        set_setting(c, "gw2_last_sync", time.time())
    status.update(last_sync=time.time(), error=None, mapped=len(sample), sample=sample)


def reset_baseline(engine):
    with tx() as c:
        c.execute("UPDATE market_state SET gw2_base_price=NULL, gw2_base_ratio=NULL, ext_mult=1, ext_supply=1")
        for i in engine.ext:
            engine.ext[i] = (1.0, 1.0)


def disable(engine):
    with tx() as c:
        c.execute("UPDATE market_state SET ext_mult=1, ext_supply=1")
        for i in engine.ext:
            engine.ext[i] = (1.0, 1.0)


class Syncer(threading.Thread):
    def __init__(self, engine):
        super().__init__(name="gw2-sync", daemon=True)
        self.engine = engine
        self.wake = threading.Event()
        self.stopped = threading.Event()

    def run(self):
        while not self.stopped.is_set():
            if S["gw2_sync"]:
                try:
                    sync_once(self.engine)
                except Exception as e:  # network errors must never break the game
                    log.warning("gw2 sync failed: %s", e)
                    status["error"] = str(e)
            self.wake.wait(INTERVAL)
            self.wake.clear()

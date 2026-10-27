"""How do bots react to a player's lot? Time until someone lists cheaper, by item liquidity.

    uv run python scripts/undercut_test.py [--warmup-days 5] [--hours 12]
"""
import argparse
import os
import statistics
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ap = argparse.ArgumentParser()
ap.add_argument("--warmup-days", type=float, default=5)
ap.add_argument("--hours", type=float, default=12)
ap.add_argument("--seed", type=int, default=3)
args = ap.parse_args()
os.environ["TRADER_DB"] = os.path.join(tempfile.mkdtemp(), "undercut.db")

from trader import db, market as m  # noqa: E402
from trader.engine import TICKS_PER_DAY, Engine  # noqa: E402
from trader.seed import seed  # noqa: E402

db.reset_db()
with db.tx() as c:
    seed(c)
eng = Engine(seed=args.seed)
with db.tx() as c:
    eng.load(c)
for _ in range(int(args.warmup_days * TICKS_PER_DAY)):
    eng.step()

# place one lot per item, priced 1 copper below the cheapest lot (or at the reference price)
lots = {}
with db.tx() as c:
    pid = c.execute("INSERT INTO traders(name, kind, gold) VALUES('Тест', 'player', 100000000)").lastrowid
    for i, it in eng.items.items():
        la = m.best_ask(c, i)
        price = max(it["vendor_price"] + 1, (la - 1) if la else round(eng.ref[i]))
        qty = max(1, it["stack"] // 4)
        m.add_items(c, pid, i, qty)
        res = m.place_order(c, pid, i, "sell", price, qty, eng.tick, ttl=144)
        if res["order_id"] and res["filled"] == 0:
            lots[i] = {"order": res["order_id"], "price": price, "vel": eng.velocity[i] * TICKS_PER_DAY,
                       "start": eng.tick, "undercut": None, "sold": 0}

for t in range(int(args.hours * 6)):
    eng.step()
    with db.tx() as c:
        for i, lot in lots.items():
            if lot["undercut"] is None and c.execute(
                    "SELECT 1 FROM orders WHERE item_id=? AND side='sell' AND status='open' AND trader_id != ? "
                    "AND price < ? AND created_tick > ?", (i, pid, lot["price"], lot["start"])).fetchone():
                lot["undercut"] = (t + 1) * 10  # game minutes
            o = c.execute("SELECT qty, qty_left FROM orders WHERE id=?", (lot["order"],)).fetchone()
            lot["sold"] = o["qty"] - o["qty_left"]

classes = [("мертвий (<1 шт/добу)", 0, 1), ("повільний (1-20)", 1, 20), ("середній (20-150)", 20, 150),
           ("ліквідний (>150)", 150, 1e9)]
print(f"Лот гравця на кожен товар, спостереження {args.hours:.0f} год гри\n")
print(f"{'ринок':24s} {'товарів':>7s} {'підрізали':>10s} {'за 1 год':>9s} {'медіана, хв':>12s} {'лот продавався':>15s}")
for name, lo, hi in classes:
    ls = [x for x in lots.values() if lo <= x["vel"] < hi]
    if not ls:
        continue
    cut = [x["undercut"] for x in ls if x["undercut"] is not None]
    print(f"{name:24s} {len(ls):7d} {len(cut) / len(ls):10.0%} {sum(u <= 60 for u in cut) / len(ls):9.0%} "
          f"{(statistics.median(cut) if cut else float('nan')):12.0f} {sum(x['sold'] > 0 for x in ls) / len(ls):15.0%}")

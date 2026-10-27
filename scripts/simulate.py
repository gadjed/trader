"""Headless market simulation for tuning: fresh DB, N ticks, liveliness report.

    uv run python scripts/simulate.py --days 6 [--preset oversupply] [--set ah_cut_pct=10]
"""
import argparse
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ap = argparse.ArgumentParser()
ap.add_argument("--days", type=float, default=6)
ap.add_argument("--preset", default=None)
ap.add_argument("--set", action="append", default=[], help="key=value setting override")
ap.add_argument("--seed", type=int, default=1)
ap.add_argument("--db", default=None, help="keep the resulting DB at this path")
ap.add_argument("--verbose", action="store_true")
args = ap.parse_args()

os.environ["TRADER_DB"] = args.db or os.path.join(tempfile.mkdtemp(), "sim.db")

from trader import db, settings  # noqa: E402
from trader.engine import CANDLE_TICKS, TICKS_PER_DAY, Engine  # noqa: E402
from trader.seed import seed  # noqa: E402

db.reset_db()
with db.tx() as c:
    seed(c)
    if args.preset:
        settings.apply_preset(c, args.preset)
    for kv in args.set:
        k, v = kv.split("=")
        settings.save(c, {k: float(v)})

eng = Engine(seed=args.seed)
with db.tx() as c:
    eng.load(c)

ticks = int(args.days * TICKS_PER_DAY)
t0 = time.perf_counter()
for _ in range(ticks):
    eng.step()
elapsed = time.perf_counter() - t0
print(f"{ticks} ticks in {elapsed:.1f}s ({elapsed / ticks * 1000:.1f} ms/tick)")

with db.tx() as c:
    last_day_bucket = (eng.tick - TICKS_PER_DAY) // CANDLE_TICKS
    stats = {r["item_id"]: r for r in c.execute(
        "SELECT item_id, SUM(volume) vol, SUM(trades) n, AVG(ask_qty) askq, "
        "SUM(CASE WHEN best_ask IS NULL THEN 1 ELSE 0 END) * 1.0 / COUNT(*) empty "
        "FROM candles WHERE bucket > ? GROUP BY item_id", (last_day_bucket,))}
    closes = {}
    for r in c.execute("SELECT item_id, bucket, close FROM candles WHERE close IS NOT NULL ORDER BY bucket"):
        closes.setdefault(r["item_id"], []).append(r["close"])
    events = c.execute("SELECT tick, title FROM events ORDER BY id").fetchall()
    total_trades = c.execute("SELECT COUNT(*) n FROM trades").fetchone()["n"]

    rows = []
    for i, it in eng.items.items():
        s = stats.get(i)
        cl = closes.get(i, [])
        ratio = eng.ref[i] / it["base_price"]
        # volatility: stdev of log-returns between candles that had a price
        rets = [abs(b / a - 1) for a, b in zip(cl, cl[1:]) if a and b and a != b]
        rows.append(dict(
            name=it["name"], cat=it["category"], base=it["base_price"], ref=eng.ref[i], ratio=ratio,
            vol=(s["vol"] or 0) if s else 0, n=(s["n"] or 0) if s else 0,
            sat=((s["askq"] or 0) / it["stack"]) if s else 0, empty=s["empty"] if s else 1,
            moves=len(rets)))

dead = [r for r in rows if r["n"] == 0]
ratios = [r["ratio"] for r in rows]
print(f"trades total: {total_trades}, events: {len(events)}")
print(f"items: {len(rows)}, no trades last day: {len(dead)}, empty book >50% of last day: "
      f"{sum(r['empty'] > .5 for r in rows)}, saturated (>8 stacks listed): {sum(r['sat'] > 8 for r in rows)}")
print(f"ref/base ratio: median {statistics.median(ratios):.2f}, min {min(ratios):.2f}, max {max(ratios):.2f}")

by_cat = {}
for r in rows:
    by_cat.setdefault(r["cat"], []).append(r)
print("\ncategory            trades/day  med ref/base  dead")
for k, rs in sorted(by_cat.items()):
    print(f"{k:22s} {sum(r['n'] for r in rs):8d}  {statistics.median(r['ratio'] for r in rs):10.2f}  "
          f"{sum(r['n'] == 0 for r in rs):4d}/{len(rs)}")

if args.verbose or dead:
    print("\nDEAD:", ", ".join(r["name"] for r in dead))
if args.verbose:
    print("\nitem                         base     ref   ratio  trades  stacks_listed  empty")
    for r in sorted(rows, key=lambda r: r["ratio"]):
        print(f"{r['name'][:28]:28s} {r['base']:6d} {r['ref']:8.0f} {r['ratio']:6.2f} {r['n']:6d} "
              f"{r['sat']:8.1f} {r['empty']:8.2f}")
    print("\nEvents:")
    for e in events:
        print(f"  t={e['tick']:5d} {e['title']}")

# impact of item-level events: price & listed quantity before vs. during the event
with db.tx() as c:
    print("\nEvent impact (close / units listed): before -> +12h -> +24h")
    for e in c.execute("SELECT * FROM events WHERE target_type='item' ORDER BY id"):
        item_id = eng.by_code[e["target"]]
        b0 = e["tick"] // CANDLE_TICKS

        def at(b):
            r = c.execute("SELECT close, ask_qty FROM candles WHERE item_id=? AND bucket<=? AND close IS NOT NULL "
                          "ORDER BY bucket DESC LIMIT 1", (item_id, b)).fetchone()
            return f"{r['close']}/{r['ask_qty']}" if r else "-"
        print(f"  [{e['kind']:6s} x{e['mult']:.2f}] {e['title'][:55]:55s} {at(b0 - 1):>12s} -> "
              f"{at(b0 + 24):>12s} -> {at(b0 + 48):>12s}")

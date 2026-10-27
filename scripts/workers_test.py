"""Economy check for hired workers: output value vs. wages, food and tools.

    uv run python scripts/workers_test.py [--days 3]
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ap = argparse.ArgumentParser()
ap.add_argument("--days", type=int, default=3)
args = ap.parse_args()
os.environ["TRADER_DB"] = os.path.join(tempfile.mkdtemp(), "workers.db")

from trader import db, market as m, workers as W  # noqa: E402
from trader.engine import TICKS_PER_DAY, Engine  # noqa: E402
from trader.seed import seed  # noqa: E402

db.reset_db()
with db.tx() as c:
    seed(c)
eng = Engine(seed=5)
with db.tx() as c:
    eng.load(c)
for _ in range(2 * TICKS_PER_DAY):
    eng.step()

code = eng.by_code
# (role, profession, level, traits, contract days, food, tool, tool item to equip)
SETUPS = [
    ("gatherer", "scavenger", 1, [], 7, False, False, None),
    ("gatherer", "lumberjack", 1, [], 7, False, False, None),
    ("gatherer", "lumberjack", 3, [], 7, True, True, "axe"),
    ("gatherer", "lumberjack", 5, ["hardworking"], 7, True, True, "axe"),
    ("gatherer", "miner", 4, ["lucky"], 7, True, True, "lantern"),
    ("gatherer", "farmer", 2, ["drunk"], 7, True, False, None),
    ("crafter", "carpenter", 2, [], 7, False, False, None),
    ("crafter", "blacksmith", 3, ["thrifty"], 7, True, True, "hammer"),
]
with db.tx() as c:
    pid = c.execute("INSERT INTO traders(name, kind, gold, license) VALUES('Тест', 'player', ?, 4)",
                    (500 * m.GOLD,)).lastrowid
    # pantry, tools and crafting stock
    for item, q in [("rations", 60), ("bread", 40), ("beer", 10), ("axe", 2), ("lantern", 1), ("hammer", 1),
                    ("birch_log", 200), ("iron_ore", 300), ("coal", 300)]:
        m.add_items(c, pid, code[item], q)
    hired = []
    for role, prof, level, traits, days, food, tool, tool_item in SETUPS:
        ask = round(W.base_wage(role, prof, level) * W.effect(traits, "wage"))
        spec = None
        if role == "crafter":
            spec = "Інструменти" if prof == "blacksmith" else "Деревина"
        wid = c.execute("INSERT INTO workers(name, role, profession, level, xp, traits, spec, ask_wage, morale,"
                        " available_until) VALUES(?,?,?,?,?,?,?,?,80,?)",
                        (f"{prof}-{level}", role, prof, level, W.XP_FOR_LEVEL.get(level, 0), json.dumps(traits),
                         spec, ask, eng.tick + 999)).lastrowid
        W.hire(c, eng, pid, wid, days, food, tool)
        if tool_item:
            W.equip(c, eng, pid, wid, code[tool_item])
        hired.append(wid)
    # crafter queues: carpenter makes planks and handles, blacksmith smelts iron and makes axes
    carp = [r for r in eng.recipes if r["profession"] == "carpenter" and not r["is_alt"]]
    smith = [r for r in eng.recipes if r["profession"] == "blacksmith" and not r["is_alt"]]
    rid = {eng.items[r["output_id"]]["code"]: r["id"] for r in carp + smith}
    W.set_tasks(c, eng, pid, hired[6], [{"recipe_id": rid["birch_plank"], "keep": 0}])
    W.set_tasks(c, eng, pid, hired[7], [{"recipe_id": rid["axe"], "keep": 3},
                                        {"recipe_id": rid["iron_ingot"], "keep": 60}])
    W.set_tasks(c, eng, pid, hired[6], [{"recipe_id": rid["handle"], "keep": 20},
                                        {"recipe_id": rid["birch_plank"], "keep": 0}])
    gold0 = m.gold_of(c, pid)

produced = {w: {} for w in hired}
for t in range(args.days * TICKS_PER_DAY):
    with db.tx() as c:
        before = {w: json.loads(c.execute("SELECT today FROM workers WHERE id=?", (w,)).fetchone()["today"])
                  for w in hired if c.execute("SELECT 1 FROM workers WHERE id=? AND owner_id=?", (w, pid)).fetchone()}
    eng.step()
    with db.tx() as c:
        for w, prev in before.items():
            row = c.execute("SELECT today FROM workers WHERE id=?", (w,)).fetchone()
            now = json.loads(row["today"]) if row else {}
            for i, q in now.items():
                d = q - prev.get(i, 0)
                if d > 0:
                    produced[w][i] = produced[w].get(i, 0) + d

with db.tx() as c:
    print(f"{args.days} днів роботи\n")
    print(f"{'працівник':28s} {'ЗП/день':>9s} {'виробіток (база)':>17s} {'за ринком':>11s} {'настрій':>8s}  що зробив")
    for (role, prof, level, traits, *_), w in zip(SETUPS, hired):
        row = c.execute("SELECT * FROM workers WHERE id=?", (w,)).fetchone()
        base = sum(eng.items[int(i)]["base_price"] * q for i, q in produced[w].items())
        mkt = sum(eng.ref[int(i)] * q for i, q in produced[w].items())
        top = sorted(produced[w].items(), key=lambda x: -eng.items[int(x[0])]["base_price"] * x[1])[:4]
        desc = ", ".join(f"{eng.items[int(i)]['name']}×{q}" for i, q in top)
        label = f"{W.prof_name(prof)} L{level} {'+'.join(traits)}"
        print(f"{label:28s} {m.fmt_money(row['wage']):>9s} {m.fmt_money(base / args.days):>17s} "
              f"{m.fmt_money(mkt / args.days):>11s} {row['morale']:8.0f}  {row['status']}: {desc}")
    print(f"\nвитрачено золота (ЗП): {m.fmt_money(gold0 - m.gold_of(c, pid))}")
    left = {k: m.qty_of(c, pid, code[k]) for k in ("rations", "bread", "beer", "birch_log", "iron_ore", "coal")}
    print("залишки:", left)
    for r in c.execute("SELECT kind, text FROM worker_log WHERE owner_id=? AND kind NOT IN ('hire') ORDER BY id", (pid,)):
        print("  log:", r["kind"], r["text"])

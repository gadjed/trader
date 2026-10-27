"""Populate a fresh database with catalog content and the bot population."""
import json
import math
import random

from . import catalog as cat
from .db import get_setting, set_setting

MARKUP = 0.25
LUXURY_MARKUP = 0.40


def _stack_for(price):
    if price < 50:
        return 100
    if price < 500:
        return 20
    if price < 3000:
        return 5
    return 1


def compute_catalog():
    """Return {code: dict(...)} with derived base price, tier and demand weight."""
    items = {}
    for code, name, icon, category, prof, base, rarity, gw2 in cat.RAW:
        items[code] = dict(code=code, name=name, icon=icon, category=category, gather_prof=prof,
                           base=base, rarity=rarity, tier=0, is_junk=0, gw2_id=gw2)
    for code, name, icon, base in cat.JUNK:
        items[code] = dict(code=code, name=name, icon=icon, category="Хлам", gather_prof=None,
                           base=base, rarity=1.0, tier=0, is_junk=1, gw2_id=None)
    for code, name, icon, category, gw2 in cat.CRAFTED:
        items[code] = dict(code=code, name=name, icon=icon, category=category, gather_prof=None,
                           base=None, rarity=1.0, tier=None, is_junk=0, gw2_id=gw2)

    primary = {}
    for prof, out, qty, ings in cat.RECIPES:
        primary.setdefault(out, (qty, ings))

    def resolve(code, seen=()):
        it = items[code]
        if it["base"] is not None and it["tier"] is not None:
            return it["base"], it["tier"]
        if code in seen:
            raise ValueError(f"recipe cycle at {code}")
        qty, ings = primary[code]
        cost, tier = 0, 0
        for ing, n in ings.items():
            b, t = resolve(ing, seen + (code,))
            cost += b * n
            tier = max(tier, t + 1)
        markup = LUXURY_MARKUP if it["category"] in cat.LUXURY_CATEGORIES else MARKUP
        it["base"] = max(1, math.ceil(cost * (1 + markup) / qty))
        it["tier"] = tier
        return it["base"], tier

    for code in items:
        resolve(code)

    used_as_ingredient = {ing for _p, _o, _q, ings in cat.RECIPES for ing in ings}
    for it in items.values():
        if it["is_junk"]:
            w = 0.5
        elif it["code"] not in used_as_ingredient:
            w = 1.0
        elif it["tier"] == 0:
            w = 0.25
        else:
            w = 0.45
        if it["category"] == "Їжа":
            w = max(w, 0.9)
        it["consume_weight"] = w
        it["stack"] = _stack_for(it["base"])
        it["vendor"] = max(1, it["base"] // 4)
    return items


def _nick(rng, used, profession_title=""):
    for _ in range(100):
        style = rng.choice(cat.NICK_STYLES)
        name = style.format(n=rng.choice(cat.FIRST_NAMES), p=profession_title or "Торгаш", d=rng.randint(1, 99))
        if name not in used:
            used.add(name)
            return name
    name = f"Бот{len(used)}"
    used.add(name)
    return name


def seed(c, rng_seed=42):
    if get_setting(c, "seeded") == "1":
        return False
    rng = random.Random(rng_seed)
    items = compute_catalog()

    ids = {}
    for it in items.values():
        ids[it["code"]] = c.execute(
            "INSERT INTO items(code, name, icon, category, gather_prof, base_price, vendor_price, stack, tier, rarity,"
            " consume_weight, is_junk, gw2_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (it["code"], it["name"], it["icon"], it["category"], it["gather_prof"], it["base"], it["vendor"],
             it["stack"], it["tier"], it["rarity"], it["consume_weight"], it["is_junk"], it["gw2_id"]),
        ).lastrowid
        c.execute("INSERT INTO market_state(item_id) VALUES(?)", (ids[it["code"]],))

    for recipes, alt in ((cat.RECIPES, 0), (cat.ALT_RECIPES, 1)):
        for prof, out, qty, ings in recipes:
            rid = c.execute(
                "INSERT INTO recipes(profession, output_id, output_qty, is_alt) VALUES(?,?,?,?)",
                (prof, ids[out], qty, alt),
            ).lastrowid
            for ing, n in ings.items():
                c.execute("INSERT INTO recipe_ingredients(recipe_id, item_id, qty) VALUES(?,?,?)", (rid, ids[ing], n))

    used = set()

    def bot(strategy, profession, gold, params, name=None):
        name = name or _nick(rng, used, (cat.GATHER_PROFS | cat.CRAFT_PROFS).get(profession, ""))
        used.add(name)
        tid = c.execute(
            "INSERT INTO traders(name, kind, strategy, profession, params, gold) VALUES(?,?,?,?,?,?)",
            (name, "bot", strategy, profession, json.dumps(params, ensure_ascii=False), gold),
        ).lastrowid
        return tid

    G = 10000
    for prof in cat.GATHER_PROFS:
        for _ in range(4):
            bot("gatherer", prof, 5 * G, {
                "undercut": round(rng.uniform(0.0, 0.04), 3),   # how hard they undercut
                "patience": round(rng.uniform(0.15, 0.45), 2),  # how far below ref they agree to sell
                "skill": round(rng.uniform(0.7, 1.4), 2),
                "reprice_age": rng.randint(4, 30),
            })
    for prof in cat.CRAFT_PROFS:
        for _ in range(3):
            bot("crafter", prof, 40 * G, {
                "margin": round(rng.uniform(0.05, 0.25), 2),
                "undercut": round(rng.uniform(0.0, 0.03), 3),
                "patience": round(rng.uniform(0.1, 0.35), 2),
                "reprice_age": rng.randint(4, 24),
            })
    for name, cats, scale in cat.CONSUMERS:
        bot("consumer", None, 1000 * G, {"categories": cats, "scale": scale}, name=name)
    for _ in range(4):
        bot("speculator", None, 200 * G, {
            "discount": round(rng.uniform(0.15, 0.35), 2),
            "markup": round(rng.uniform(0.0, 0.2), 2),
            "undercut": 0.01, "patience": 0.05, "reprice_age": rng.randint(10, 40),
        }, name=_nick(rng, used, "Перекупник"))
    for _ in range(5):
        bot("dumper", None, 1 * G, {
            "discount": round(rng.uniform(0.2, 0.45), 2),
            "undercut": 0.05, "patience": 0.9, "reprice_age": 6,
        }, name=_nick(rng, used, "Нуб"))

    set_setting(c, "tick", 0)
    set_setting(c, "seeded", "1")
    return True


def starter_kit(c, trader_id, rng=random):
    """Starting inventory for a new player: some raw materials and junk."""
    raws = c.execute("SELECT id, base_price, stack FROM items WHERE tier=0 AND rarity >= 0.3").fetchall()
    for it in rng.sample(raws, 8):
        qty = max(1, int(rng.uniform(0.3, 1.0) * min(it["stack"], 600 / it["base_price"] + 1)))
        c.execute("INSERT INTO inventory(trader_id, item_id, qty) VALUES(?,?,?) "
                  "ON CONFLICT DO UPDATE SET qty=qty+excluded.qty", (trader_id, it["id"], qty))

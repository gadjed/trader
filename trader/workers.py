"""Hired workers: gatherers and crafters on contracts.

A worker has a profession, level (skill grows with work days), traits and morale.
Contracts are prepaid daily; providing food and/or tools lowers the wage but makes the
employer responsible for keeping the pantry stocked and the worker equipped.
Production lands in the employer's inventory; crafters take ingredients from it –
so gatherers feed crafters, crafters make tools for gatherers, cooks feed everyone.
"""
import json
import math
import random

from . import catalog as cat
from . import market as m
from .settings import S

G = m.GOLD
DAY = 144                       # ticks per game day
WORK_TICKS = 96                 # 06:00–22:00
LEVELS = ["", "Новачок", "Підмайстер", "Майстер", "Експерт", "Легенда"]
LEVEL_WEIGHTS = [40, 28, 18, 10, 4]
XP_FOR_LEVEL = {2: 4, 3: 10, 4: 20, 5: 36}          # work days to reach the level

# copper of base value produced per work day
GATHER_VALUE = [0, 4000, 6000, 9000, 14000, 22000]
CRAFT_VALUE = [0, 20000, 35000, 60000, 100000, 160000]
GATHER_WAGE = [0, 3500, 5500, 8500, 13000, 20000]
CRAFT_WAGE = [0, 2500, 4500, 7500, 12000, 20000]

SCAVENGER = "scavenger"
SCAVENGER_NAME = "Збирач хламу"
SCAVENGER_VALUE = 0.4           # share of a normal gatherer's output
SCAVENGER_WAGE = 0.25

# gatherers of level L only find items with rarity >= MIN_RARITY[L]; luck lowers the bar one step
MIN_RARITY = [1.0, 0.6, 0.3, 0.1, 0.03, 0.0]
JUNK_CHANCE = [0, 0.25, 0.18, 0.12, 0.08, 0.05]
OWN_TOOL = [0, 0.0, 0.1, 0.2, 0.3, 0.4]            # bonus of the worker's own basic tool
MISSING_TOOL = 0.6                                  # output when a promised tool was never handed over

DURATIONS = {1: 1.1, 3: 1.0, 7: 0.92, 14: 0.85}
FOOD_DISCOUNT = 0.20
TOOL_DISCOUNT = 0.15
FOOD_NEED = 8                   # nutrition per day
NUTRITION = {"rations": 10, "meat_pie": 6, "stew": 6, "cheese": 4, "smoked_fish": 4, "bread": 3,
             "meat": 2, "eggs": 1, "milk": 1, "vegetables": 1, "fish": 1}
LICENSES = [(2, 0), (4, 5 * G), (6, 15 * G), (9, 40 * G), (12, 100 * G)]   # (slots, price)
TOOL_WEAR = 8.0                 # durability % per work day
TOOL_RETURN_MIN = 30.0          # tools below this durability are worn out when returned

# tool code -> output bonus, per profession; "luck" tools also unlock rarer finds
TOOLS = {
    "lumberjack": {"axe": 0.5, "saw": 0.3},
    "miner": {"pickaxe": 0.5, "lantern": 0.2},
    "herbalist": {"backpack": 0.4, "sack": 0.25},
    "farmer": {"cart": 0.7, "sack": 0.25},
    "hunter": {"bow": 0.45, "dagger": 0.25},
    "fisher": {"sail": 0.8, "fishing_rod": 0.5},
    SCAVENGER: {"backpack": 0.4, "sack": 0.25},
    "carpenter": {"saw": 0.5, "axe": 0.25},
    "blacksmith": {"hammer": 0.5},
    "tailor": {"lantern": 0.3},
    "leatherworker": {"dagger": 0.4},
    "alchemist": {"lantern": 0.3},
    "cook": {"barrel": 0.3},
    "mason": {"hammer": 0.4, "pickaxe": 0.3},
    "jeweler": {"lantern": 0.3, "hammer": 0.2},
}
LUCK_TOOLS = {"lantern"}

# code: (name, description, effects)
TRAITS = {
    "hardworking": ("Працьовитий", "+20% виробітку", {"output": 1.2, "wage": 1.1}),
    "lazy": ("Лінивий", "−20% виробітку, зате дешевший", {"output": 0.8, "wage": 0.85}),
    "lucky": ("Удачливий", "частіше знаходить рідкісне", {"luck": 1, "wage": 1.1}),
    "careful": ("Акуратний", "інструмент зношується вдвічі повільніше", {"wear": 0.5}),
    "glutton": ("Ненажера", "їсть майже вдвічі більше", {"food": 1.75}),
    "modest": ("Невибагливий", "мало їсть і рідше ображається", {"food": 0.75, "morale_loss": 0.5, "wage": 0.95}),
    "drunk": ("Пияк", "щодня потребує пива, інакше псується настрій", {"beer": 1, "wage": 0.85}),
    "thrifty": ("Ощадливий", "інколи не витрачає інгредієнти", {"save": 0.12}),
    "nightowl": ("Сова", "працює й уночі", {"night": 1, "wage": 1.1}),
    "smart": ("Тямущий", "вчиться вдвічі швидше", {"xp": 2}),
    "greedy": ("Жадібний", "+10% виробітку, але дорогий", {"output": 1.1, "wage": 1.3}),
}
CONFLICTS = [{"hardworking", "lazy"}, {"glutton", "modest"}]
EPITHETS = ["Кривий", "Швидкий", "Бородатий", "Тихий", "Рудий", "Мудрий", "Лисий", "Веселий", "Кремезний",
            "Сухорлявий", "Похмурий", "Співучий", "Безвусий", "Одноокий", "Кульгавий", "Молодий", "Старий"]
FEMALE_NAMES = {"Мирослава", "Ярина", "Любава", "Дарина", "Горислава", "Злата", "Веселина", "Ружена", "Леся",
                "Оксана", "Квітослава", "Ельдріна", "Сільвана", "Тіліель"}
MARKET_SIZE = 14

STATUS = {
    "working": "⚒️ Працює", "night": "🌙 Відпочиває (ніч)", "waiting": "⏳ Чекає інгредієнтів",
    "no_task": "💤 Немає завдання", "stocked": "✅ Запас заповнено", "hungry": "🍞 Голодний — працює вполсили",
    "idle": "🤝 Щойно найнятий, стане до роботи з наступною зміною",
}


class WorkerError(m.MarketError):
    pass


def is_female(name):
    return name.split()[0] in FEMALE_NAMES


def g(w, masc, fem):
    """Pick the grammatical form matching the worker's gender."""
    return fem if is_female(w["name"]) else masc


def make_name(rng):
    first, epithet = rng.choice(cat.FIRST_NAMES), rng.choice(EPITHETS)
    if first in FEMALE_NAMES:
        epithet = epithet[:-2] + "а"  # Кривий → Крива
    return f"{first} {epithet}"


# ------------------------------------------------------------------ helpers

def prof_name(prof):
    return SCAVENGER_NAME if prof == SCAVENGER else (cat.GATHER_PROFS | cat.CRAFT_PROFS)[prof]


def effect(traits, key, default=1.0):
    """Combined trait effect: multiplicative for factors, additive for flags."""
    val = default
    for t in traits:
        e = TRAITS[t][2]
        if key in e:
            val = val * e[key] if default == 1.0 else val + e[key]
    return val


def flag(traits, key):
    return effect(traits, key, 0) > 0


def base_wage(role, prof, level):
    if role == "crafter":
        return CRAFT_WAGE[level]
    return GATHER_WAGE[level] * (SCAVENGER_WAGE if prof == SCAVENGER else 1)


def contract_wage(ask, days, food, tool):
    return max(1, round(ask * DURATIONS[days] * (1 - FOOD_DISCOUNT * bool(food)) * (1 - TOOL_DISCOUNT * bool(tool))))


def slots_of(license_level):
    return LICENSES[min(license_level, len(LICENSES) - 1)][0]


def level_for_xp(xp):
    lvl = 1
    for L, need in XP_FOR_LEVEL.items():
        if xp >= need:
            lvl = L
    return lvl


def log(c, owner_id, worker_id, tick, kind, text):
    c.execute("INSERT INTO worker_log(owner_id, worker_id, tick, kind, text) VALUES(?,?,?,?,?)",
              (owner_id, worker_id, tick, kind, text))


def _row(c, worker_id):
    w = c.execute("SELECT * FROM workers WHERE id=?", (worker_id,)).fetchone()
    if not w:
        raise WorkerError("Працівника не знайдено")
    return w


def _own(c, worker_id, owner_id):
    w = _row(c, worker_id)
    if w["owner_id"] != owner_id:
        raise WorkerError("Це не ваш працівник")
    return w


def tool_bonus(engine, w):
    """Output multiplier from the equipped tool (or the worker's own basic one)."""
    if w["tool_item_id"]:
        code = engine.items[w["tool_item_id"]]["code"]
        return 1 + TOOLS.get(w["profession"], {}).get(code, 0)
    if w["tool_provided"]:
        return MISSING_TOOL
    return 1 + OWN_TOOL[w["level"]]


def gather_pool(engine, w_prof, level, luck):
    """Items a gatherer can find, with weights."""
    min_rarity = MIN_RARITY[max(0, min(5, level - luck))]
    if w_prof == SCAVENGER:
        pool = [(i, 3.0) for i in engine.junk]
        pool += [(i, 0.6) for i, it in engine.items.items() if it["gather_prof"] and it["rarity"] >= 0.9]
        return pool
    return [(i, it["rarity"]) for i, it in engine.items.items()
            if it["gather_prof"] == w_prof and it["rarity"] >= min_rarity]


def known_recipes(engine, prof, level):
    """Recipes a crafter of this level knows: tier <= level (all from Expert), junk recycling always."""
    return [r for r in engine.recipes_by_prof.get(prof, [])
            if r["is_alt"] or level >= 4 or engine.items[r["output_id"]]["tier"] <= level]


def daily_value(engine, w):
    """Expected copper of base value produced per work day at current conditions."""
    traits = json.loads(w["traits"])
    hours = DAY if flag(traits, "night") else WORK_TICKS
    base = CRAFT_VALUE[w["level"]] if w["role"] == "crafter" else GATHER_VALUE[w["level"]]
    if w["profession"] == SCAVENGER:
        base *= SCAVENGER_VALUE
    morale = 0.6 + 0.5 * w["morale"] / 100
    return base * hours / WORK_TICKS * effect(traits, "output") * tool_bonus(engine, w) * morale * (
        0.5 if w["hungry"] else 1)


# ------------------------------------------------------------------ labor market

def make_candidate(rng, engine, tick):
    role = "gatherer" if rng.random() < 0.55 else "crafter"
    if role == "gatherer":
        prof = rng.choice(list(cat.GATHER_PROFS) + [SCAVENGER, SCAVENGER])
    else:
        prof = rng.choice(list(cat.CRAFT_PROFS))
    level = rng.choices(range(1, 6), LEVEL_WEIGHTS)[0]
    pool = [t for t in TRAITS if not (t == "thrifty" and role != "crafter")]
    traits = []
    for _ in range(rng.choices([0, 1, 2], [35, 45, 20])[0]):
        t = rng.choice(pool)
        if t not in traits and not any(t in cf and set(traits) & cf for cf in CONFLICTS):
            traits.append(t)
    spec = None
    if role == "crafter":
        cats = sorted({engine.items[r["output_id"]]["category"] for r in engine.recipes_by_prof[prof]})
        spec = rng.choice(cats)
    ask = base_wage(role, prof, level) * effect(traits, "wage") * rng.uniform(0.85, 1.2)
    name = make_name(rng)
    xp = XP_FOR_LEVEL.get(level, 0) + rng.uniform(0, 2)
    return (name, role, prof, level, xp, json.dumps(traits), spec, max(1, round(ask)), rng.uniform(65, 90),
            tick + rng.randint(72, 288))


def refresh_market(c, engine):
    c.execute("DELETE FROM workers WHERE owner_id IS NULL AND available_until < ?", (engine.tick,))
    have = c.execute("SELECT COUNT(*) n FROM workers WHERE owner_id IS NULL").fetchone()["n"]
    for _ in range(max(0, MARKET_SIZE - have)):
        c.execute("INSERT INTO workers(name, role, profession, level, xp, traits, spec, ask_wage, morale,"
                  " available_until) VALUES(?,?,?,?,?,?,?,?,?,?)", make_candidate(engine.rng, engine, engine.tick))


# ------------------------------------------------------------------ contracts

def hire(c, engine, owner_id, worker_id, days, food, tool):
    if days not in DURATIONS:
        raise WorkerError("Невірний термін контракту")
    w = _row(c, worker_id)
    if w["owner_id"] is not None:
        raise WorkerError("Цього працівника вже найняли")
    lic = c.execute("SELECT license FROM traders WHERE id=?", (owner_id,)).fetchone()["license"]
    used = c.execute("SELECT COUNT(*) n FROM workers WHERE owner_id=?", (owner_id,)).fetchone()["n"]
    if used >= slots_of(lic):
        raise WorkerError("Усі місця за ліцензією гільдії зайняті — розширте ліцензію")
    wage = contract_wage(w["ask_wage"], days, food, tool)
    m.take_gold(c, owner_id, wage)  # first day is paid upfront
    c.execute("UPDATE workers SET owner_id=?, available_until=NULL, hired_tick=?, next_pay_tick=?, days_left=?,"
              " wage=?, food_provided=?, tool_provided=?, hungry=0, unpaid=0, progress=0, target_id=NULL,"
              " status='idle', status_detail=NULL, today='{}', tasks='[]', focus_item_id=NULL WHERE id=?",
              (owner_id, engine.tick, engine.tick + DAY, days, wage, int(bool(food)), int(bool(tool)), worker_id))
    w = _row(c, worker_id)
    if food:
        _feed(c, engine, w)
    log(c, owner_id, worker_id, engine.tick, "hire",
        f"{w['name']} ({prof_name(w['profession'])}) {g(w, 'підписав', 'підписала')} контракт на {days} дн. за {m.fmt_money(wage)}/день")
    return wage


def _release(c, engine, w, reason_kind, text, back_to_market=True):
    """End the contract: return the tool if usable, put the worker back on the labor market."""
    if w["tool_item_id"]:
        if (w["tool_durability"] or 0) >= TOOL_RETURN_MIN:
            m.add_items(c, w["owner_id"], w["tool_item_id"], 1)
            text += f" Інструмент «{engine.items[w['tool_item_id']]['name']}» повернуто."
        else:
            text += f" Інструмент «{engine.items[w['tool_item_id']]['name']}» зношено вщент."
    log(c, w["owner_id"], w["id"], engine.tick, reason_kind, text)
    if back_to_market:
        level = level_for_xp(w["xp"])
        ask = base_wage(w["role"], w["profession"], level) * effect(json.loads(w["traits"]), "wage")
        c.execute("UPDATE workers SET owner_id=NULL, available_until=?, level=?, ask_wage=?, morale=MAX(morale, 60),"
                  " tool_item_id=NULL, tool_durability=NULL, hungry=0, unpaid=0, status='idle', today='{}',"
                  " tasks='[]', focus_item_id=NULL, target_id=NULL, progress=0 WHERE id=?",
                  (engine.tick + DAY, level, round(ask * engine.rng.uniform(0.95, 1.1)), w["id"]))
    else:
        c.execute("DELETE FROM workers WHERE id=?", (w["id"],))


def fire(c, engine, owner_id, worker_id):
    w = _own(c, worker_id, owner_id)
    penalty = w["wage"]
    m.take_gold(c, owner_id, penalty)
    _release(c, engine, w, "fired", f"{w['name']} {g(w, 'звільнений', 'звільнена')}. Неустойка {m.fmt_money(penalty)}.")
    return penalty


def renew(c, engine, owner_id, worker_id, days):
    if days not in DURATIONS:
        raise WorkerError("Невірний термін контракту")
    w = _own(c, worker_id, owner_id)
    if w["morale"] < 40:
        raise WorkerError(f"{w['name']} {g(w, 'незадоволений', 'незадоволена')} (настрій {w['morale']:.0f}) і не хоче продовжувати")
    ask = w["ask_wage"]  # raised on level-up, so a renewal costs more after promotions
    wage = contract_wage(ask, days, w["food_provided"], w["tool_provided"])
    c.execute("UPDATE workers SET days_left=days_left+?, wage=?, ask_wage=? WHERE id=?", (days, wage, ask, worker_id))
    log(c, owner_id, worker_id, engine.tick, "renew",
        f"{w['name']}: контракт продовжено на {days} дн. Нова ЗП {m.fmt_money(wage)}/день.")
    return wage


def equip(c, engine, owner_id, worker_id, item_id):
    w = _own(c, worker_id, owner_id)
    code = engine.items[item_id]["code"]
    if code not in TOOLS.get(w["profession"], {}):
        raise WorkerError(f"{prof_name(w['profession'])} не користується «{engine.items[item_id]['name']}»")
    m.take_items(c, owner_id, item_id, 1)
    if w["tool_item_id"]:
        unequip(c, engine, owner_id, worker_id)
    c.execute("UPDATE workers SET tool_item_id=?, tool_durability=100 WHERE id=?", (item_id, worker_id))


def unequip(c, engine, owner_id, worker_id):
    w = _own(c, worker_id, owner_id)
    if not w["tool_item_id"]:
        raise WorkerError("Інструмента немає")
    returned = (w["tool_durability"] or 0) >= TOOL_RETURN_MIN
    if returned:
        m.add_items(c, owner_id, w["tool_item_id"], 1)
    c.execute("UPDATE workers SET tool_item_id=NULL, tool_durability=NULL WHERE id=?", (worker_id,))
    return returned


def set_focus(c, engine, owner_id, worker_id, item_id):
    w = _own(c, worker_id, owner_id)
    if w["role"] != "gatherer":
        raise WorkerError("Лише для збирачів")
    traits = json.loads(w["traits"])
    if item_id is not None and item_id not in {i for i, _ in gather_pool(engine, w["profession"], w["level"],
                                                                          _luck(engine, w, traits))}:
        raise WorkerError("Цей працівник не вміє знаходити такий товар")
    c.execute("UPDATE workers SET focus_item_id=?, target_id=NULL WHERE id=?", (item_id, worker_id))


def set_tasks(c, engine, owner_id, worker_id, tasks):
    w = _own(c, worker_id, owner_id)
    if w["role"] != "crafter":
        raise WorkerError("Лише для ремісників")
    known = {r["id"] for r in known_recipes(engine, w["profession"], w["level"])}
    clean = []
    for t in tasks[:3]:
        rid = int(t["recipe_id"])
        if rid not in known:
            raise WorkerError("Працівник не знає цього рецепта")
        clean.append({"recipe_id": rid, "keep": max(0, int(t.get("keep") or 0))})
    c.execute("UPDATE workers SET tasks=?, progress=0, target_id=NULL WHERE id=?", (json.dumps(clean), worker_id))


def upgrade_license(c, owner_id):
    lic = c.execute("SELECT license FROM traders WHERE id=?", (owner_id,)).fetchone()["license"]
    if lic + 1 >= len(LICENSES):
        raise WorkerError("Ліцензія вже максимальна")
    price = LICENSES[lic + 1][1]
    m.take_gold(c, owner_id, price)
    c.execute("UPDATE traders SET license=license+1 WHERE id=?", (owner_id,))
    return slots_of(lic + 1)


# ------------------------------------------------------------------ daily upkeep

def _luck(engine, w, traits):
    luck = effect(traits, "luck", 0)
    if w["tool_item_id"] and engine.items[w["tool_item_id"]]["code"] in LUCK_TOOLS:
        luck += 1
    return int(luck)


def _feed(c, engine, w):
    """Take a day's worth of food from the employer's inventory, cheapest nutrition first."""
    traits = json.loads(w["traits"])
    need = FOOD_NEED * effect(traits, "food")
    foods = []
    for code, nut in NUTRITION.items():
        i = engine.by_code[code]
        have = m.qty_of(c, w["owner_id"], i)
        if have:
            foods.append((engine.ref[i] / nut, i, nut, have))
    foods.sort()
    eaten = {}
    for _, i, nut, have in foods:
        if need <= 0:
            break
        n = min(have, math.ceil(need / nut))
        m.take_items(c, w["owner_id"], i, n)
        eaten[i] = n
        need -= n * nut
    hungry = need > 0
    mood = 0.0
    if hungry:
        mood -= 15
        log(c, w["owner_id"], w["id"], engine.tick, "hungry",
            f"{w['name']} {g(w, 'голодний', 'голодна')}: у коморі не вистачило їжі. Завтра працюватиме вполсили.")
    else:
        mood += 3 + (2 if len(eaten) >= 2 else 0)  # a varied menu cheers people up
    if flag(traits, "beer"):
        beer = engine.by_code["beer"]
        if m.qty_of(c, w["owner_id"], beer):
            m.take_items(c, w["owner_id"], beer, 1)
            mood += 3
        else:
            mood -= 12
            log(c, w["owner_id"], w["id"], engine.tick, "beer", f"{w['name']} без пива і в поганому гуморі.")
    c.execute("UPDATE workers SET hungry=? WHERE id=?", (int(hungry), w["id"]))
    return mood


def _payday(c, engine, w):
    traits = json.loads(w["traits"])
    loss = effect(traits, "morale_loss")
    mood = 0.0
    # experience for the day worked
    xp = w["xp"] + effect(traits, "xp")
    level = level_for_xp(xp)
    if level > w["level"]:
        log(c, w["owner_id"], w["id"], engine.tick, "level",
            f"🎉 {w['name']} тепер {LEVELS[level]}! Працюватиме краще, але на продовженні попросить більше.")
    days_left = w["days_left"] - 1
    ask = round(w["ask_wage"] * base_wage(w["role"], w["profession"], level) / base_wage(w["role"], w["profession"], w["level"]))
    c.execute("UPDATE workers SET xp=?, level=?, ask_wage=?, days_left=?, today='{}' WHERE id=?",
              (xp, level, ask, days_left, w["id"]))
    w = _row(c, w["id"])
    if days_left <= 0:
        _release(c, engine, w, "ended", f"{w['name']}: контракт завершено.")
        return

    # next day's wage, paid upfront
    if m.gold_of(c, w["owner_id"]) >= w["wage"]:
        m.take_gold(c, w["owner_id"], w["wage"])
        mood += 2
        c.execute("UPDATE workers SET unpaid=0 WHERE id=?", (w["id"],))
    else:
        mood -= 30
        c.execute("UPDATE workers SET unpaid=unpaid+1 WHERE id=?", (w["id"],))
        if w["unpaid"] + 1 >= 2:
            _release(c, engine, w, "quit", f"{w['name']} {g(w, 'пішов', 'пішла')}: двічі не отримав зарплату.")
            return
        log(c, w["owner_id"], w["id"], engine.tick, "unpaid",
            f"{w['name']}: не вистачило золота на зарплату ({m.fmt_money(w['wage'])}). Ще раз — і {g(w, 'він', 'вона')} піде.")

    if w["food_provided"]:
        mood += _feed(c, engine, w)
    if w["tool_provided"]:
        if w["tool_item_id"]:
            mood += 2
        else:
            mood -= 10
            log(c, w["owner_id"], w["id"], engine.tick, "no_tool",
                f"{w['name']} досі без обіцяного інструмента: працює гірше і ображається.")

    morale = max(0.0, min(100.0, w["morale"] + (mood * loss if mood < 0 else mood)))
    c.execute("UPDATE workers SET morale=?, next_pay_tick=next_pay_tick+? WHERE id=?", (morale, DAY, w["id"]))
    if morale <= 10:
        _release(c, engine, _row(c, w["id"]), "quit", f"{w['name']} {g(w, 'звільнився', 'звільнилася')}: настрій на нулі.")


# ------------------------------------------------------------------ work

def _working_hours(tick, traits):
    hour = tick * 10 % 1440 // 60
    return flag(traits, "night") or 6 <= hour < 22


def _wear_tool(c, engine, w, traits):
    if not w["tool_item_id"]:
        return
    dur = w["tool_durability"] - TOOL_WEAR / WORK_TICKS * effect(traits, "wear")
    if dur <= 0:
        log(c, w["owner_id"], w["id"], engine.tick, "tool_broken",
            f"{w['name']}: зламався інструмент «{engine.items[w['tool_item_id']]['name']}».")
        c.execute("UPDATE workers SET tool_item_id=NULL, tool_durability=NULL WHERE id=?", (w["id"],))
    else:
        c.execute("UPDATE workers SET tool_durability=? WHERE id=?", (dur, w["id"]))


def _rate(engine, w, traits):
    """Copper of base value produced per work tick."""
    base = CRAFT_VALUE[w["level"]] if w["role"] == "crafter" else GATHER_VALUE[w["level"]]
    if w["profession"] == SCAVENGER:
        base *= SCAVENGER_VALUE
    morale = 0.6 + 0.5 * w["morale"] / 100
    return base / WORK_TICKS * effect(traits, "output") * tool_bonus(engine, w) * morale * (0.5 if w["hungry"] else 1)


def _set_status(c, w, status, detail=None):
    if w["status"] != status or w["status_detail"] != detail:
        c.execute("UPDATE workers SET status=?, status_detail=? WHERE id=?", (status, detail, w["id"]))


def _add_today(c, w, item_id, qty):
    today = json.loads(w["today"])
    today[str(item_id)] = today.get(str(item_id), 0) + qty
    c.execute("UPDATE workers SET today=? WHERE id=?", (json.dumps(today), w["id"]))


def _gather(c, engine, w, traits):
    rng = engine.rng
    luck = _luck(engine, w, traits)
    pool = gather_pool(engine, w["profession"], w["level"], luck)
    target = w["target_id"]
    if w["focus_item_id"]:
        target = w["focus_item_id"]
    elif target is None or target not in {i for i, _ in pool}:
        items, weights = zip(*pool)
        target = rng.choices(items, [wt * (2 if luck and engine.items[i]["rarity"] < 0.3 else 1)
                                     for i, wt in zip(items, weights)])[0]
    progress = w["progress"] + _rate(engine, w, traits) * S["supply_mult"]
    base = engine.items[target]["base_price"]
    if progress >= base:
        units = int(progress // base)
        progress -= units * base
        m.add_items(c, w["owner_id"], target, units)
        _add_today(c, w, target, units)
        w = _row(c, w["id"])
        if rng.random() < JUNK_CHANCE[w["level"]] and w["profession"] != SCAVENGER:
            junk = rng.choice(engine.junk)
            n = rng.randint(1, 3)
            m.add_items(c, w["owner_id"], junk, n)
            _add_today(c, w, junk, n)
        target = None if not w["focus_item_id"] else target  # pick something else next time
    c.execute("UPDATE workers SET progress=?, target_id=? WHERE id=?", (progress, target, w["id"]))
    _set_status(c, w, "hungry" if w["hungry"] else "working")


def _missing(c, engine, owner_id, recipe):
    for i, q in recipe["ings"]:
        have = m.qty_of(c, owner_id, i)
        if have < q:
            return f"{engine.items[i]['name']} ×{q - have}"
    return None


def _craft(c, engine, w, traits):
    tasks = json.loads(w["tasks"])
    if not tasks:
        _set_status(c, w, "no_task")
        return
    recipes = {r["id"]: r for r in engine.recipes}
    chosen, waiting, stocked = None, None, 0
    for t in tasks:
        r = recipes[t["recipe_id"]]
        if t["keep"] and m.qty_of(c, w["owner_id"], r["output_id"]) >= t["keep"]:
            stocked += 1
            continue
        miss = _missing(c, engine, w["owner_id"], r)
        if miss is None:
            chosen = r
            break
        waiting = waiting or f"{engine.items[r['output_id']]['name']}: бракує {miss}"
    if chosen is None:
        if waiting:
            _set_status(c, w, "waiting", waiting)
        else:
            _set_status(c, w, "stocked")
        return

    out = engine.items[chosen["output_id"]]
    batch_value = out["base_price"] * chosen["output_qty"]
    speed = _rate(engine, w, traits) * (1.3 if out["category"] == w["spec"] else 1)
    progress = (w["progress"] if w["target_id"] == chosen["id"] else 0) + speed
    made = 0
    while progress >= batch_value and made < 20 and m.max_crafts(c, w["owner_id"], chosen["id"]):
        if engine.rng.random() < effect(traits, "save", 0):
            m.add_items(c, w["owner_id"], chosen["output_id"], chosen["output_qty"])  # thrifty: no ingredients used
        else:
            m.craft(c, w["owner_id"], chosen["id"], 1)
        progress -= batch_value
        made += chosen["output_qty"]
    if made:
        _add_today(c, w, chosen["output_id"], made)
    c.execute("UPDATE workers SET progress=?, target_id=? WHERE id=?", (min(progress, batch_value), chosen["id"], w["id"]))
    _set_status(c, w, "hungry" if w["hungry"] else "working")


def tick(c, engine):
    """Called by the engine every tick."""
    if engine.tick % 36 == 0:
        refresh_market(c, engine)
    for w in c.execute("SELECT * FROM workers WHERE owner_id IS NOT NULL").fetchall():
        if engine.tick >= w["next_pay_tick"]:
            _payday(c, engine, w)
            row = c.execute("SELECT * FROM workers WHERE id=? AND owner_id IS NOT NULL", (w["id"],)).fetchone()
            if not row:
                continue
            w = row
        traits = json.loads(w["traits"])
        if not _working_hours(engine.tick, traits):
            _set_status(c, w, "night")
            continue
        try:
            if w["role"] == "gatherer":
                _gather(c, engine, w, traits)
            else:
                _craft(c, engine, w, traits)
        except m.MarketError:
            pass
        _wear_tool(c, engine, _row(c, w["id"]), traits)


# ------------------------------------------------------------------ views

def view(c, engine, w, owner_id=None):
    traits = json.loads(w["traits"])
    out = {
        "id": w["id"], "name": w["name"], "role": w["role"], "profession": w["profession"],
        "profession_name": prof_name(w["profession"]), "level": w["level"], "level_name": LEVELS[w["level"]],
        "xp": round(w["xp"], 1), "next_level_xp": XP_FOR_LEVEL.get(w["level"] + 1),
        "traits": [{"code": t, "name": TRAITS[t][0], "desc": TRAITS[t][1]} for t in traits],
        "spec": w["spec"], "ask_wage": w["ask_wage"], "morale": round(w["morale"]),
        "food_need": round(FOOD_NEED * effect(traits, "food"), 1),
        "night": flag(traits, "night"), "drunk": flag(traits, "beer"),
        "tools": [{"item_id": engine.by_code[code], "bonus": b, "luck": code in LUCK_TOOLS}
                  for code, b in TOOLS.get(w["profession"], {}).items()],
        "daily_value": round(daily_value(engine, w)),
    }
    if w["role"] == "gatherer":
        luck = _luck(engine, w, traits)
        out["finds"] = [i for i, _ in sorted(gather_pool(engine, w["profession"], w["level"], luck),
                                            key=lambda x: -x[1])]
    else:
        out["recipes"] = [r["id"] for r in known_recipes(engine, w["profession"], w["level"])]
    if w["owner_id"] is None:
        out["available_in"] = (w["available_until"] or 0) - engine.tick
        return out
    out.update({
        "days_left": w["days_left"], "wage": w["wage"], "food_provided": bool(w["food_provided"]),
        "tool_provided": bool(w["tool_provided"]), "hungry": bool(w["hungry"]), "unpaid": w["unpaid"],
        "next_pay_in": w["next_pay_tick"] - engine.tick,
        "tool": {"item_id": w["tool_item_id"], "durability": round(w["tool_durability"], 1),
                 "bonus": TOOLS[w["profession"]][engine.items[w["tool_item_id"]]["code"]]}
        if w["tool_item_id"] else None,
        "tool_mult": round(tool_bonus(engine, w), 2),
        "focus_item_id": w["focus_item_id"], "tasks": json.loads(w["tasks"]),
        "status": w["status"], "status_name": STATUS.get(w["status"], w["status"]), "status_detail": w["status_detail"],
        "today": [{"item_id": int(i), "qty": q} for i, q in json.loads(w["today"]).items()],
        "progress": round(w["progress"]),
        "renew_wage": contract_wage(w["ask_wage"], 3, w["food_provided"], w["tool_provided"]),
    })
    return out


def tool_users(engine):
    """{tool item id: [profession names that use it]}."""
    out = {}
    for prof, tools in TOOLS.items():
        for code in tools:
            out.setdefault(engine.by_code[code], []).append(prof_name(prof))
    return out


def overview(c, engine, owner_id):
    lic = c.execute("SELECT license FROM traders WHERE id=?", (owner_id,)).fetchone()["license"]
    mine = [view(c, engine, w, owner_id) for w in
            c.execute("SELECT * FROM workers WHERE owner_id=? ORDER BY id", (owner_id,)).fetchall()]
    market = [view(c, engine, w) for w in
              c.execute("SELECT * FROM workers WHERE owner_id IS NULL ORDER BY level DESC, id").fetchall()]
    pantry = sum(NUTRITION[code] * m.qty_of(c, owner_id, engine.by_code[code]) for code in NUTRITION)
    need = sum(w["food_need"] for w in mine if w["food_provided"])
    return {
        "mine": mine, "market": market,
        "license": {"level": lic, "slots": slots_of(lic), "used": len(mine),
                    "next": {"slots": LICENSES[lic + 1][0], "price": LICENSES[lic + 1][1]} if lic + 1 < len(LICENSES) else None},
        "wage_bill": sum(w["wage"] for w in mine),
        "pantry": {"nutrition": pantry, "daily_need": need, "days": round(pantry / need, 1) if need else None,
                   "beer": m.qty_of(c, owner_id, engine.by_code["beer"]),
                   "beer_need": sum(1 for w in mine if w["drunk"] and w["food_provided"])},
        "rules": {"durations": DURATIONS, "food_discount": FOOD_DISCOUNT, "tool_discount": TOOL_DISCOUNT,
                  "nutrition": {engine.by_code[k]: v for k, v in NUTRITION.items()}, "levels": LEVELS,
                  "tool_wear": TOOL_WEAR, "tool_return_min": TOOL_RETURN_MIN,
                  "tools": tool_users(engine)},
    }

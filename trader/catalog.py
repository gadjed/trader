"""Static game content: items, recipes, professions, NPC consumers.

Raw items carry an explicit base price (copper). Crafted items get their base
price derived from the primary recipe (ingredients cost + markup).
Prices: 1 gold = 100 silver = 10 000 copper.
"""

GATHER_PROFS = {
    "lumberjack": "Лісоруб",
    "miner": "Шахтар",
    "herbalist": "Травник",
    "farmer": "Фермер",
    "hunter": "Мисливець",
    "fisher": "Рибалка",
}

CRAFT_PROFS = {
    "carpenter": "Тесляр",
    "blacksmith": "Коваль",
    "tailor": "Кравець",
    "leatherworker": "Шкірник",
    "alchemist": "Алхімік",
    "cook": "Кухар",
    "mason": "Муляр",
    "jeweler": "Ювелір",
}

# code, name, icon, category, gather profession, base price, rarity, gw2 id
RAW = [
    ("oak_log", "Дубова колода", "🪵", "Деревина", "lumberjack", 40, 1.0, 19727),
    ("pine_log", "Соснова колода", "🌲", "Деревина", "lumberjack", 25, 1.0, 19723),
    ("birch_log", "Березова колода", "🌳", "Деревина", "lumberjack", 30, 1.0, 19726),
    ("resin", "Смола", "🍯", "Деревина", "lumberjack", 35, 0.6, None),
    ("bark", "Дубова кора", "🍂", "Деревина", "lumberjack", 12, 0.9, None),
    ("brushwood", "Хмиз", "🌿", "Деревина", "lumberjack", 6, 1.0, None),

    ("iron_ore", "Залізна руда", "⛰️", "Руда й камінь", "miner", 45, 1.0, 19699),
    ("copper_ore", "Мідна руда", "🟠", "Руда й камінь", "miner", 35, 1.0, 19697),
    ("tin_ore", "Олов'яна руда", "⚪", "Руда й камінь", "miner", 40, 0.8, 19704),
    ("silver_ore", "Срібна руда", "🏔️", "Руда й камінь", "miner", 150, 0.35, 19703),
    ("gold_ore", "Золота руда", "✨", "Руда й камінь", "miner", 400, 0.15, 19698),
    ("coal", "Кам'яне вугілля", "⚫", "Руда й камінь", "miner", 20, 1.0, 19750),
    ("stone", "Камінь", "🪨", "Руда й камінь", "miner", 8, 1.0, None),
    ("clay", "Глина", "🟤", "Руда й камінь", "miner", 10, 1.0, None),
    ("sand", "Пісок", "🏜️", "Руда й камінь", "miner", 5, 1.0, None),
    ("sulfur", "Сірка", "🟡", "Руда й камінь", "miner", 60, 0.5, None),
    ("raw_ruby", "Необроблений рубін", "🔴", "Самоцвіти", "miner", 900, 0.04, 24464),
    ("raw_sapphire", "Необроблений сапфір", "🔵", "Самоцвіти", "miner", 850, 0.04, 24465),
    ("raw_emerald", "Необроблений смарагд", "🟢", "Самоцвіти", "miner", 950, 0.04, 24466),

    ("chamomile", "Ромашка", "🌼", "Трави", "herbalist", 15, 1.0, None),
    ("sage", "Шавлія", "🌱", "Трави", "herbalist", 25, 1.0, 12246),
    ("mandrake", "Корінь мандрагори", "🥕", "Трави", "herbalist", 120, 0.35, None),
    ("firebloom", "Вогнецвіт", "🌺", "Трави", "herbalist", 90, 0.4, None),
    ("mushroom", "Гриби", "🍄", "Трави", "herbalist", 18, 1.0, 12147),
    ("nightshade", "Беладона", "🫐", "Трави", "herbalist", 70, 0.5, None),

    ("wheat", "Пшениця", "🌾", "Ферма", "farmer", 8, 1.0, None),
    ("barley", "Ячмінь", "🌻", "Ферма", "farmer", 9, 1.0, None),
    ("flax", "Льон", "🪻", "Ферма", "farmer", 14, 1.0, 19718),
    ("cotton", "Бавовна", "☁️", "Ферма", "farmer", 16, 0.9, 19741),
    ("vegetables", "Овочі", "🥬", "Ферма", "farmer", 12, 1.0, 12332),
    ("eggs", "Яйця", "🥚", "Ферма", "farmer", 6, 1.0, 12143),
    ("milk", "Молоко", "🥛", "Ферма", "farmer", 10, 1.0, None),
    ("wool", "Шерсть", "🐑", "Ферма", "farmer", 22, 0.9, 19739),
    ("hops", "Хміль", "🍃", "Ферма", "farmer", 15, 0.8, None),

    ("raw_hide", "Сира шкура", "🐄", "Мисливство й рибальство", "hunter", 50, 1.0, 19719),
    ("fur", "Хутро", "🦊", "Мисливство й рибальство", "hunter", 130, 0.35, None),
    ("meat", "М'ясо", "🥩", "Мисливство й рибальство", "hunter", 30, 1.0, 24359),
    ("bones", "Кістки", "🦴", "Мисливство й рибальство", "hunter", 10, 1.0, 24344),
    ("feathers", "Пір'я", "🪶", "Мисливство й рибальство", "hunter", 8, 1.0, None),
    ("sinew", "Сухожилля", "🎗️", "Мисливство й рибальство", "hunter", 25, 0.8, None),

    ("fish", "Риба", "🐟", "Мисливство й рибальство", "fisher", 20, 1.0, None),
    ("shells", "Мушлі", "🐚", "Мисливство й рибальство", "fisher", 12, 1.0, None),
    ("seaweed", "Водорості", "🌊", "Мисливство й рибальство", "fisher", 7, 1.0, None),
    ("pearl", "Перлина", "🦪", "Самоцвіти", "fisher", 700, 0.05, 24536),
]

# Junk drops from any gathering activity. code, name, icon, base price
JUNK = [
    ("rusty_nail", "Іржавий цвях", "🔩", 2),
    ("broken_pot", "Битий горщик", "🏺", 4),
    ("old_horseshoe", "Стара підкова", "🧲", 6),
    ("rag", "Ганчірка", "🧦", 3),
    ("empty_bottle", "Порожня пляшка", "🍾", 5),
    ("rat_tail", "Щурячий хвіст", "🐀", 1),
    ("bent_spoon", "Погнута ложка", "🥄", 3),
    ("button", "Ґудзик", "🔘", 2),
    ("old_boot", "Старий чобіт", "👢", 4),
    ("broken_sword", "Уламок меча", "🗡️", 15),
    ("old_coin", "Стара монета", "🪙", 25),
    ("torn_map", "Клапоть мапи", "🗺️", 20),
]

# code, name, icon, category, gw2 id
CRAFTED = [
    ("oak_plank", "Дубова дошка", "🟫", "Деревина", 19714),
    ("pine_plank", "Соснова дошка", "📏", "Деревина", 19710),
    ("birch_plank", "Березова дошка", "🟨", "Деревина", 19713),
    ("beam", "Дубовий брус", "🪜", "Деревина", None),
    ("handle", "Дерев'яне руків'я", "🥢", "Деревина", 19758),
    ("charcoal", "Деревне вугілля", "⬛", "Деревина", None),

    ("iron_ingot", "Залізний злиток", "⬜", "Метали", 19683),
    ("copper_ingot", "Мідний злиток", "🟧", "Метали", 19680),
    ("tin_ingot", "Олов'яний злиток", "◽", "Метали", None),
    ("bronze_ingot", "Бронзовий злиток", "🥉", "Метали", 19679),
    ("steel_ingot", "Сталевий злиток", "🔷", "Метали", 19688),
    ("silver_ingot", "Срібний злиток", "🥈", "Метали", 19687),
    ("gold_ingot", "Золотий злиток", "🥇", "Метали", 19682),

    ("nails", "Цвяхи", "📌", "Метизи", None),
    ("hinge", "Дверні петлі", "🚪", "Метизи", None),
    ("iron_hoop", "Залізний обруч", "⭕", "Метизи", None),
    ("chain", "Ланцюг", "⛓️", "Метизи", None),
    ("horseshoe", "Підкова", "🐴", "Метизи", None),

    ("linen_thread", "Лляні нитки", "🧵", "Тканини", None),
    ("wool_yarn", "Вовняна пряжа", "🧶", "Тканини", None),
    ("linen_cloth", "Полотно", "🏳️", "Тканини", 19720),
    ("cotton_cloth", "Бавовняна тканина", "🤍", "Тканини", 19742),
    ("wool_cloth", "Сукно", "🟪", "Тканини", 19740),
    ("rope", "Мотузка", "🪢", "Тканини", None),

    ("leather", "Вичинена шкіра", "🧳", "Шкіра", 19738),
    ("belt", "Ремінь", "〰️", "Шкіра", None),

    ("glass", "Скло", "🪟", "Алхімія", None),
    ("vial", "Скляна колба", "🧪", "Алхімія", None),
    ("dye", "Барвник", "🎨", "Алхімія", None),
    ("candle", "Свічка", "🕯️", "Алхімія", None),

    ("healing_potion", "Зілля лікування", "❤️", "Зілля", None),
    ("mana_potion", "Зілля мани", "💙", "Зілля", None),
    ("fire_potion", "Вогняне зілля", "🔥", "Зілля", None),
    ("antidote", "Протиотрута", "💚", "Зілля", None),
    ("elixir", "Еліксир сили", "💪", "Зілля", None),
    ("dubious_potion", "Сумнівне зілля", "🧃", "Зілля", None),

    ("flour", "Борошно", "🍚", "Їжа", 12136),
    ("bread", "Хліб", "🍞", "Їжа", None),
    ("beer", "Пиво", "🍺", "Їжа", None),
    ("smoked_fish", "Копчена риба", "🐠", "Їжа", None),
    ("meat_pie", "М'ясний пиріг", "🥧", "Їжа", None),
    ("cheese", "Сир", "🧀", "Їжа", None),
    ("stew", "Рагу", "🍲", "Їжа", None),
    ("rations", "Похідний пайок", "🥪", "Їжа", None),

    ("brick", "Цегла", "🧱", "Будівництво", None),
    ("cut_stone", "Тесаний камінь", "🗿", "Будівництво", None),
    ("mortar", "Будівельний розчин", "🪣", "Будівництво", None),
    ("fireplace", "Камін", "♨️", "Будівництво", None),
    ("well", "Криниця", "⛲", "Будівництво", None),
    ("house_kit", "Набір «Хатинка»", "🏠", "Будівництво", None),

    ("barrel", "Бочка", "🛢️", "Меблі й побут", None),
    ("chair", "Стілець", "🪑", "Меблі й побут", None),
    ("table", "Стіл", "🍽️", "Меблі й побут", None),
    ("chest", "Скриня", "🧰", "Меблі й побут", None),
    ("bed", "Ліжко", "🛏️", "Меблі й побут", None),
    ("lantern", "Ліхтар", "🏮", "Меблі й побут", None),
    ("carpet", "Килим", "🟥", "Меблі й побут", None),
    ("bell", "Бронзовий дзвін", "🔔", "Меблі й побут", None),
    ("sack", "Мішок", "🛍️", "Меблі й побут", None),

    ("axe", "Сокира", "🪓", "Інструменти", None),
    ("pickaxe", "Кайло", "⛏️", "Інструменти", None),
    ("hammer", "Молот", "🔨", "Інструменти", None),
    ("saw", "Пилка", "🪚", "Інструменти", None),
    ("fishing_rod", "Вудка", "🎣", "Інструменти", None),
    ("backpack", "Наплічник", "🎒", "Інструменти", None),
    ("saddle", "Сідло", "🏇", "Інструменти", None),
    ("sail", "Вітрило", "⛵", "Інструменти", None),
    ("cart", "Віз", "🛒", "Інструменти", None),

    ("dagger", "Кинджал", "🔪", "Зброя", None),
    ("sword", "Сталевий меч", "⚔️", "Зброя", None),
    ("bow", "Лук", "🏹", "Зброя", None),
    ("arrows", "Стріли", "🎯", "Зброя", None),
    ("wooden_shield", "Дерев'яний щит", "🛡️", "Зброя", None),
    ("firebomb", "Вибухова суміш", "💥", "Зброя", None),

    ("helmet", "Шолом", "🪖", "Одяг і броня", None),
    ("chainmail", "Кольчуга", "🥋", "Одяг і броня", None),
    ("leather_armor", "Шкіряний обладунок", "🦺", "Одяг і броня", None),
    ("plate_armor", "Латний обладунок", "🤺", "Одяг і броня", None),
    ("boots", "Шкіряні чоботи", "🥾", "Одяг і броня", None),
    ("gloves", "Рукавиці", "🧤", "Одяг і броня", None),
    ("cloak", "Вовняний плащ", "🧥", "Одяг і броня", None),
    ("shirt", "Сорочка", "👕", "Одяг і броня", None),
    ("hat", "Капелюх з пером", "🎩", "Одяг і броня", None),
    ("fur_hat", "Хутряна шапка", "🧢", "Одяг і броня", None),

    ("ruby", "Огранений рубін", "♦️", "Самоцвіти", None),
    ("sapphire", "Огранений сапфір", "💠", "Самоцвіти", None),
    ("emerald", "Огранений смарагд", "❇️", "Самоцвіти", None),

    ("silver_ring", "Срібна каблучка", "💍", "Прикраси", None),
    ("gold_ring", "Перстень з рубіном", "💎", "Прикраси", None),
    ("pearl_necklace", "Перлове намисто", "📿", "Прикраси", None),
    ("amulet", "Смарагдовий амулет", "🧿", "Прикраси", None),
    ("tiara", "Діадема", "👸", "Прикраси", None),
    ("crown", "Корона", "👑", "Прикраси", None),

    ("treasure_map", "Мапа скарбів", "📜", "Колекційне", None),
    ("coin_collection", "Колекція монет", "🏆", "Колекційне", None),
]

# profession, output, output qty, ingredients, alt (alternative recipe: not used for base price)
RECIPES = [
    ("carpenter", "oak_plank", 4, {"oak_log": 1}),
    ("carpenter", "pine_plank", 4, {"pine_log": 1}),
    ("carpenter", "birch_plank", 4, {"birch_log": 1}),
    ("carpenter", "beam", 1, {"oak_plank": 3}),
    ("carpenter", "handle", 3, {"birch_plank": 1}),
    ("carpenter", "charcoal", 2, {"brushwood": 5}),
    ("carpenter", "barrel", 1, {"oak_plank": 6, "iron_hoop": 2}),
    ("carpenter", "chair", 1, {"pine_plank": 4, "nails": 6}),
    ("carpenter", "table", 1, {"pine_plank": 6, "beam": 2, "nails": 10}),
    ("carpenter", "chest", 1, {"oak_plank": 8, "hinge": 2, "nails": 10}),
    ("carpenter", "bed", 1, {"pine_plank": 8, "wool_cloth": 3, "nails": 12}),
    ("carpenter", "cart", 1, {"beam": 4, "oak_plank": 10, "iron_hoop": 4, "nails": 30}),
    ("carpenter", "bow", 1, {"birch_plank": 2, "sinew": 3}),
    ("carpenter", "arrows", 20, {"birch_plank": 1, "feathers": 4, "nails": 10}),
    ("carpenter", "wooden_shield", 1, {"oak_plank": 4, "leather": 1, "nails": 8}),
    ("carpenter", "fishing_rod", 1, {"birch_plank": 1, "linen_thread": 3}),

    ("blacksmith", "iron_ingot", 1, {"iron_ore": 2, "coal": 1}),
    ("blacksmith", "copper_ingot", 1, {"copper_ore": 2, "coal": 1}),
    ("blacksmith", "tin_ingot", 1, {"tin_ore": 2, "coal": 1}),
    ("blacksmith", "bronze_ingot", 4, {"copper_ingot": 3, "tin_ingot": 1}),
    ("blacksmith", "steel_ingot", 1, {"iron_ingot": 2, "coal": 2}),
    ("blacksmith", "silver_ingot", 1, {"silver_ore": 2, "coal": 1}),
    ("blacksmith", "gold_ingot", 1, {"gold_ore": 2, "coal": 1}),
    ("blacksmith", "nails", 30, {"iron_ingot": 1}),
    ("blacksmith", "hinge", 2, {"iron_ingot": 1}),
    ("blacksmith", "iron_hoop", 1, {"iron_ingot": 1}),
    ("blacksmith", "chain", 1, {"iron_ingot": 3}),
    ("blacksmith", "horseshoe", 2, {"iron_ingot": 1, "nails": 4}),
    ("blacksmith", "dagger", 1, {"steel_ingot": 1, "handle": 1, "leather": 1}),
    ("blacksmith", "sword", 1, {"steel_ingot": 3, "handle": 1, "leather": 1}),
    ("blacksmith", "axe", 1, {"iron_ingot": 3, "handle": 1}),
    ("blacksmith", "pickaxe", 1, {"iron_ingot": 3, "handle": 1}),
    ("blacksmith", "hammer", 1, {"iron_ingot": 2, "handle": 1}),
    ("blacksmith", "saw", 1, {"steel_ingot": 1, "handle": 1}),
    ("blacksmith", "helmet", 1, {"steel_ingot": 3, "leather": 1}),
    ("blacksmith", "chainmail", 1, {"chain": 6, "leather": 2}),
    ("blacksmith", "plate_armor", 1, {"steel_ingot": 10, "leather": 3, "belt": 2}),
    ("blacksmith", "bell", 1, {"bronze_ingot": 8, "chain": 1}),
    ("blacksmith", "lantern", 1, {"iron_ingot": 1, "glass": 2, "candle": 1}),

    ("tailor", "linen_thread", 2, {"flax": 3}),
    ("tailor", "wool_yarn", 1, {"wool": 2}),
    ("tailor", "linen_cloth", 1, {"linen_thread": 4}),
    ("tailor", "cotton_cloth", 1, {"cotton": 4}),
    ("tailor", "wool_cloth", 1, {"wool_yarn": 3}),
    ("tailor", "rope", 1, {"flax": 4}),
    ("tailor", "sack", 1, {"linen_cloth": 2, "linen_thread": 1}),
    ("tailor", "shirt", 1, {"cotton_cloth": 2, "linen_thread": 1, "button": 4}),
    ("tailor", "cloak", 1, {"wool_cloth": 3, "linen_thread": 2, "fur": 1}),
    ("tailor", "hat", 1, {"wool_cloth": 1, "feathers": 3}),
    ("tailor", "carpet", 1, {"wool_yarn": 10, "dye": 2}),
    ("tailor", "sail", 1, {"linen_cloth": 8, "rope": 4}),

    ("leatherworker", "leather", 1, {"raw_hide": 1, "bark": 2}),
    ("leatherworker", "belt", 1, {"leather": 1, "nails": 2}),
    ("leatherworker", "boots", 1, {"leather": 2, "linen_thread": 2}),
    ("leatherworker", "gloves", 1, {"leather": 1, "linen_thread": 1}),
    ("leatherworker", "leather_armor", 1, {"leather": 6, "linen_thread": 4, "belt": 1}),
    ("leatherworker", "saddle", 1, {"leather": 5, "iron_hoop": 1, "wool_cloth": 1}),
    ("leatherworker", "backpack", 1, {"leather": 3, "rope": 1, "belt": 2}),
    ("leatherworker", "fur_hat", 1, {"fur": 2, "leather": 1}),

    ("alchemist", "glass", 1, {"sand": 4, "coal": 1}),
    ("alchemist", "vial", 3, {"glass": 1}),
    ("alchemist", "dye", 2, {"seaweed": 4, "mushroom": 1}),
    ("alchemist", "candle", 2, {"resin": 1, "linen_thread": 1}),
    ("alchemist", "healing_potion", 1, {"chamomile": 2, "sage": 1, "vial": 1}),
    ("alchemist", "mana_potion", 1, {"mandrake": 1, "sage": 2, "vial": 1}),
    ("alchemist", "fire_potion", 1, {"firebloom": 2, "sulfur": 1, "vial": 1}),
    ("alchemist", "antidote", 1, {"nightshade": 1, "mushroom": 2, "vial": 1}),
    ("alchemist", "elixir", 1, {"healing_potion": 1, "mana_potion": 1, "bones": 3}),
    ("alchemist", "firebomb", 2, {"sulfur": 2, "charcoal": 3, "broken_pot": 1}),
    ("alchemist", "dubious_potion", 1, {"rat_tail": 5, "vial": 1}),

    ("cook", "flour", 1, {"wheat": 4}),
    ("cook", "bread", 2, {"flour": 2, "eggs": 1}),
    ("cook", "beer", 4, {"barley": 4, "hops": 2}),
    ("cook", "smoked_fish", 2, {"fish": 2, "brushwood": 2}),
    ("cook", "meat_pie", 2, {"flour": 1, "meat": 2, "eggs": 1}),
    ("cook", "cheese", 1, {"milk": 5}),
    ("cook", "stew", 2, {"meat": 1, "vegetables": 3, "mushroom": 1}),
    ("cook", "rations", 3, {"bread": 2, "cheese": 1, "smoked_fish": 1}),

    ("mason", "brick", 4, {"clay": 3, "coal": 1}),
    ("mason", "cut_stone", 1, {"stone": 4}),
    ("mason", "mortar", 2, {"sand": 3, "clay": 1, "stone": 1}),
    ("mason", "fireplace", 1, {"brick": 40, "cut_stone": 10, "mortar": 6, "iron_ingot": 2}),
    ("mason", "well", 1, {"cut_stone": 30, "mortar": 10, "rope": 3, "chain": 1}),
    ("mason", "house_kit", 1, {"beam": 20, "oak_plank": 40, "brick": 60, "nails": 200, "hinge": 4, "glass": 6}),

    ("jeweler", "ruby", 1, {"raw_ruby": 1}),
    ("jeweler", "sapphire", 1, {"raw_sapphire": 1}),
    ("jeweler", "emerald", 1, {"raw_emerald": 1}),
    ("jeweler", "silver_ring", 1, {"silver_ingot": 1}),
    ("jeweler", "gold_ring", 1, {"gold_ingot": 1, "ruby": 1}),
    ("jeweler", "pearl_necklace", 1, {"pearl": 5, "silver_ingot": 1}),
    ("jeweler", "amulet", 1, {"silver_ingot": 2, "emerald": 1}),
    ("jeweler", "tiara", 1, {"silver_ingot": 4, "sapphire": 3, "pearl": 2}),
    ("jeweler", "crown", 1, {"gold_ingot": 10, "ruby": 2, "sapphire": 2, "emerald": 2, "pearl": 4}),
    ("jeweler", "treasure_map", 1, {"torn_map": 4, "dye": 1}),
    ("jeweler", "coin_collection", 1, {"old_coin": 12, "chest": 1}),
]

# Alternative recipes: junk recycling and substitutes. Not used for base prices.
ALT_RECIPES = [
    ("blacksmith", "iron_ingot", 1, {"rusty_nail": 25}),
    ("blacksmith", "iron_ingot", 1, {"old_horseshoe": 3}),
    ("blacksmith", "steel_ingot", 1, {"broken_sword": 2}),
    ("blacksmith", "tin_ingot", 1, {"bent_spoon": 4}),
    ("tailor", "linen_thread", 1, {"rag": 6}),
    ("tailor", "button", 6, {"shells": 2}),
    ("leatherworker", "leather", 1, {"old_boot": 2}),
    ("alchemist", "glass", 1, {"empty_bottle": 3}),
    ("mason", "mortar", 2, {"shells": 3, "sand": 3, "clay": 1}),
    ("mason", "mortar", 1, {"broken_pot": 2, "sand": 2}),
]

LUXURY_CATEGORIES = {"Прикраси", "Колекційне"}

# NPC demand sources. name, categories of interest, purchase scale
CONSUMERS = [
    ("Таверна «Ситий Кабан»", ["Їжа", "Ферма"], 1.2),
    ("Армія Північного рубежу", ["Зброя", "Одяг і броня", "Зілля", "Їжа"], 1.5),
    ("Королівський двір", ["Прикраси", "Самоцвіти", "Меблі й побут"], 1.0),
    ("Будівельна артіль «Цегла»", ["Будівництво", "Деревина", "Метизи", "Руда й камінь"], 1.3),
    ("Шукачі пригод", ["Зілля", "Зброя", "Інструменти", "Одяг і броня", "Їжа"], 1.0),
    ("Містяни Златограда", ["Їжа", "Одяг і броня", "Меблі й побут", "Тканини"], 1.3),
    ("Колекціонер дивацтв", ["Хлам", "Колекційне", "Самоцвіти"], 0.8),
    ("Ремісничий цех", ["Метали", "Тканини", "Шкіра", "Алхімія", "Трави", "Ферма", "Мисливство й рибальство"], 1.2),
    ("Портове місто Солебриз", ["Інструменти", "Тканини", "Їжа", "Мисливство й рибальство"], 1.0),
    ("Шахтарське містечко", ["Інструменти", "Їжа", "Алхімія", "Руда й камінь"], 1.0),
    ("Вежа чарівників", ["Зілля", "Трави", "Самоцвіти", "Алхімія"], 0.9),
    ("Ринкова площа", None, 1.0),
]

FIRST_NAMES = [
    "Остап", "Богдан", "Тарас", "Мирослава", "Ярина", "Олекса", "Зореслав", "Любава",
    "Святослав", "Дарина", "Устим", "Горислава", "Любомир", "Злата", "Добриня", "Веселина",
    "Мстислав", "Ружена", "Всеволод", "Леся", "Гордій", "Оксана", "Назар", "Квітослава",
    "Торін", "Гримбальд", "Ельдріна", "Фаргус", "Сільвана", "Борк", "Тіліель", "Дрогар",
]
NICK_STYLES = ["{n}", "{n}_{p}", "xX{n}Xx", "{n}{d}", "Пан {n}", "{n} з Пагорбів", "Дід {n}", "{p}_{n}"]

# Market event templates. Categories hit by demand shocks.
DEMAND_UP = [
    (["Зброя", "Одяг і броня"], "Війна на кордоні", "Армія скуповує спорядження — попит на зброю та броню злетів."),
    (["Будівництво", "Деревина", "Метизи"], "Будівельний бум", "У Златограді закладають новий квартал. Будматеріали в ціні."),
    (["Їжа", "Ферма"], "Неврожай у провінціях", "Посуха вигубила поля — їжа дорожчає."),
    (["Зілля", "Трави"], "Епідемія лихоманки", "Цілителі не встигають — зілля та трави розкуповують миттєво."),
    (["Прикраси", "Самоцвіти"], "Королівське весілля", "Знать замовляє прикраси до свята."),
    (["Інструменти", "Метали"], "Відкрито нові копальні", "Шахтарі масово закуповують інструменти."),
    (["Меблі й побут", "Тканини"], "Новосілля у Новому кварталі", "Мешканці облаштовують житло."),
    (["Колекційне", "Хлам"], "Ярмарок дивацтв", "Колекціонери полюють на старожитності."),
]
DEMAND_DOWN = [
    (["Зброя", "Одяг і броня"], "Мирний договір", "Полки розпущено. Ринок завалено трофейним спорядженням."),
    (["Одяг і броня", "Тканини"], "Мода змінилась", "Нові фасони — старий одяг ніхто не хоче."),
    (["Їжа", "Ферма"], "Рекордний урожай", "Комори переповнені, їжа дешевшає."),
    (["Прикраси"], "Королівський указ проти розкоші", "Знать сховала коштовності."),
]
SUPPLY_UP = [
    ("Патч {v}: дроп «{item}» збільшено вдвічі", "Розробники підкрутили шанси випадіння. Очікується перенасичення."),
    ("Ботоферми заполонили локацію з «{item}»", "Боти фармлять цілодобово — ринок затоплює товаром."),
    ("Відкрито нове родовище: «{item}»", "Видобуток зріс у рази."),
]
SUPPLY_DOWN = [
    ("Обвал у шахті: «{item}» в дефіциті", "Видобуток зупинено до розчищення завалів."),
    ("Патч {v}: нерф дропу «{item}»", "Шанс випадіння знижено. Запаси тануть."),
    ("Банхвиля серед ботів: «{item}»", "Ботоводів забанили — пропозиція різко впала."),
]
CORNER = ("Картель скуповує «{item}»", "Гільдія «Золота Жаба» викупила лоти та переставила вдвічі дорожче.")

"""Runtime-tunable market parameters, persisted in the `world` table.

`S` is an in-memory cache read by the engine and the matching code; `save()`
writes changes through to the DB so they survive restarts.
"""
from .db import get_setting, set_setting

# key: (default, min, max, label, help)
SPEC = {
    "tick_seconds": (2.0, 0.2, 30.0, "Секунд на тік", "Реальний час одного тіку (10 ігрових хвилин)."),
    "paused": (0, 0, 1, "Пауза", "Зупинити симуляцію."),
    "ah_cut_pct": (5.0, 0.0, 50.0, "% біржі (комісія з продажу)",
                   "Скільки біржа забирає з кожної угоди у продавця."),
    "deposit_pct": (1.0, 0.0, 20.0, "Депозит за лот, %",
                    "Неповоротна плата за виставлення лоту від його вартості."),
    "demand_mult": (1.0, 0.1, 5.0, "Попит NPC", "Глобальний множник попиту споживачів."),
    "supply_mult": (1.0, 0.1, 5.0, "Видобуток", "Глобальний множник видобутку сировини."),
    "volatility": (1.0, 0.0, 5.0, "Волатильність", "Шум оцінок і дрейф фундаментальної вартості."),
    "event_rate": (1.0, 0.0, 10.0, "Частота подій", "Множник частоти ринкових подій (новин)."),
    "bot_activity": (1.0, 0.1, 5.0, "Активність ботів", "Скільки дій роблять боти за тік."),
    "gw2_sync": (0, 0, 1, "Синхронізація з GW2",
                 "Підтягувати настрої ринку з Guild Wars 2 Trading Post."),
    "gw2_weight": (0.5, 0.0, 1.0, "Вага GW2", "Наскільки сильно реальний ринок впливає на наш."),
}

PRESETS = {
    "normal": ("Звичайний ринок", {}),
    "calm": ("Спокійний", {"volatility": 0.5, "event_rate": 0.3}),
    "volatile": ("Волатильний", {"volatility": 2.0, "event_rate": 3.0, "bot_activity": 1.5}),
    "low_fee": ("Низька комісія (1%)", {"ah_cut_pct": 1.0, "deposit_pct": 0.0}),
    "high_fee": ("Висока комісія (15%)", {"ah_cut_pct": 15.0, "deposit_pct": 3.0}),
    "oversupply": ("Перенасичення", {"supply_mult": 2.2, "demand_mult": 0.7}),
    "deficit": ("Дефіцит", {"supply_mult": 0.45, "demand_mult": 1.4}),
    "crisis": ("Криза", {"demand_mult": 0.5, "event_rate": 2.5, "volatility": 1.5}),
}

S: dict[str, float] = {k: v[0] for k, v in SPEC.items()}


def load(c):
    for key, (default, *_rest) in SPEC.items():
        S[key] = float(get_setting(c, f"cfg.{key}", default))


def save(c, changes: dict):
    for key, value in changes.items():
        if key not in SPEC:
            raise KeyError(key)
        _default, lo, hi, *_ = SPEC[key]
        value = min(hi, max(lo, float(value)))
        S[key] = value
        set_setting(c, f"cfg.{key}", value)


def apply_preset(c, name: str):
    _title, overrides = PRESETS[name]
    values = {k: v[0] for k, v in SPEC.items() if k not in ("tick_seconds", "paused", "gw2_sync", "gw2_weight")}
    values.update(overrides)
    save(c, values)


def describe():
    return {
        "values": dict(S),
        "spec": {k: {"default": v[0], "min": v[1], "max": v[2], "label": v[3], "help": v[4]} for k, v in SPEC.items()},
        "presets": {k: {"title": t, "values": o} for k, (t, o) in PRESETS.items()},
    }

"""Digital Factory Model (DFM) cards data.

This module provides a concrete set of card definitions required by the
specification (section 2).  Each entry corresponds to a normative time card
used in the calculation of `Нвр`.  The values are taken from the standard
tables of ГОСТ 14.205‑83 and the Минтруд № 6 2000 norms.  They serve as a working
baseline – they can be refined later by domain experts.
"""

# The structure of each card follows the pattern used in the original
# specification: a dictionary with a short description and the numeric
# parameters required by the formulas (base time, coefficient, etc.).
# Only the fields that are actually used by the current stub implementation
# are populated; additional fields can be added when the full engine is
# completed.

CARDS = {
    # ---- General operative cards ------------------------------------------------
    1: {
        "description": "Base time per part (Т_шт – базовый)",
        "base_time_min": 0.5,  # minutes per operation (example value)
    },
    2: {
        "description": "Setup time (t_ву) – installation of the tool",
        "time_min": 1.2,
    },
    3: {
        "description": "Adjustment time (t_нш) – intermediate adjustments",
        "time_min": 0.8,
    },
    # ---- Specific cards mentioned in the spec -----------------------------------
    5: {
        "description": "Transition time between operations (t_пз)",
        "time_min": 1.05,
    },
    36: {
        "description": "粗加工 (черновое) – turning with tool T5K10",
        "time_factor": 1.0,
    },
    41: {
        "description": "Получистовое (получистовое) – turning with tool T15K6",
        "time_factor": 1.15,
    },
    42: {
        "description": "Тонкое (точное) – fine turning with tool T15K6",
        "time_factor": 1.30,
    },
    50: {
        "description": "Шлифовальная операция (кат. 58) – grinding",
        "time_min": 5.9,  # total time for a single grinding surface (see rule 1)
    },
    58: {
        "description": "Круглошлифовальная операция – special grinding step",
        "time_min": 5.9,
        "t_pz_min": 3.4,  # auxiliary time component from spec
    },
    60: {
        "description": "Фрезерная операция (карта 39) – pocketing",
        "time_min": 3.40,
    },
    73: {
        "description": "Унификация резца – минимальный радиус галтелей",
        "min_radius_mm": 1.6,
    },
    74: {
        "description": "Унификация резца – рекомендованный радиус",
        "recommended_radius_mm": 3.0,
    },
    # ---- Выполнение II (cards 39/40) -------------------------------------------
    39: {
        "description": "Фрезерная операция с пазом",
        "time_min": 3.40,
        "t_ву_min": 1.05,
        "t_pz_min": 25.0,
    },
    40: {
        "description": "Шлицефрезерная операция",
        "time_min": 30.0,
    },
}

# Export a convenient name for importers.
__all__ = ["CARDS"]

"""Расчет вспомогательного времени T_ву (от массы), T_вп, T_пз и K_тшт (§5.3 ТЗ)."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from ingro_dfm.classifier.setup_clusterer import SetupCluster
from ingro_dfm.classifier.tech_coder_10 import encode_l8_it_bucket
from ingro_dfm.core_schema.part_passport import FeatureOrFaceItem, PartPassport, ProductionType
from ingro_dfm.database.loader import load_drilling_db, load_milling_db, load_turning_db

logger = logging.getLogger(__name__)


def _first_ge_key(keys: List[str], val: float) -> str:
    parsed: List[Tuple[float, str]] = []
    for k in keys:
        try:
            parsed.append((float(str(k).replace(">", "").strip()), str(k)))
        except ValueError:
            continue
    parsed.sort(key=lambda item: item[0])
    for num, raw in parsed:
        if num >= val - 1e-9:
            return raw
    return parsed[-1][1]


def calc_t_vu_setup(
    passport: PartPassport,
    setup: SetupCluster,
    alignment_precision: str = "standard",
) -> float:
    """T_ву одного установа: зависит от массы заготовки M_заг и способа крепления."""
    m_blank = float(passport.blank_mass_kg)
    l_tot = float(passport.bounding_box_mm.get("L", 100.0))
    turn_db = load_turning_db()
    frez_db = load_milling_db()

    if setup.operation_kind == "grinding":
        # Базовое T_ву для круглошлифования / плоскошлифования
        base = float(turn_db["karta58"].get("T_vu_default_min", 0.65))
        if m_blank > 10.0:
            base *= 1.8
        elif m_blank > 3.0:
            base *= 1.25
        return round(base, 3)

    if setup.operation_kind == "turning":
        if setup.clamping_type == "centers":
            rows = [
                r for r in turn_db["karta5"]["rows"]
                if r.get("lunety", 0) == 0 and float(r["L_max"]) >= l_tot and float(r["mass_max"]) >= m_blank
            ]
            if rows:
                best = min(rows, key=lambda r: (float(r["L_max"]), float(r["mass_max"])))
                return round(float(best["time"]) * (0.7 if setup.setup_id > 1 else 1.0), 3)
        # Карта 3 (патрон, таблица по массе)
        k3_rows = turn_db["karta3"]["rows"]
        vyv = "с выверкой" if alignment_precision == "precise" else "без выверки"
        cand = [r for r in k3_rows if r.get("vyverka") == vyv] or k3_rows
        row = cand[0]
        mk = _first_ge_key(list(row["times"].keys()), m_blank)
        val = float(row["times"][mk])
        return round(val * (0.7 if setup.setup_id > 1 else 1.0), 3)

    # Фрезерно-сверлильные работы: Карта 4 FREZ2004 (по массе до 20 кг и свыше — подъемник/кран)
    if m_blank > 20.0:
        p61 = frez_db["karta4"]["poz61"]
        blk = p61["kran"] if m_blank > 30.0 else p61["podemnik"]
        for m, t in zip(blk["massy"], blk["times"]):
            if m_blank <= float(m):
                return round(float(t), 3)
        return round(float(blk["times"][-1]), 3)

    k4_rows = frez_db["karta4"]["rows"]
    poz_pref = 24 if setup.clamping_type == "vise" else 13
    cand = [r for r in k4_rows if r["poz"] == poz_pref] or k4_rows
    row = cand[0]
    mk = _first_ge_key(list(row["times"].keys()), m_blank)
    return round(float(row["times"][mk]), 3)


def calc_measurement_time(elem: FeatureOrFaceItem) -> float:
    """Время контрольных промеров элемента t_изм(IT_i, L_i)."""
    drill_db = load_drilling_db()["measurement_times_min"]
    l_dim = float(elem.dimensions.diameter_mm or elem.dimensions.length_or_depth_mm or 50.0)
    bucket = encode_l8_it_bucket(elem.pmi.it_grade)

    if bucket in ("IT_B1", "IT_B2"):
        tbl = drill_db["IT_B1_B2_caliper"]
    elif bucket == "IT_B3":
        tbl = drill_db["IT_B3_caliper_plug"]
    elif bucket == "IT_B4":
        tbl = drill_db["IT_B4_micrometer_bore"]
    else:
        tbl = drill_db["IT_B5_precision_gauge"]

    lk = _first_ge_key(list(tbl.keys()), l_dim)
    return float(tbl[lk]) * max(1, min(elem.dimensions.identical_count, 3))


def calc_t_vp_setup(setup: SetupCluster) -> Tuple[float, int]:
    """T_вп установа = N_инстр * t_см_инстр + sum(t_изм)."""
    drill_db = load_drilling_db()
    t_change = float(drill_db["tool_change_time_min"].get(setup.machine_type, 0.16))

    # Число уникальных переходов/инструментов в установе
    unique_tools = set()
    t_meas_sum = 0.0
    for elem in setup.elements:
        for tr in elem.classification.assigned_transitions:
            unique_tools.add((elem.geometry_type.value, tr))
        t_meas_sum += calc_measurement_time(elem)

    n_tools = max(1, len(unique_tools))
    t_vp = n_tools * t_change + t_meas_sum
    return round(t_vp, 3), n_tools


def calc_k_tsht(q: int, production_type: ProductionType, t_op: float) -> float:
    """Коэффициент K_тшт(q, ProductionType) по Карте 1 ЦБНТ + обслуживание/отдых."""
    turn_db = load_turning_db()
    if q <= 3:
        band = "1-3"
    elif q <= 6:
        band = "4-6"
    elif q <= 10:
        band = "7-10"
    elif q <= 15:
        band = "11-15"
    elif q <= 20:
        band = "16-20"
    elif q <= 30:
        band = "21-30"
    elif q <= 40:
        band = "31-40"
    else:
        band = ">40"

    k_part = 1.0
    for row in turn_db["karta1"]["rows"]:
        if t_op <= float(row["T_sht_max"]):
            k_part = float(row["k"].get(band, 1.0))
            break
    else:
        last = turn_db["karta1"]["rows"][-1]
        k_part = float(last["k"].get(band, 0.85))

    # Учет серийности / обслуживания рабочего места и отдыха (+6..8%)
    obs_factor = {
        ProductionType.SINGLE: 1.08,
        ProductionType.SMALL_BATCH: 1.06,
        ProductionType.MEDIUM_BATCH: 1.04,
        ProductionType.MASS: 1.02,
    }.get(production_type, 1.06)
    return round(k_part * obs_factor, 4)


def calc_t_pz_setup(setup: SetupCluster, n_tools: int, use_cnc: bool = False) -> float:
    """Подготовительно-заключительное время T_пз (мин) по виду станка и числу инструментов."""
    drill_db = load_drilling_db()["setup_tpz_min"]
    m_key = setup.machine_type
    if use_cnc and m_key == "universal_lathe":
        m_key = "cnc_lathe"
    spec = drill_db.get(m_key, {"base": 15.0, "per_tool": 2.0})
    return round(float(spec["base"]) + max(0, n_tools - 1) * float(spec["per_tool"]), 2)


__all__ = [
    "calc_t_vu_setup",
    "calc_measurement_time",
    "calc_t_vp_setup",
    "calc_k_tsht",
    "calc_t_pz_setup",
]

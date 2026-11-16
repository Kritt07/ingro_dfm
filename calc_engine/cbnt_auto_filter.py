"""Контур 1: Автоматический подбор нормативов из таблиц ЦБНТ / ОУНВ / FREZ2004 по параметрам КТЭ."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ingro_dfm.core_schema.part_passport import (
    FeatureOrFaceItem,
    GeomToleranceType,
    GeometryType,
    MaterialGroup,
    PartPassport,
)
from ingro_dfm.core_schema.pmi_utils import extract_hb_numeric
from ingro_dfm.database.loader import (
    load_drilling_db,
    load_materials_db,
    load_milling_db,
    load_turning_db,
)

logger = logging.getLogger(__name__)


@dataclass
class CBNTElementTrace:
    element_id: str
    source_norm: str
    card_ids: List[str]
    table_time_min: float
    t_hold_min: float
    k_hb: float
    k_holes: float
    k_rigidity: float
    k_blind: float
    k_geom_tol: float
    k_mat: float
    total_card_time_min: float
    notes: List[str] = field(default_factory=list)


def _first_ge_key(keys: Any, value: float) -> Optional[str]:
    numeric: List[Tuple[float, str]] = []
    for k in keys:
        try:
            numeric.append((float(str(k).replace(">", "").strip()), str(k)))
        except ValueError:
            continue
    numeric.sort(key=lambda pair: pair[0])
    for num, raw_key in numeric:
        if num >= value - 1e-9:
            return raw_key
    return numeric[-1][1] if numeric else None


def _pick_turning_row(rows: List[Dict[str, Any]], d: float, t: Optional[float] = None) -> Optional[Dict[str, Any]]:
    if not rows:
        return None
    if t is not None:
        cand = [r for r in rows if float(r["D_max"]) >= d and float(r.get("t_max", 999)) >= t]
        if cand:
            return min(cand, key=lambda r: (float(r["D_max"]), float(r.get("t_max", 0))))
    cand_d = [r for r in rows if float(r["D_max"]) >= d]
    if cand_d:
        return min(cand_d, key=lambda r: (float(r["D_max"]), float(r.get("t_max", 0))))
    return max(rows, key=lambda r: (float(r["D_max"]), float(r.get("t_max", 0))))


def _lookup_turning_time(rows: List[Dict[str, Any]], d: float, l_val: float, t: Optional[float] = None) -> float:
    row = _pick_turning_row(rows, d, t)
    if row is None:
        return 0.5
    lk = _first_ge_key(row["times"].keys(), l_val)
    return float(row["times"][lk]) if lk is not None else 0.5


def _lookup_k36(db: Dict[str, Any], d: float, l_val: float, t: float) -> float:
    return _lookup_turning_time(db["karta36"]["rows"], d, l_val, t=t)


def _lookup_k41(db: Dict[str, Any], d: float, l_val: float) -> float:
    rows = db["karta41"]["rows"] if l_val <= 550.0 else db["karta41"].get("rows_sheet2", db["karta41"]["rows"])
    return _lookup_turning_time(rows, d, l_val)


def _lookup_k43(db: Dict[str, Any], d: float, l_val: float) -> float:
    rows = db["karta43"]["rows"] if l_val <= 200.0 else db["karta43"].get("rows_sheet2", db["karta43"]["rows"])
    return _lookup_turning_time(rows, d, l_val)


def _lookup_k50(db: Dict[str, Any], d: float, width_b: float, depth_t: float) -> float:
    rows = db["karta50"]["rows"]
    cand = [r for r in rows if float(r["D_max"]) >= d and float(r["B_max"]) >= width_b]
    row = min(cand, key=lambda r: (float(r["D_max"]), float(r["B_max"]))) if cand else max(rows, key=lambda r: float(r["D_max"]))
    tk = _first_ge_key(row["times"].keys(), depth_t)
    return float(row["times"][tk]) if tk is not None else 0.5


def _lookup_k58_grinding(db: Dict[str, Any], d: float, l_val: float) -> float:
    rows = db["karta58"]["rows"]
    cand = [r for r in rows if float(r["D_max"]) >= d]
    row = min(cand, key=lambda r: float(r["D_max"])) if cand else max(rows, key=lambda r: float(r["D_max"]))
    lk = _first_ge_key(row["times"].keys(), l_val)
    return float(row["times"][lk]) if lk is not None else 1.4


def _lookup_k60_thread(db: Dict[str, Any], d: float, pitch: float, l_val: float) -> float:
    rows = db["karta60"]["rows"]
    cand = [r for r in rows if float(r["D_min"]) <= d <= float(r["D_max"]) and abs(float(r["P"]) - pitch) < 0.2]
    if not cand:
        cand = [r for r in rows if float(r["D_min"]) <= d <= float(r["D_max"])] or rows
    row = min(cand, key=lambda r: (abs(float(r["P"]) - pitch), float(r["D_max"])))
    lk = _first_ge_key(row["times"].keys(), l_val)
    return float(row["times"][lk]) if lk is not None else 1.2


def _lookup_k73_chamfer_or_fillet(db: Dict[str, Any], kind: str, d: float, size_w_or_r: float) -> float:
    tbl = db["karta73"]["faski" if kind == "chamfer" else "galteli"]
    cand = [r for r in tbl if float(r["D_max"]) >= d]
    row = min(cand, key=lambda r: float(r["D_max"])) if cand else max(tbl, key=lambda r: float(r["D_max"]))
    wk = _first_ge_key(row["times"].keys(), size_w_or_r)
    return float(row["times"][wk]) if wk is not None else 0.35


def _milling_mat_column(mat_group: MaterialGroup) -> str:
    if mat_group in (MaterialGroup.CAST_IRON_GRAY, MaterialGroup.CAST_IRON_DUCTILE):
        return "чугун"
    if mat_group == MaterialGroup.ALUMINUM_ALLOY:
        return "алюминий"
    return "сталь"


def _lookup_frez_t100(
    frez_db: Dict[str, Any],
    karta: str,
    width_b: float,
    depth_t: float,
    length_l: float,
    mat_group: MaterialGroup,
    cutter_d: Optional[float] = None,
    tile_width: bool = False,
) -> float:
    rows = frez_db[karta]["rows"]
    col = _milling_mat_column(mat_group)
    cand = [
        r for r in rows
        if float(r.get("B_max", 999)) >= width_b
        and float(r.get("t_max", 999)) >= depth_t
        and (cutter_d is None or float(r.get("D", 999)) >= cutter_d)
    ]
    if not cand:
        cand = [r for r in rows if float(r.get("B_max", 999)) >= min(width_b, max(float(x.get("B_max", 10)) for x in rows))] or rows
    row = min(cand, key=lambda r: (float(r.get("B_max", 999)), float(r.get("t_max", 999)), float(r.get("D", 999))))
    t100_dict = row["t100"]
    t100 = float(t100_dict.get(col) or t100_dict.get("сталь") or next(iter(t100_dict.values())))
    l1 = float(row.get("l1", 10.0))
    step_w = max(float(row.get("B_max", 20.0)), 10.0)
    n_width_passes = max(1, math.ceil(width_b / step_w)) if tile_width else 1
    return (t100 * (length_l + l1) / 100.0) * n_width_passes


def _lookup_frez_k36_keyway(frez_db: Dict[str, Any], width_w: float, depth_t: float, length_l: float) -> float:
    rows = frez_db["karta36"]["rows"]
    cand = [r for r in rows if float(r["D"]) >= width_w]
    row = min(cand, key=lambda r: float(r["D"])) if cand else max(rows, key=lambda r: float(r["D"]))
    v = row["vertikalno"]
    l1 = float(v.get("l1", 5.0))
    sm_prod = float(v.get("Sm_prod", 120.0))
    sm_vert = float(v.get("Sm_vert", 25.0))
    return (length_l + l1) / max(sm_prod, 1.0) + depth_t / max(sm_vert, 1.0)


def _lookup_drilling_table(drill_db: Dict[str, Any], key: str, d: float, l_val: float) -> float:
    cards = drill_db["drilling_cards"]
    if key == "center_drill":
        rows = cards["center_drill"]
        cand = [r for r in rows if float(r["D_max"]) >= d]
        row = min(cand, key=lambda r: float(r["D_max"])) if cand else max(rows, key=lambda r: float(r["D_max"]))
        return float(row["time_min"])
    rows = cards[key]
    cand = [r for r in rows if float(r["D_max"]) >= d]
    row = min(cand, key=lambda r: float(r["D_max"])) if cand else max(rows, key=lambda r: float(r["D_max"]))
    lk = _first_ge_key(row["times"].keys(), l_val)
    return float(row["times"][lk]) if lk is not None else 0.6


def _hardness_coeff(passport: PartPassport) -> float:
    hb = extract_hb_numeric(passport.hardness_hb_or_hrc)
    if hb is None:
        return 1.0
    if hb < 170.0:
        return 0.92
    if hb <= 210.0:
        return 1.0
    if hb <= 280.0:
        return 1.10
    if hb <= 380.0:
        return 1.25
    return 1.40


def _holes_batch_coeff(identical_count: int, drill_db: Dict[str, Any]) -> float:
    if identical_count <= 1:
        return 1.0
    for band in drill_db["hole_modifiers"]["k_identical_holes"]:
        if identical_count <= int(band["count_max"]):
            return float(band["k"])
    return 0.78


def _geom_tol_coeff(elem: FeatureOrFaceItem) -> float:
    gt = elem.pmi.geom_tolerance_type
    val = elem.pmi.geom_tolerance_val_mm
    if gt == GeomToleranceType.NONE:
        return 1.0
    if gt == GeomToleranceType.ORIENTATION:
        return 1.22 if (val is not None and val < 0.05) else 1.10
    if gt == GeomToleranceType.POSITION:
        return 1.30 if (val is not None and val < 0.05) else 1.18
    return 1.35 if (val is not None and val < 0.02) else 1.22


def estimate_element_cbnt(
    passport: PartPassport,
    elem: FeatureOrFaceItem,
    operation_kind: Optional[str] = None,
) -> CBNTElementTrace:
    """Автоматический подбор карты ЦБНТ/ОУНВ и расчет по формуле примечаний для 1 КТЭ."""
    turn_db = load_turning_db()
    frez_db = load_milling_db()
    drill_db = load_drilling_db()
    mat_info = load_materials_db()["materials"][passport.material_group.value]

    filters = elem.classification.cbnt_search_filters
    d = float(filters.get("filtr_Dcut") or elem.dimensions.diameter_mm or 35.0)
    l_val = float(filters.get("filtr_Lcut") or elem.dimensions.length_or_depth_mm or 30.0)
    t_allow = float(filters.get("filtr_tcut") or elem.dimensions.allowance_t_mm or 2.0)
    width = float(elem.dimensions.width_mm or min(d, 30.0))
    ra = elem.pmi.roughness_ra_um
    it = elem.pmi.it_grade

    cards: List[str] = []
    notes: List[str] = []
    t_tbl = 0.0
    t_hold = 0.0
    source_norm = "ЦБНТ ОУНВ Ч.1 (Токарная)"

    gtype = elem.geometry_type

    # Выбор таблицы нормирования по виду элемента и типу детали
    if gtype == GeometryType.CYLINDER_INT_HOLE:
        if operation_kind == "grinding":
            source_norm = "ЦБНТ ОУНВ (Внутреннее шлифование)"
            t_tbl = _lookup_k58_grinding(turn_db, d, l_val) * 1.15
            cards.append("К.58 (внутр. шлиф.)")
        else:
            source_norm = "ОУНВ Ч.3 (Сверлильно-расточная)"
            transitions = elem.classification.assigned_transitions
            if any("центров" in tr.lower() for tr in transitions):
                t_tbl += _lookup_drilling_table(drill_db, "center_drill", d, l_val)
                cards.append("ОУНВ-Св: Центрование")
            t_tbl += _lookup_drilling_table(drill_db, "twist_drill", d, l_val)
            cards.append("ОУНВ-Св: Сверление")
            if any("зенкер" in tr.lower() or "растач" in tr.lower() for tr in transitions):
                t_tbl += _lookup_drilling_table(drill_db, "counterbore", d, l_val)
                cards.append("ОУНВ-Св: Зенкерование/Растачивание")
            if any("разверт" in tr.lower() for tr in transitions):
                t_tbl += _lookup_drilling_table(drill_db, "reaming", d, l_val)
                cards.append("ОУНВ-Св: Развертывание")
            if operation_kind is None and any("шлиф" in tr.lower() for tr in transitions):
                t_tbl += _lookup_k58_grinding(turn_db, d, l_val) * 1.15
                cards.append("К.58 (внутр. шлиф.)")
            if elem.dimensions.is_blind:
                t_hold = float(drill_db["hole_modifiers"]["t_hold_depth_min"])

    elif gtype in (GeometryType.POCKET, GeometryType.SLOT, GeometryType.STEP) or (
        gtype == GeometryType.PLANE and not passport.is_rotational_part
    ):
        if operation_kind == "grinding":
            source_norm = "ЦБНТ ОУНВ (Плоское шлифование)"
            t_tbl = _lookup_k58_grinding(turn_db, min(max(d, width), 250.0), max(l_val, d)) * 0.90
            cards.append("К.58 (плоск. шлиф.)")
        else:
            source_norm = "FREZ2004 (ОУНВ Ч.2 Фрезерная)"
            if gtype == GeometryType.SLOT and passport.is_rotational_part:
                t_slot = _lookup_frez_k36_keyway(frez_db, max(width, 4.0), max(t_allow, 3.0), max(l_val, 20.0))
                t_tbl += t_slot
                cards.append("FREZ2004 К.36 (шпоночный паз)")
            elif gtype == GeometryType.SLOT:
                t_slot = _lookup_frez_t100(frez_db, "karta21", width, max(t_allow, 3.0), max(d, l_val), passport.material_group, tile_width=True)
                t_tbl += t_slot
                cards.append("FREZ2004 К.21 (паз)")
            elif gtype == GeometryType.POCKET:
                passes_z = max(1, math.ceil(max(l_val, t_allow) / 5.0))
                t_pkt = _lookup_frez_t100(frez_db, "karta20", width, 5.0, max(d, width), passport.material_group, tile_width=True) * passes_z
                t_tbl += t_pkt
                cards.append(f"FREZ2004 К.20 (карман, {passes_z} слоев)")
            else:
                karta = "karta19" if elem.area_mm2 >= 1800.0 else "karta20"
                t_pln = _lookup_frez_t100(frez_db, karta, width, max(t_allow, 2.0), max(d, l_val), passport.material_group, tile_width=True)
                t_tbl += t_pln
                cards.append(f"FREZ2004 {'К.19' if karta == 'karta19' else 'К.20'}")

            if ra <= 2.5 or it <= 10:
                t_tbl *= 1.45
                notes.append("Чистовой проход фрезерования (+45%)")
            if operation_kind is None and (ra <= 0.8 or it <= 6):
                t_tbl += _lookup_k58_grinding(turn_db, min(d, 200.0), max(l_val, 40.0)) * 0.85
                cards.append("К.58 (плоск. шлиф.)")

    elif gtype == GeometryType.SPLINE:
        source_norm = "ОУНВ Вып.II К.40 (Шлицефрезерование)"
        t_tbl = _lookup_frez_t100(frez_db, "karta34", 8.0, 4.0, l_val, passport.material_group) * 6.0
        cards.append("FREZ2004 К.34 / Вып.II К.40")

    elif gtype == GeometryType.THREAD:
        pitch = float(elem.dimensions.pitch_mm or 1.5)
        t_tbl = _lookup_k60_thread(turn_db, d, pitch, l_val)
        cards.append("ЦБНТ К.60 (резьба)")

    elif gtype == GeometryType.CHAMFER:
        w = float(elem.dimensions.width_mm or elem.dimensions.length_or_depth_mm or 1.5)
        t_tbl = _lookup_k73_chamfer_or_fillet(turn_db, "chamfer", d, w)
        cards.append("ЦБНТ К.73 (фаска)")

    elif gtype == GeometryType.GROOVE:
        if "галтел" in elem.name.lower() or elem.dimensions.radius_mm:
            r_val = float(elem.dimensions.radius_mm or elem.dimensions.width_mm or 2.0)
            t_tbl = _lookup_k73_chamfer_or_fillet(turn_db, "fillet", d, r_val)
            cards.append("ЦБНТ К.73 (галтель)")
        else:
            b_w = float(elem.dimensions.length_or_depth_mm or 4.0)
            t_d = float(elem.dimensions.width_mm or 3.0)
            t_tbl = _lookup_k50(turn_db, d, b_w, t_d)
            cards.append("ЦБНТ К.50 (канавка)")

    elif gtype == GeometryType.PLANE and passport.is_rotational_part:
        if operation_kind == "grinding":
            t_tbl = _lookup_k58_grinding(turn_db, d, 25.0) * 0.65
            cards.append("ЦБНТ К.58 (шлиф. торца)")
        else:
            # Подрезка торца (К.36 поперечное) + центровка (К.74) при наличии центров
            t_face = _lookup_k36(turn_db, d, max(d / 2.0, 15.0), min(t_allow, 3.0)) * 0.90
            t_tbl += t_face
            cards.append("ЦБНТ К.36 (подрезка торца)")
            if ra <= 3.2 or it <= 11:
                t_tbl += _lookup_k41(turn_db, d, max(d / 2.0, 15.0))
                cards.append("ЦБНТ К.41")

    else:
        # CYL, CON, SPH для тел вращения
        if operation_kind == "grinding":
            t_tbl = _lookup_k58_grinding(turn_db, d, l_val)
            cards.append("ЦБНТ К.58 (круглошлиф.)")
        else:
            passes = max(1, math.ceil(t_allow / 3.0))
            t_rough = _lookup_k36(turn_db, d, l_val, min(t_allow, 3.0)) * passes
            t_tbl += t_rough
            cards.append(f"ЦБНТ К.36 ({passes} пр.)")
            if ra <= 6.3 or it <= 11:
                t_tbl += _lookup_k41(turn_db, d, l_val)
                cards.append("ЦБНТ К.41")
            if ra <= 2.5 or it <= 9:
                t_tbl += _lookup_k43(turn_db, d, l_val)
                cards.append("ЦБНТ К.43")
            if operation_kind is None and (ra <= 0.8 or it <= 6):
                t_tbl += _lookup_k58_grinding(turn_db, d, l_val)
                cards.append("ЦБНТ К.58 (круглошлиф.)")
            if gtype == GeometryType.CONE:
                t_tbl *= 1.15
                notes.append("Конусность (+15%)")
            elif gtype == GeometryType.SPHERE:
                t_tbl *= 1.35
                notes.append("Сферический/фасонный профиль (+35%)")

    # Коэффициенты примечаний (формула §5.1)
    k_hb = _hardness_coeff(passport)
    k_holes = _holes_batch_coeff(elem.dimensions.identical_count, drill_db) if gtype == GeometryType.CYLINDER_INT_HOLE else 1.0
    k_rigidity = float(drill_db["hole_modifiers"]["k_rigidity_ld5"]) if (gtype in (GeometryType.CYLINDER_INT_HOLE, GeometryType.CYLINDER_EXT) and d > 0 and (l_val / d) > 5.0) else 1.0
    k_blind = float(drill_db["hole_modifiers"]["k_blind"]) if (gtype == GeometryType.CYLINDER_INT_HOLE and elem.dimensions.is_blind) else 1.0
    k_geom_tol = _geom_tol_coeff(elem)

    # Для фрезерных карт t100 материал уже учтен на 3 базовые группы, но коррозионностойкие/титан требуют доп. k_mat
    if "FREZ2004" in source_norm and passport.material_group in (MaterialGroup.CARBON_STEEL, MaterialGroup.CAST_IRON_GRAY, MaterialGroup.ALUMINUM_ALLOY):
        k_mat = 1.0
    else:
        k_mat = float(passport.k_mat_coeff or mat_info["k_mat_coeff"])

    n_qty = max(1, elem.dimensions.identical_count)
    total_card = (t_tbl + t_hold) * k_hb * k_holes * k_rigidity * k_blind * k_geom_tol * k_mat * n_qty

    return CBNTElementTrace(
        element_id=elem.element_id,
        source_norm=source_norm,
        card_ids=cards,
        table_time_min=round(t_tbl, 4),
        t_hold_min=round(t_hold, 4),
        k_hb=round(k_hb, 3),
        k_holes=round(k_holes, 3),
        k_rigidity=round(k_rigidity, 3),
        k_blind=round(k_blind, 3),
        k_geom_tol=round(k_geom_tol, 3),
        k_mat=round(k_mat, 3),
        total_card_time_min=round(total_card, 4),
        notes=notes,
    )


__all__ = ["CBNTElementTrace", "estimate_element_cbnt"]

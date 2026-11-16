"""Контур 2: Гибридная аналитико-регрессионная модель (MRR + Степенная регрессия по КТЭ)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from ingro_dfm.classifier.tech_coder_10 import encode_l8_it_bucket
from ingro_dfm.core_schema.part_passport import (
    FeatureOrFaceItem,
    GeomToleranceType,
    GeometryType,
    PartPassport,
)
from ingro_dfm.database.loader import load_materials_db, load_regression_weights

logger = logging.getLogger(__name__)


@dataclass
class RegressionElementTrace:
    element_id: str
    weight_key_used: str
    t_rough_mrr_min: float
    t_finish_reg_min: float
    alpha_v: float
    q_mrr_mm3_per_min: float
    alpha_0: float
    x1: float
    x2: float
    x3: float
    k_mat: float
    k_geom_tol: float
    identical_count: int
    total_osn_min: float


def _mrr_operation_bucket(geom: GeometryType, operation_kind: Optional[str] = None) -> str:
    if operation_kind == "grinding":
        return "grinding"
    if geom == GeometryType.CYLINDER_INT_HOLE:
        return "drilling"
    if geom in (GeometryType.SLOT, GeometryType.POCKET, GeometryType.STEP, GeometryType.SPLINE):
        return "milling"
    return "turning"


def _k_geom_tol(elem: FeatureOrFaceItem) -> float:
    gt = elem.pmi.geom_tolerance_type
    val = elem.pmi.geom_tolerance_val_mm
    if gt == GeomToleranceType.NONE:
        return 1.0
    if gt == GeomToleranceType.ORIENTATION:
        return 1.25 if (val is not None and val < 0.05) else 1.10
    if gt == GeomToleranceType.POSITION:
        return 1.35 if (val is not None and val < 0.05) else 1.15
    if gt == GeomToleranceType.FORM_RUNOUT:
        return 1.40 if (val is not None and val < 0.02) else 1.20
    return 1.0


def _pick_weights(weights_db: Dict[str, Dict], elem: FeatureOrFaceItem) -> tuple[str, Dict[str, float]]:
    weights = weights_db["weights"]
    full_code = elem.classification.tech_code_10 or ""
    l7 = elem.geometry_type.value
    l8 = encode_l8_it_bucket(elem.pmi.it_grade)

    for key in (full_code, f"{l7}.{l8}", l7, "DEFAULT"):
        if key and key in weights:
            return key, weights[key]
    return "DEFAULT", {"alpha_0": 0.012, "x1": 0.72, "x2": -0.24, "x3": -0.35}


def estimate_element_regression(
    passport: PartPassport,
    elem: FeatureOrFaceItem,
    operation_kind: Optional[str] = None,
    weights_path: Optional[Path] = None,
) -> RegressionElementTrace:
    """Расчет основного времени T_осн,i = (T_черн + T_чист) * k_мат * k_геом_доп * n."""
    weights_db = load_regression_weights(weights_path)
    mat_db = load_materials_db()["materials"][passport.material_group.value]

    g_key = elem.geometry_type.value
    alpha_v = float(weights_db.get("alpha_v_by_geometry", {}).get(g_key, 1.20))
    mrr_bucket = _mrr_operation_bucket(elem.geometry_type, operation_kind)
    q_mrr = float(mat_db["mrr_mm3_per_min"][mrr_bucket])

    # Если работа в режиме шлифования — снимаем только чистовой припуск и 35% чистовой регрессии;
    # в лезвийной операции при последующем шлифовании — 65% от T_чист (без дублирования).
    v_removed = float(elem.removed_volume_mm3)
    will_grind = (
        elem.geometry_type in (GeometryType.CYLINDER_EXT, GeometryType.CYLINDER_INT_HOLE, GeometryType.PLANE)
        and (elem.pmi.roughness_ra_um <= 0.8 or elem.pmi.it_grade <= 6 or any("шлиф" in tr.lower() for tr in elem.classification.assigned_transitions))
    )
    if operation_kind == "grinding":
        v_removed = min(v_removed, elem.area_mm2 * 0.20)
        finish_share = 0.35
    elif operation_kind is not None and will_grind:
        finish_share = 0.65
    else:
        finish_share = 1.0

    t_rough = (alpha_v * v_removed / max(q_mrr, 1.0)) if v_removed > 0 else 0.0

    weight_key, w = _pick_weights(weights_db, elem)
    alpha_0 = float(w["alpha_0"])
    x1 = float(w["x1"])
    x2 = float(w["x2"])
    x3 = float(w["x3"])

    s_mm2 = max(1.0, float(elem.area_mm2))
    ra_um = max(0.02, float(elem.pmi.roughness_ra_um))
    it_grade = max(1, int(elem.pmi.it_grade))

    t_finish = alpha_0 * (s_mm2 ** x1) * (ra_um ** x2) * (float(it_grade) ** x3) * finish_share

    k_mat = float(passport.k_mat_coeff or mat_db["k_mat_coeff"])
    k_geom = _k_geom_tol(elem)
    n_count = max(1, int(elem.dimensions.identical_count))

    total_osn = (t_rough + t_finish) * k_mat * k_geom * n_count
    return RegressionElementTrace(
        element_id=elem.element_id,
        weight_key_used=weight_key,
        t_rough_mrr_min=round(t_rough, 4),
        t_finish_reg_min=round(t_finish, 4),
        alpha_v=alpha_v,
        q_mrr_mm3_per_min=q_mrr,
        alpha_0=alpha_0,
        x1=x1,
        x2=x2,
        x3=x3,
        k_mat=round(k_mat, 3),
        k_geom_tol=round(k_geom, 3),
        identical_count=n_count,
        total_osn_min=round(total_osn, 4),
    )


__all__ = ["RegressionElementTrace", "estimate_element_regression"]

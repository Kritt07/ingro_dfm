"""Калибратор весов степенной регрессии (Ridge L2 + физические ограничения и Rollback)."""

from __future__ import annotations

import copy
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from pydantic import BaseModel
from scipy.optimize import lsq_linear
from sklearn.linear_model import Ridge

from ingro_dfm.calibration.cam_dataset_loader import CalibrationSample
from ingro_dfm.database.loader import (
    DATABASE_DIR,
    load_materials_db,
    load_regression_weights,
    save_regression_weights,
)

logger = logging.getLogger(__name__)


class CalibrationReport(BaseModel):
    weight_key: str
    samples_used: int
    method_used: str  # "sklearn.Ridge" | "sklearn.Ridge+ConstrainedL2"
    alpha_0: float
    x1: float
    x2: float
    x3: float
    r2_log_score: float
    previous_version: int
    new_version: int


def _extract_l7_from_code(tech_code_10: str) -> str:
    # Format: L1.L2.L3.L4.L5-L6.L7.L8.L9.L10
    if "-" in tech_code_10:
        right = tech_code_10.split("-", 1)[1].split(".")
        if len(right) >= 2:
            return right[1]
    return "CYL"


def _compute_finish_targets(samples: List[CalibrationSample], alpha_v_map: Dict[str, float]) -> Tuple[np.ndarray, np.ndarray]:
    """Строит матрицу X=[ln(S), ln(Ra), ln(IT)] и целевой вектор y=ln(T_чист)."""
    mats = load_materials_db()["materials"]
    x_rows: List[List[float]] = []
    y_vals: List[float] = []

    for s in samples:
        l7 = _extract_l7_from_code(s.tech_code_10)
        mat_info = mats.get(s.material_group, mats["ST_Carbon"])
        k_mat = float(mat_info["k_mat_coeff"])

        # Делим фактическое время на k_мат и вычитаем черновую составляющую MRR, если V_mm3 > 0
        mrr_bucket = "drilling" if l7 == "HOL" else ("milling" if l7 in ("SLT", "PKT", "STP", "SPL") else "turning")
        q_mrr = float(mat_info["mrr_mm3_per_min"][mrr_bucket])
        alpha_v = float(alpha_v_map.get(l7, 1.20))

        t_unscaled = max(0.02, float(s.cam_machining_time_min) / max(k_mat, 0.1))
        t_rough = (alpha_v * float(s.V_mm3) / max(q_mrr, 1.0)) if s.V_mm3 > 0 else 0.0
        # Если CAM время включало и черновую, но не дало опуститься ниже 15% от T_unscaled:
        t_finish = max(0.02, t_unscaled - t_rough) if (t_unscaled - t_rough) >= 0.05 else max(0.02, t_unscaled * 0.65)

        x_rows.append([math.log(max(s.S_mm2, 1.0)), math.log(max(s.Ra_um, 0.02)), math.log(max(float(s.IT_grade), 1.0))])
        y_vals.append(math.log(t_finish))

    return np.asarray(x_rows, dtype=float), np.asarray(y_vals, dtype=float)


def fit_constrained_ridge(
    samples: List[CalibrationSample],
    weight_key: str,
    alpha: float = 1.0,
    weights_path: Optional[Path] = None,
) -> CalibrationReport:
    """Выполняет калибровку коэффициентов через Ridge с гарантией x1 > 0, x2 < 0, x3 < 0."""
    if len(samples) < 4:
        raise ValueError(f"Слишком мало обучающих точек ({len(samples)} < 4) для калибровки '{weight_key}'.")

    target_path = weights_path or (DATABASE_DIR / "regression_weights.json")
    db = copy.deepcopy(load_regression_weights(target_path))
    alpha_v_map = db.get("alpha_v_by_geometry", {})

    X, y = _compute_finish_targets(samples, alpha_v_map)

    ridge = Ridge(alpha=alpha, fit_intercept=True)
    ridge.fit(X, y)
    x1, x2, x3 = float(ridge.coef_[0]), float(ridge.coef_[1]), float(ridge.coef_[2])
    beta_0 = float(ridge.intercept_)
    method = "sklearn.Ridge"

    # Проверка физических знаков и границ (§7.3: x1 > 0, x2 < 0, x3 < 0)
    bounds_cfg = db.get("physical_bounds", {})
    b_x1 = bounds_cfg.get("x1_area_exp", [0.6, 1.0])
    b_x2 = bounds_cfg.get("x2_ra_exp", [-0.45, -0.15])
    b_x3 = bounds_cfg.get("x3_it_exp", [-0.60, -0.20])

    if not (b_x1[0] <= x1 <= b_x1[1] and b_x2[0] <= x2 <= b_x2[1] and b_x3[0] <= x3 <= b_x3[1]):
        # Ridge с L2-регуляризацией и физическими ограничениями через lsq_linear
        n = X.shape[0]
        X_aug = np.hstack([np.ones((n, 1)), X])
        reg_rows = np.sqrt(alpha) * np.eye(4)
        reg_rows[0, 0] = 0.0  # не штрафуем свободный член beta_0
        A = np.vstack([X_aug, reg_rows])
        b = np.concatenate([y, np.zeros(4)])

        lb = np.array([-np.inf, float(b_x1[0]), float(b_x2[0]), float(b_x3[0])], dtype=float)
        ub = np.array([np.inf, float(b_x1[1]), float(b_x2[1]), float(b_x3[1])], dtype=float)
        sol = lsq_linear(A, b, bounds=(lb, ub))
        beta_0, x1, x2, x3 = [float(v) for v in sol.x]
        method = "sklearn.Ridge+ConstrainedL2"

    alpha_0 = math.exp(max(-12.0, min(6.0, beta_0)))
    y_pred = beta_0 + x1 * X[:, 0] + x2 * X[:, 1] + x3 * X[:, 2]
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-12 else 1.0

    # Сохраняем историю для Rollback
    prev_ver = int(db.get("version", 1))
    new_ver = prev_ver + 1
    history_entry = {
        "version": prev_ver,
        "saved_at": db.get("updated_at"),
        "weight_key": weight_key,
        "previous_entry": copy.deepcopy(db["weights"].get(weight_key)),
    }
    db.setdefault("history", []).append(history_entry)
    db["version"] = new_ver
    db["updated_at"] = datetime.now(timezone.utc).isoformat()
    db["weights"][weight_key] = {
        "alpha_0": round(alpha_0, 6),
        "x1": round(x1, 4),
        "x2": round(x2, 4),
        "x3": round(x3, 4),
        "samples_count": len(samples),
    }

    save_regression_weights(db, target_path)
    return CalibrationReport(
        weight_key=weight_key,
        samples_used=len(samples),
        method_used=method,
        alpha_0=round(alpha_0, 6),
        x1=round(x1, 4),
        x2=round(x2, 4),
        x3=round(x3, 4),
        r2_log_score=round(r2, 4),
        previous_version=prev_ver,
        new_version=new_ver,
    )


def rollback_weights(weights_path: Optional[Path] = None) -> int:
    """Откатывает последнее обновление весов из history."""
    target_path = weights_path or (DATABASE_DIR / "regression_weights.json")
    db = copy.deepcopy(load_regression_weights(target_path))
    history = db.get("history") or []
    if not history:
        raise RuntimeError("История калибровки пуста — откат невозможен.")

    last = history.pop()
    key = last["weight_key"]
    prev_entry = last.get("previous_entry")
    if prev_entry is None:
        db["weights"].pop(key, None)
    else:
        db["weights"][key] = prev_entry
    db["version"] = int(last["version"])
    db["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_regression_weights(db, target_path)
    logger.info("Выполнен откат весов '%s' к версии v%s", key, db["version"])
    return int(db["version"])


__all__ = ["CalibrationReport", "fit_constrained_ridge", "rollback_weights"]

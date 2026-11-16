"""Гибридный оркестратор расчета трудоемкости (Контур 1 ЦБНТ + Контур 2 MRR/Регрессия)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from ingro_dfm.calc_engine.auxiliary_time_calc import (
    calc_k_tsht,
    calc_measurement_time,
    calc_t_pz_setup,
    calc_t_vp_setup,
    calc_t_vu_setup,
)
from ingro_dfm.calc_engine.cbnt_auto_filter import CBNTElementTrace, estimate_element_cbnt
from ingro_dfm.calc_engine.regression_estimator import RegressionElementTrace, estimate_element_regression
from ingro_dfm.classifier.setup_clusterer import SetupCluster, cluster_setups
from ingro_dfm.classifier.tech_coder_10 import classify_passport
from ingro_dfm.core_schema.part_passport import GeometryType, PartPassport

logger = logging.getLogger(__name__)


class ElementCalculationDetail(BaseModel):
    element_id: str
    name: str
    geometry_type: str
    tech_code_10: str
    setup_id: int
    setup_direction: str
    operation_kind: str
    assigned_transitions: List[str]
    roughness_ra_um: float
    it_grade: int
    pmi_source: str
    # Контур 1 (ЦБНТ / ОУНВ)
    cbnt_cards: List[str]
    cbnt_t_osn_min: float
    # Контур 2 (MRR + Степенная регрессия)
    reg_weight_key: str
    reg_t_rough_mrr_min: float
    reg_t_finish_min: float
    reg_t_osn_min: float
    # Гибрид и промеры
    hybrid_t_osn_min: float
    hybrid_source_used: str
    t_vp_measure_min: float


class OperationSummary(BaseModel):
    setup_id: int
    operation_name: str
    operation_kind: str
    setup_direction: str
    clamping_type: str
    machine_type: str
    tools_count: int
    elements_count: int
    t_osn_cbnt_min: float
    t_osn_reg_min: float
    t_osn_hybrid_min: float
    t_vu_min: float
    t_vp_min: float
    t_op_min: float
    k_tsht: float
    t_sht_min: float
    t_pz_min: float
    t_shk_min: float
    t_norm_hours: float


class ContourTotals(BaseModel):
    contour_name: str
    t_osn_total_min: float
    t_vu_total_min: float
    t_vp_total_min: float
    t_op_total_min: float
    t_sht_total_min: float
    t_pz_total_min: float
    t_shk_total_min: float
    t_norm_hours: float


class HybridCalculationResult(BaseModel):
    part_id: str
    part_name: str
    batch_size_q: int
    kim_ratio: float
    setups_count: int
    operations: List[OperationSummary]
    elements: List[ElementCalculationDetail]
    cbnt_totals: ContourTotals
    regression_totals: ContourTotals
    hybrid_totals: ContourTotals
    contours_diff_percent: float


def _operation_title(op_kind: str, setup_dir: str) -> str:
    titles = {
        "turning": f"Токарная (установ {setup_dir})",
        "milling": f"Фрезерная (установ {setup_dir})",
        "drilling": f"Сверлильно-расточная (установ {setup_dir})",
        "grinding": f"Шлифовальная (установ {setup_dir})",
    }
    return titles.get(op_dir := op_kind, f"Механическая ({op_dir}, {setup_dir})")


def _build_contour_totals(
    name: str,
    op_rows: List[tuple[float, float, float, float, float]],  # (t_osn, t_vu, t_vp, t_pz, k_tsht)
    batch_q: int,
) -> ContourTotals:
    t_osn_sum = sum(r[0] for r in op_rows)
    t_vu_sum = sum(r[1] for r in op_rows)
    t_vp_sum = sum(r[2] for r in op_rows)
    t_op_sum = t_osn_sum + t_vu_sum + t_vp_sum
    t_sht_sum = sum((r[0] + r[1] + r[2]) * r[4] for r in op_rows)
    t_pz_sum = sum(r[3] for r in op_rows)
    t_shk_sum = t_sht_sum + t_pz_sum / max(1, batch_q)
    return ContourTotals(
        contour_name=name,
        t_osn_total_min=round(t_osn_sum, 2),
        t_vu_total_min=round(t_vu_sum, 2),
        t_vp_total_min=round(t_vp_sum, 2),
        t_op_total_min=round(t_op_sum, 2),
        t_sht_total_min=round(t_sht_sum, 2),
        t_pz_total_min=round(t_pz_sum, 2),
        t_shk_total_min=round(t_shk_sum, 2),
        t_norm_hours=round(t_shk_sum / 60.0, 4),
    )


def calculate_passport(
    passport: PartPassport,
    use_cnc: bool = False,
    primary_mode: Literal["hybrid", "cbnt", "regression"] = "hybrid",
    weights_path: Optional[Path] = None,
) -> HybridCalculationResult:
    """Полный двухконтурный расчет трудоемкости детали по PartPassport v2.0."""
    classified = passport.model_copy(deep=True)
    classify_passport(classified)
    setups: List[SetupCluster] = cluster_setups(classified, use_cnc=use_cnc)

    element_details: List[ElementCalculationDetail] = []
    operations: List[OperationSummary] = []

    cbnt_rows: List[tuple[float, float, float, float, float]] = []
    reg_rows: List[tuple[float, float, float, float, float]] = []
    hyb_rows: List[tuple[float, float, float, float, float]] = []

    for setup in setups:
        t_vu = calc_t_vu_setup(classified, setup)
        t_vp, n_tools = calc_t_vp_setup(setup)
        t_pz = calc_t_pz_setup(setup, n_tools, use_cnc=use_cnc)

        op_cbnt = 0.0
        op_reg = 0.0
        op_hyb = 0.0

        for elem in setup.elements:
            c_trace: CBNTElementTrace = estimate_element_cbnt(classified, elem, operation_kind=setup.operation_kind)
            r_trace: RegressionElementTrace = estimate_element_regression(
                classified, elem, operation_kind=setup.operation_kind, weights_path=weights_path
            )

            # Гибридный выбор для элемента:
            # для свободных 3D/BSpline поверхностей или явных объемных карманов без точной карты - усиленный вес регрессии;
            # для типовых КТЭ с табличной картой ЦБНТ/ОУНВ - взвешенная связка (0.75 * ЦБНТ + 0.25 * Регрессия) или выбор режима
            if primary_mode == "cbnt":
                t_hyb = c_trace.total_card_time_min
                hyb_src = c_trace.source_norm
            elif primary_mode == "regression":
                t_hyb = r_trace.total_osn_min
                hyb_src = f"MRR+Reg({r_trace.weight_key_used})"
            else:
                if elem.geometry_type == GeometryType.SPHERE or not c_trace.card_ids:
                    t_hyb = r_trace.total_osn_min
                    hyb_src = f"MRR+Reg({r_trace.weight_key_used})"
                else:
                    # В гибриде нормативный якорь ЦБНТ доминирует, а MRR учитывает фактическую геометрическую сложность
                    t_hyb = 0.70 * c_trace.total_card_time_min + 0.30 * r_trace.total_osn_min
                    hyb_src = f"Hybrid({', '.join(c_trace.card_ids[:2])} + MRR)"

            op_cbnt += c_trace.total_card_time_min
            op_reg += r_trace.total_osn_min
            op_hyb += t_hyb

            element_details.append(
                ElementCalculationDetail(
                    element_id=elem.element_id,
                    name=elem.name,
                    geometry_type=elem.geometry_type.value,
                    tech_code_10=elem.classification.tech_code_10 or "",
                    setup_id=setup.setup_id,
                    setup_direction=setup.setup_direction,
                    operation_kind=setup.operation_kind,
                    assigned_transitions=list(elem.classification.assigned_transitions),
                    roughness_ra_um=elem.pmi.roughness_ra_um,
                    it_grade=elem.pmi.it_grade,
                    pmi_source=elem.pmi.source.value,
                    cbnt_cards=c_trace.card_ids,
                    cbnt_t_osn_min=round(c_trace.total_card_time_min, 3),
                    reg_weight_key=r_trace.weight_key_used,
                    reg_t_rough_mrr_min=round(r_trace.t_rough_mrr_min, 3),
                    reg_t_finish_min=round(r_trace.t_finish_reg_min, 3),
                    reg_t_osn_min=round(r_trace.total_osn_min, 3),
                    hybrid_t_osn_min=round(t_hyb, 3),
                    hybrid_source_used=hyb_src,
                    t_vp_measure_min=round(calc_measurement_time(elem), 3),
                )
            )

        t_op_hyb = op_hyb + t_vu + t_vp
        k_tsht_hyb = calc_k_tsht(classified.batch_size_q, classified.production_type, t_op_hyb)
        k_tsht_cbnt = calc_k_tsht(classified.batch_size_q, classified.production_type, op_cbnt + t_vu + t_vp)
        k_tsht_reg = calc_k_tsht(classified.batch_size_q, classified.production_type, op_reg + t_vu + t_vp)

        t_sht = t_op_hyb * k_tsht_hyb
        t_shk = t_sht + t_pz / classified.batch_size_q

        operations.append(
            OperationSummary(
                setup_id=setup.setup_id,
                operation_name=_operation_title(setup.operation_kind, setup.setup_direction),
                operation_kind=setup.operation_kind,
                setup_direction=setup.setup_direction,
                clamping_type=setup.clamping_type,
                machine_type=setup.machine_type,
                tools_count=n_tools,
                elements_count=len(setup.elements),
                t_osn_cbnt_min=round(op_cbnt, 2),
                t_osn_reg_min=round(op_reg, 2),
                t_osn_hybrid_min=round(op_hyb, 2),
                t_vu_min=round(t_vu, 2),
                t_vp_min=round(t_vp, 2),
                t_op_min=round(t_op_hyb, 2),
                k_tsht=round(k_tsht_hyb, 4),
                t_sht_min=round(t_sht, 2),
                t_pz_min=round(t_pz, 2),
                t_shk_min=round(t_shk, 2),
                t_norm_hours=round(t_shk / 60.0, 4),
            )
        )

        cbnt_rows.append((op_cbnt, t_vu, t_vp, t_pz, k_tsht_cbnt))
        reg_rows.append((op_reg, t_vu, t_vp, t_pz, k_tsht_reg))
        hyb_rows.append((op_hyb, t_vu, t_vp, t_pz, k_tsht_hyb))

    cbnt_tot = _build_contour_totals("Контур 1 (ЦБНТ / ОУНВ)", cbnt_rows, classified.batch_size_q)
    reg_tot = _build_contour_totals("Контур 2 (MRR + Регрессия)", reg_rows, classified.batch_size_q)
    hyb_tot = _build_contour_totals(f"Итоговый ({primary_mode})", hyb_rows, classified.batch_size_q)

    denom = max(cbnt_tot.t_shk_total_min, 1e-6)
    diff_pct = abs(cbnt_tot.t_shk_total_min - reg_tot.t_shk_total_min) / denom * 100.0
    kim = classified.part_mass_kg / max(classified.blank_mass_kg, 1e-6)

    return HybridCalculationResult(
        part_id=classified.part_id,
        part_name=classified.part_name,
        batch_size_q=classified.batch_size_q,
        kim_ratio=round(kim, 4),
        setups_count=len(setups),
        operations=operations,
        elements=element_details,
        cbnt_totals=cbnt_tot,
        regression_totals=reg_tot,
        hybrid_totals=hyb_tot,
        contours_diff_percent=round(diff_pct, 2),
    )


__all__ = [
    "ElementCalculationDetail",
    "OperationSummary",
    "ContourTotals",
    "HybridCalculationResult",
    "calculate_passport",
]

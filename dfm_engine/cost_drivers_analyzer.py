"""Анализатор главных драйверов трудоемкости (Cost Drivers)."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel

from ingro_dfm.calc_engine.hybrid_orchestrator import HybridCalculationResult


class CostDriverItem(BaseModel):
    rank: int
    element_id: str
    name: str
    tech_code_10: str
    roughness_ra_um: float
    it_grade: int
    t_osn_hybrid_min: float
    t_finish_reg_min: float
    t_vp_measure_min: float
    total_element_min: float
    share_of_t_op_percent: float
    is_major_driver: bool


def analyze_cost_drivers(calc_result: HybridCalculationResult, top_n: int = 10) -> List[CostDriverItem]:
    """Ранжирует элементы детали по их вкладу в суммарное оперативное время."""
    t_op_ref = max(calc_result.hybrid_totals.t_op_total_min, 1e-6)
    scored = []
    for elem in calc_result.elements:
        total_e = elem.hybrid_t_osn_min + elem.t_vp_measure_min
        scored.append((total_e, elem))

    scored.sort(key=lambda item: item[0], reverse=True)
    drivers: List[CostDriverItem] = []
    for idx, (total_e, elem) in enumerate(scored[:top_n], start=1):
        share = total_e / t_op_ref * 100.0
        is_major = share >= 20.0 or elem.it_grade <= 8 or elem.roughness_ra_um <= 1.6
        drivers.append(
            CostDriverItem(
                rank=idx,
                element_id=elem.element_id,
                name=elem.name,
                tech_code_10=elem.tech_code_10,
                roughness_ra_um=elem.roughness_ra_um,
                it_grade=elem.it_grade,
                t_osn_hybrid_min=round(elem.hybrid_t_osn_min, 3),
                t_finish_reg_min=round(elem.reg_t_finish_min, 3),
                t_vp_measure_min=round(elem.t_vp_measure_min, 3),
                total_element_min=round(total_e, 3),
                share_of_t_op_percent=round(share, 2),
                is_major_driver=is_major,
            )
        )
    return drivers


__all__ = ["CostDriverItem", "analyze_cost_drivers"]

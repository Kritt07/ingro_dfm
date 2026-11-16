"""Интерактивный What-If симулятор пересчета трудоемкости при изменении Ra и IT (§6.2 ТЗ)."""

from __future__ import annotations

from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel

from ingro_dfm.calc_engine.hybrid_orchestrator import calculate_passport
from ingro_dfm.core_schema.part_passport import PMISource, PartPassport


class WhatIfResult(BaseModel):
    element_id: str
    old_ra_um: float
    old_it_grade: int
    new_ra_um: float
    new_it_grade: int
    old_tech_code_10: str
    new_tech_code_10: str
    old_t_shk_min: float
    new_t_shk_min: float
    delta_min: float
    delta_percent: float
    removed_transitions: List[str]
    added_transitions: List[str]


def simulate_parameter_change(
    passport: PartPassport,
    element_id: str,
    new_ra: float,
    new_it: int,
    use_cnc: bool = False,
    primary_mode: Literal["hybrid", "cbnt", "regression"] = "hybrid",
    weights_path: Optional[Path] = None,
) -> WhatIfResult:
    """Мгновенно перекодирует tech_code_10 элемента и оценивает изменение T_шк."""
    old_res = calculate_passport(passport, use_cnc=use_cnc, primary_mode=primary_mode, weights_path=weights_path)
    old_elem = next((e for e in old_res.elements if e.element_id == element_id), None)
    if old_elem is None:
        raise KeyError(f"Элемент '{element_id}' не найден в паспорте детали '{passport.part_name}'.")

    modified = passport.model_copy(deep=True)
    target = next(e for e in modified.elements if e.element_id == element_id)
    old_ra = target.pmi.roughness_ra_um
    old_it = target.pmi.it_grade

    target.pmi.roughness_ra_um = float(new_ra)
    target.pmi.it_grade = int(new_it)
    target.pmi.source = PMISource.USER_OVERRIDE

    new_res = calculate_passport(modified, use_cnc=use_cnc, primary_mode=primary_mode, weights_path=weights_path)
    new_elem = next(e for e in new_res.elements if e.element_id == element_id)

    old_t = old_res.hybrid_totals.t_shk_total_min
    new_t = new_res.hybrid_totals.t_shk_total_min
    delta = round(new_t - old_t, 2)
    delta_pct = round((delta / max(old_t, 1e-6)) * 100.0, 2)

    removed = [tr for tr in old_elem.assigned_transitions if tr not in new_elem.assigned_transitions]
    added = [tr for tr in new_elem.assigned_transitions if tr not in old_elem.assigned_transitions]

    return WhatIfResult(
        element_id=element_id,
        old_ra_um=old_ra,
        old_it_grade=old_it,
        new_ra_um=float(new_ra),
        new_it_grade=int(new_it),
        old_tech_code_10=old_elem.tech_code_10,
        new_tech_code_10=new_elem.tech_code_10,
        old_t_shk_min=old_t,
        new_t_shk_min=new_t,
        delta_min=delta,
        delta_percent=delta_pct,
        removed_transitions=removed,
        added_transitions=added,
    )


__all__ = ["WhatIfResult", "simulate_parameter_change"]

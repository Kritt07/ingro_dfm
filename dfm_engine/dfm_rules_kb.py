"""База знаний DFM-правил и система оценки 'Светофор' (§6.1, §8 ТЗ)."""

from __future__ import annotations

import logging
from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel

from ingro_dfm.calc_engine.hybrid_orchestrator import HybridCalculationResult
from ingro_dfm.classifier.tech_coder_10 import classify_passport, encode_l8_it_bucket, encode_l9_ra_bucket
from ingro_dfm.core_schema.part_passport import (
    FeatureOrFaceItem,
    GeometryType,
    PMISource,
    PartPassport,
)

logger = logging.getLogger(__name__)


class DFMFinding(BaseModel):
    rule_id: str
    severity: Literal["critical", "warning", "info"]
    element_id: Optional[str] = None
    title: str
    message: str
    recommendation: str
    estimated_impact_min: float = 0.0


class ElementTrafficLight(BaseModel):
    element_id: str
    color: Literal["green", "yellow", "red"]
    reasons: List[str]


class DFMAssessment(BaseModel):
    kim_ratio: float
    is_manufacturable: bool
    findings: List[DFMFinding]
    traffic_lights: Dict[str, ElementTrafficLight]
    total_potential_savings_min: float


def _find_close_clusters(values: List[Tuple[str, float]], min_diff: float, max_diff: float) -> List[List[Tuple[str, float]]]:
    """Находит группы близких, но различающихся размеров (в заданном диапазоне разницы)."""
    if len(values) < 2:
        return []
    ordered = sorted(values, key=lambda pair: pair[1])
    clusters: List[List[Tuple[str, float]]] = []
    cur = [ordered[0]]
    for item in ordered[1:]:
        if item[1] - cur[-1][1] <= max_diff + 1e-9:
            cur.append(item)
        else:
            distinct = {round(x[1], 3) for x in cur}
            if len(distinct) >= 2 and (max(distinct) - min(distinct)) >= min_diff:
                clusters.append(cur)
            cur = [item]
    distinct = {round(x[1], 3) for x in cur}
    if len(distinct) >= 2 and (max(distinct) - min(distinct)) >= min_diff:
        clusters.append(cur)
    return clusters


def evaluate_dfm(
    passport: PartPassport,
    calc_result: Optional[HybridCalculationResult] = None,
) -> DFMAssessment:
    """Проводит полный DFM-анализ детали и формирует индикацию 'Светофор'."""
    classified = passport.model_copy(deep=True)
    classify_passport(classified)

    findings: List[DFMFinding] = []
    element_issues: Dict[str, List[Tuple[str, str]]] = {e.element_id: [] for e in classified.elements}

    # 1. КИМ < 0.35
    kim = classified.part_mass_kg / max(classified.blank_mass_kg, 1e-6)
    if kim < 0.35:
        waste_pct = (1.0 - kim) * 100.0
        findings.append(
            DFMFinding(
                rule_id="DFM_01_LOW_KIM",
                severity="warning",
                title="Низкий коэффициент использования материала (КИМ)",
                message=f"Низкий КИМ = {kim:.3f} (< 0.35): в стружку уходит {waste_pct:.1f}% металла.",
                recommendation="Рекомендуется рассмотреть замену проката на литую/штампованную заготовку или сварную конструкцию.",
                estimated_impact_min=round(classified.total_removed_volume_mm3 / 40000.0 * 0.35, 2),
            )
        )

    # Распределение времени по элементам (если передан calc_result)
    elem_time_map: Dict[str, float] = {}
    if calc_result is not None:
        for det in calc_result.elements:
            elem_time_map[det.element_id] = det.hybrid_t_osn_min + det.t_vp_measure_min

    # 2. Глубокие и глухие отверстия + 3. Карманы и пазы + 4. Избыточная точность
    hole_diams: List[Tuple[str, float]] = []
    fillet_radii: List[Tuple[str, float]] = []
    grinding_candidates: List[FeatureOrFaceItem] = []

    for elem in classified.elements:
        d = elem.dimensions.diameter_mm
        l_val = elem.dimensions.length_or_depth_mm
        g = elem.geometry_type

        # Правило 2: Отверстия
        if g == GeometryType.CYLINDER_INT_HOLE and d and l_val:
            hole_diams.append((elem.element_id, float(d)))
            ld = l_val / max(d, 1e-6)
            if ld > 5.0:
                msg = f"Глубокое отверстие {elem.element_id} (L/D = {ld:.2f} > 5): требуется цикл глубокого сверления с выводом стружки (+30..50%)."
                findings.append(
                    DFMFinding(
                        rule_id="DFM_02_DEEP_HOLE",
                        severity="warning",
                        element_id=elem.element_id,
                        title="Глубокое отверстие (L/D > 5)",
                        message=msg,
                        recommendation="Уменьшить глубину либо увеличить диаметр; заложить цикл с периодическим выводом сверла.",
                        estimated_impact_min=round(elem_time_map.get(elem.element_id, 2.0) * 0.30, 2),
                    )
                )
                element_issues[elem.element_id].append(("warning", msg))
            if elem.dimensions.is_blind:
                msg = f"Глухое отверстие {elem.element_id}: при наличии плоского дна требуется трудоемкая зачистка концевой фрезой."
                findings.append(
                    DFMFinding(
                        rule_id="DFM_02_BLIND_HOLE_FLAT",
                        severity="info",
                        element_id=elem.element_id,
                        title="Глухое отверстие: профиль дна",
                        message=msg,
                        recommendation="Заменить плоское дно на коническое 118°–120° из-под стандартного спирального сверла.",
                        estimated_impact_min=0.4,
                    )
                )

        # Правило 3: Карманы и пазы — H_карм / R_угл > 6 или R_угл == 0
        if g in (GeometryType.POCKET, GeometryType.SLOT) and l_val:
            r_cor = elem.dimensions.corner_radius_mm
            if r_cor is not None:
                if r_cor <= 0.05:
                    msg = f"Нетехнологичный острый внутренний угол в {elem.element_id} (R_угл = 0 мм): невозможно обработать фрезой без доп. ЭЭО/долбления."
                    findings.append(
                        DFMFinding(
                            rule_id="DFM_03_SHARP_POCKET_CORNER",
                            severity="critical",
                            element_id=elem.element_id,
                            title="Острый внутренний угол кармана/паза",
                            message=msg,
                            recommendation=f"Задать внутренний радиус скругления R >= {max(2.0, round(l_val / 6.0, 1))} мм.",
                            estimated_impact_min=round(max(3.5, elem_time_map.get(elem.element_id, 4.0) * 0.45), 2),
                        )
                    )
                    element_issues[elem.element_id].append(("critical", msg))
                elif (l_val / r_cor) > 6.0:
                    ratio = l_val / r_cor
                    msg = f"Нетехнологичный внутренний угол {elem.element_id}: H/R_угл = {ratio:.1f} > 6 (H={l_val:.1f} мм, R={r_cor:.1f} мм)."
                    findings.append(
                        DFMFinding(
                            rule_id="DFM_03_POCKET_H_R_RATIO",
                            severity="critical",
                            element_id=elem.element_id,
                            title="Малый угловой радиус глубокого кармана/паза (H/R > 6)",
                            message=msg,
                            recommendation=f"Увеличить радиус угла с {r_cor:.1f} мм до >= {round(l_val / 5.0, 1)} мм под жесткую фрезу.",
                            estimated_impact_min=round(max(2.5, elem_time_map.get(elem.element_id, 3.0) * 0.35), 2),
                        )
                    )
                    element_issues[elem.element_id].append(("critical", msg))

        # Сбор радиусов для правила унификации
        if g in (GeometryType.GROOVE, GeometryType.POCKET) and (elem.dimensions.corner_radius_mm or elem.dimensions.radius_mm):
            r_u = float(elem.dimensions.corner_radius_mm or elem.dimensions.radius_mm)
            if r_u > 0:
                fillet_radii.append((elem.element_id, r_u))

        # Правило 4: Избыточная точность / шероховатость (IT <= 8 или Ra <= 1.6)
        it_b = encode_l8_it_bucket(elem.pmi.it_grade)
        ra_b = encode_l9_ra_bucket(elem.pmi.roughness_ra_um)
        if it_b in ("IT_B4", "IT_B5") or ra_b in ("RA_B4", "RA_B5", "RA_B6"):
            impact = round(elem_time_map.get(elem.element_id, 2.5) * 0.40, 2)
            msg = f"Высокие требования к {elem.element_id}: IT{elem.pmi.it_grade}, Ra {elem.pmi.roughness_ra_um} мкм (драйвер трудоемкости)."
            findings.append(
                DFMFinding(
                    rule_id="DFM_04_HIGH_PRECISION_DRIVER",
                    severity="warning" if elem.pmi.source != PMISource.EXPLICIT_PMI else "info",
                    element_id=elem.element_id,
                    title="Высокая точность / чистота (Cost Driver)",
                    message=msg,
                    recommendation="Проверить обоснованность IT <= 8 / Ra <= 1.6; при несопрягаемой грани ослабить до Ra 3.2 / IT11.",
                    estimated_impact_min=impact,
                )
            )
            if elem.pmi.roughness_ra_um <= 0.8 or elem.pmi.it_grade <= 6:
                grinding_candidates.append(elem)

    # Одиночная шлифуемая шейка
    if len(grinding_candidates) == 1:
        sole = grinding_candidates[0]
        msg = f"Одиночная шлифуемая поверхность {sole.element_id} (Ra {sole.pmi.roughness_ra_um} / IT{sole.pmi.it_grade}) порождает отдельную операцию шлифования и T_пз."
        findings.append(
            DFMFinding(
                rule_id="DFM_04_SINGLE_GRIND",
                severity="warning",
                element_id=sole.element_id,
                title="Одиночная шлифуемая поверхность",
                message=msg,
                recommendation="Ослабить до Ra 1.6 / IT8 (тонкое точение/фрезерование) или сгруппировать с другой шлифуемой базой.",
                estimated_impact_min=round(17.0 / max(1, classified.batch_size_q) + 1.5, 2),
            )
        )
        element_issues[sole.element_id].append(("warning", msg))

    # Правило 5: Унификация диаметров отверстий и радиусов
    for cluster in _find_close_clusters(hole_diams, min_diff=0.2, max_diff=1.5):
        desc = ", ".join(f"{eid}:Ø{val:.1f}" for eid, val in cluster)
        findings.append(
            DFMFinding(
                rule_id="DFM_05_UNIFY_HOLES",
                severity="warning",
                element_id=cluster[0][0],
                title="Разнородные близкие диаметры отверстий",
                message=f"Обнаружены близкие диаметры отверстий ({desc}) — требуются разные сверла и лишние смены инструмента.",
                recommendation="Унифицировать номиналы отверстий под единый диаметр для снижения N_инстр и T_пз.",
                estimated_impact_min=round(0.45 * (len({round(v, 2) for _, v in cluster}) - 1), 2),
            )
        )
        for eid, _ in cluster:
            element_issues[eid].append(("warning", f"Близкие не унифицированные диаметры ({desc})"))

    for cluster in _find_close_clusters(fillet_radii, min_diff=0.2, max_diff=1.5):
        desc = ", ".join(f"{eid}:R{val:.1f}" for eid, val in cluster)
        findings.append(
            DFMFinding(
                rule_id="DFM_05_UNIFY_RADII",
                severity="warning",
                element_id=cluster[0][0],
                title="Разные радиусы скруглений / галтелей",
                message=f"Близкие радиусы скруглений ({desc}) увеличивают число инструментов в наладке.",
                recommendation="Унифицировать радиусы под одну фрезу / фасочный резец.",
                estimated_impact_min=0.4,
            )
        )

    # Построение светофора по элементам (§8.1)
    traffic_lights: Dict[str, ElementTrafficLight] = {}
    for elem in classified.elements:
        issues = element_issues.get(elem.element_id, [])
        reasons: List[str] = [msg for _, msg in issues]
        has_critical = any(sev == "critical" for sev, _ in issues)
        has_warning = any(sev == "warning" for sev, _ in issues)
        missing_pmi = elem.pmi.source in (PMISource.SYSTEM_DEFAULT, PMISource.INHERITED_TT)

        if has_critical or not elem.classification.tech_code_10:
            color: Literal["green", "yellow", "red"] = "red"
            if not elem.classification.tech_code_10:
                reasons.append("Неклассифицированный участок")
        elif missing_pmi or has_warning:
            color = "yellow"
            if missing_pmi:
                reasons.append(f"Нет явного PMI ({elem.pmi.source.value}: Ra {elem.pmi.roughness_ra_um}, IT{elem.pmi.it_grade})")
        else:
            color = "green"
            reasons.append("Явный PMI и геометрия распознаны; критических замечаний нет")

        traffic_lights[elem.element_id] = ElementTrafficLight(
            element_id=elem.element_id,
            color=color,
            reasons=reasons,
        )

    is_manuf = not any(f.severity == "critical" for f in findings)
    total_save = round(sum(f.estimated_impact_min for f in findings), 2)

    return DFMAssessment(
        kim_ratio=round(kim, 4),
        is_manufacturable=is_manuf,
        findings=findings,
        traffic_lights=traffic_lights,
        total_potential_savings_min=total_save,
    )


__all__ = ["DFMFinding", "ElementTrafficLight", "DFMAssessment", "evaluate_dfm"]

"""10-уровневый классификатор и генератор технологического кода (подход ТулГУ)."""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Union

from ingro_dfm.core_schema.part_passport import (
    BlankType,
    FeatureOrFaceItem,
    GeometryType,
    MachinabilityGroup,
    MaterialGroup,
    PartPassport,
)
from ingro_dfm.core_schema.pmi_utils import extract_hb_numeric
from ingro_dfm.database.loader import load_transitions_rules

logger = logging.getLogger(__name__)

_L2_MAP: Dict[MaterialGroup, str] = {
    MaterialGroup.CARBON_STEEL: "ST_C",
    MaterialGroup.ALLOY_STEEL: "ST_A",
    MaterialGroup.STAINLESS_STEEL: "ST_S",
    MaterialGroup.CAST_IRON_GRAY: "CI_G",
    MaterialGroup.CAST_IRON_DUCTILE: "CI_D",
    MaterialGroup.ALUMINUM_ALLOY: "AL",
    MaterialGroup.COPPER_ALLOY: "CU",
    MaterialGroup.TITANIUM_ALLOY: "TI",
}

_L3_MAP: Dict[MachinabilityGroup, str] = {
    MachinabilityGroup.GOOD: "G1",
    MachinabilityGroup.SATISFACTORY: "G2",
    MachinabilityGroup.POOR: "G3",
}

_L4_MAP: Dict[BlankType, str] = {
    BlankType.ROLLED_BAR: "PR",
    BlankType.ROLLED_PLATE: "PR",
    BlankType.TUBE: "PR",
    BlankType.CASTING: "LT",
    BlankType.STAMPING_FORGING: "SH",
}


def encode_l1_mass(part_mass_kg: float) -> str:
    if part_mass_kg <= 1.0:
        return "M1"
    if part_mass_kg <= 10.0:
        return "M2"
    if part_mass_kg <= 30.0:
        return "M3"
    return "M4"


def encode_l5_heat_treatment(passport: PartPassport) -> str:
    if not passport.has_heat_treatment and not passport.has_coating:
        return "HT0"
    hb_equiv = extract_hb_numeric(passport.hardness_hb_or_hrc)
    hrc_str = (passport.hardness_hb_or_hrc or "").lower()
    m_hrc = re.search(r"(\d{2})\s*hrc", hrc_str)
    if m_hrc and int(m_hrc.group(1)) > 45:
        return "HT2"
    if hb_equiv is not None and hb_equiv > 420.0:
        return "HT2"
    return "HT1"


def encode_l8_it_bucket(it_grade: int) -> str:
    if it_grade >= 14:
        return "IT_B1"
    if it_grade >= 12:
        return "IT_B2"
    if it_grade >= 9:
        return "IT_B3"
    if it_grade >= 5:
        return "IT_B4"
    return "IT_B5"


def encode_l9_ra_bucket(ra_um: float) -> str:
    if ra_um > 80.0:
        return "RA_B1"
    if ra_um > 10.0:
        return "RA_B2"
    if ra_um > 2.5:
        return "RA_B3"
    if ra_um > 0.32:
        return "RA_B4"
    if ra_um > 0.02:
        return "RA_B5"
    return "RA_B6"


def lookup_transitions(
    geom: GeometryType,
    it_bucket: str,
    ra_bucket: str,
    element: Optional[FeatureOrFaceItem] = None,
    l5_code: str = "HT0",
) -> List[str]:
    """Подбирает список технологических переходов из transitions_rules.json."""
    rules_all = load_transitions_rules()["rules"]
    g_rules = rules_all.get(geom.value, {})

    transitions: Optional[List[str]] = None
    if it_bucket in g_rules and isinstance(g_rules[it_bucket], dict):
        it_dict = g_rules[it_bucket]
        if ra_bucket in it_dict:
            transitions = list(it_dict[ra_bucket])
        else:
            # Ближайший доступный RA_B* уровень в данном квалитете
            for key in ("RA_B4", "RA_B3", "RA_B5", "RA_B2", "RA_B1", "RA_B6"):
                if key in it_dict:
                    transitions = list(it_dict[key])
                    break
    if transitions is None and "DEFAULT" in g_rules:
        transitions = list(g_rules["DEFAULT"])

    if not transitions:
        # Синтетический фоллбэк по L8 + L9
        if geom == GeometryType.CYLINDER_INT_HOLE:
            transitions = ["Сверление"]
            if it_bucket in ("IT_B3", "IT_B4", "IT_B5"):
                transitions.append("Зенкерование")
            if it_bucket in ("IT_B4", "IT_B5") or ra_bucket in ("RA_B4", "RA_B5"):
                transitions.append("Развертывание")
        elif geom in (GeometryType.PLANE, GeometryType.SLOT, GeometryType.POCKET, GeometryType.STEP):
            transitions = ["Фрезерование черновое"]
            if it_bucket in ("IT_B3", "IT_B4", "IT_B5") or ra_bucket in ("RA_B4", "RA_B5", "RA_B6"):
                transitions.append("Фрезерование чистовое")
        else:
            transitions = ["Черновая обработка"]
            if it_bucket in ("IT_B3", "IT_B4", "IT_B5") or ra_bucket in ("RA_B4", "RA_B5", "RA_B6"):
                transitions.append("Чистовая обработка")

    # Специальное правило для отверстий: L > 3D добавляет "Центрование" перед сверлением
    if geom == GeometryType.CYLINDER_INT_HOLE and element is not None:
        d = element.dimensions.diameter_mm or 10.0
        l_val = element.dimensions.length_or_depth_mm or 10.0
        if l_val > 3.0 * d and "Центрование" not in transitions:
            transitions = ["Центрование", *transitions]

    # Для закаленных деталей > 45 HRC и посадок: требуется шлифование
    if l5_code == "HT2" and geom in (GeometryType.CYLINDER_EXT, GeometryType.CYLINDER_INT_HOLE, GeometryType.PLANE):
        if it_bucket in ("IT_B3", "IT_B4", "IT_B5") and not any("шлиф" in t.lower() for t in transitions):
            if geom == GeometryType.CYLINDER_EXT:
                transitions.append("Круглое шлифование")
            elif geom == GeometryType.CYLINDER_INT_HOLE:
                transitions.append("Внутреннее шлифование")
            else:
                transitions.append("Плоское шлифование")

    return transitions


def build_cbnt_filters(passport: PartPassport, element: FeatureOrFaceItem) -> Dict[str, Union[float, str, int]]:
    """Формирует поисковый вектор ЦБНТ (раздел 5.1 ТЗ)."""
    d_cut = element.dimensions.diameter_mm or element.dimensions.width_mm or passport.bounding_box_mm.get("D_max", 40.0)
    l_cut = element.dimensions.length_or_depth_mm or passport.bounding_box_mm.get("L", 50.0)
    t_cut = element.dimensions.allowance_t_mm if element.dimensions.allowance_t_mm is not None else 2.0
    return {
        "filtr_Dcut": round(float(d_cut), 2),
        "filtr_Lcut": round(float(l_cut), 2),
        "filtr_tcut": round(float(t_cut), 2),
        "VRT_mass_dse": round(float(passport.part_mass_kg), 3),
        "VRT_DSE_Mat": passport.material_group.value,
    }


def classify_element(passport: PartPassport, element: FeatureOrFaceItem) -> FeatureOrFaceItem:
    """Присваивает одному элементу 10-уровневый код, переходы и поисковые фильтры ЦБНТ."""
    l1 = encode_l1_mass(passport.part_mass_kg)
    l2 = _L2_MAP[passport.material_group]
    l3 = _L3_MAP[passport.machinability_group]
    l4 = _L4_MAP[passport.blank_type]
    l5 = encode_l5_heat_treatment(passport)

    l6 = element.category.value
    l7 = element.geometry_type.value
    l8 = encode_l8_it_bucket(element.pmi.it_grade)
    l9 = encode_l9_ra_bucket(element.pmi.roughness_ra_um)
    l10 = element.pmi.geom_tolerance_type.value

    tech_code = f"{l1}.{l2}.{l3}.{l4}.{l5}-{l6}.{l7}.{l8}.{l9}.{l10}"
    transitions = lookup_transitions(element.geometry_type, l8, l9, element=element, l5_code=l5)
    filters = build_cbnt_filters(passport, element)

    element.classification.tech_code_10 = tech_code
    element.classification.assigned_transitions = transitions
    element.classification.cbnt_search_filters = filters
    return element


def classify_passport(passport: PartPassport) -> PartPassport:
    """Классифицирует все элементы паспорта детали."""
    for elem in passport.elements:
        classify_element(passport, elem)
    logger.debug("Классифицировано %d элементов детали %s", len(passport.elements), passport.part_name)
    return passport


__all__ = [
    "encode_l1_mass",
    "encode_l5_heat_treatment",
    "encode_l8_it_bucket",
    "encode_l9_ra_bucket",
    "lookup_transitions",
    "build_cbnt_filters",
    "classify_element",
    "classify_passport",
]

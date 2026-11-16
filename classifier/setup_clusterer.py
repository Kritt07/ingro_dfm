"""Кластеризация КТЭ по технологическим установам (N_уст) и способам закрепления."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from ingro_dfm.core_schema.part_passport import FeatureOrFaceItem, GeometryType, PartPassport
from ingro_dfm.classifier.tech_coder_10 import encode_l5_heat_treatment


@dataclass
class SetupCluster:
    setup_id: int
    operation_kind: str  # turning | milling | drilling | grinding
    setup_direction: str
    clamping_type: str   # chuck | centers | vise | table_clamps
    machine_type: str    # universal_lathe | cnc_lathe | milling_3axis | drilling | grinding
    elements: List[FeatureOrFaceItem] = field(default_factory=list)


def _needs_grinding(elem: FeatureOrFaceItem, passport: PartPassport) -> bool:
    if any("шлиф" in t.lower() or "хонинг" in t.lower() for t in elem.classification.assigned_transitions):
        return True
    if elem.geometry_type in (GeometryType.CYLINDER_EXT, GeometryType.CYLINDER_INT_HOLE, GeometryType.PLANE):
        if elem.pmi.roughness_ra_um <= 0.8 or elem.pmi.it_grade <= 6:
            return True
        if encode_l5_heat_treatment(passport) == "HT2" and elem.pmi.it_grade <= 9:
            return True
    return False


def cluster_setups(passport: PartPassport, use_cnc: bool = False) -> List[SetupCluster]:
    """Группирует КТЭ и грани паспорта в технологические установаы по нормалям/направлениям."""
    clusters: List[SetupCluster] = []
    setup_counter = 0

    def add_cluster(op_kind: str, direction: str, clamping: str, machine: str, elems: List[FeatureOrFaceItem]) -> None:
        nonlocal setup_counter
        if not elems:
            return
        setup_counter += 1
        clusters.append(
            SetupCluster(
                setup_id=setup_counter,
                operation_kind=op_kind,
                setup_direction=direction,
                clamping_type=clamping,
                machine_type=machine,
                elements=elems,
            )
        )

    if passport.is_rotational_part:
        l_tot = passport.bounding_box_mm.get("L", 100.0)
        d_max = max(passport.bounding_box_mm.get("D_max", 40.0), 1.0)
        clamping = "centers" if (l_tot / d_max) > 3.0 else "chuck"
        lathe_machine = "cnc_lathe" if use_cnc else "universal_lathe"

        turning_types = {
            GeometryType.CYLINDER_EXT,
            GeometryType.CONE,
            GeometryType.CHAMFER,
            GeometryType.GROOVE,
            GeometryType.THREAD,
            GeometryType.PLANE,
            GeometryType.SPHERE,
        }
        # Делим токарные элементы, фрезерные пазы/шлицы, осевые/радиальные отверстия и шлифование
        main_turning: List[FeatureOrFaceItem] = []
        reverse_turning: List[FeatureOrFaceItem] = []
        milling_elems: Dict[str, List[FeatureOrFaceItem]] = {}
        drilling_elems: Dict[str, List[FeatureOrFaceItem]] = {}
        grinding_elems: List[FeatureOrFaceItem] = []

        for elem in passport.elements:
            if elem.geometry_type in (GeometryType.SLOT, GeometryType.POCKET, GeometryType.STEP, GeometryType.SPLINE):
                milling_elems.setdefault(elem.setup_direction, []).append(elem)
            elif elem.geometry_type == GeometryType.CYLINDER_INT_HOLE:
                # Радиальные отверстия — сверлильно-фрезерная, осевые (+/-Z или основная ось) — в токарную или сверлильную
                if elem.setup_direction in ("+Z", "-Z"):
                    main_turning.append(elem)
                else:
                    drilling_elems.setdefault(elem.setup_direction, []).append(elem)
            elif elem.geometry_type in turning_types:
                if elem.geometry_type == GeometryType.PLANE and elem.setup_direction == "-Z":
                    reverse_turning.append(elem)
                else:
                    main_turning.append(elem)
            else:
                main_turning.append(elem)

            if _needs_grinding(elem, passport):
                grinding_elems.append(elem)

        add_cluster("turning", "+Z", clamping, lathe_machine, main_turning)
        if reverse_turning:
            add_cluster("turning", "-Z", clamping, lathe_machine, reverse_turning)
        for dir_key, elems in milling_elems.items():
            add_cluster("milling", dir_key, "vise" if passport.part_mass_kg <= 15.0 else "table_clamps", "milling_3axis", elems)
        for dir_key, elems in drilling_elems.items():
            add_cluster("drilling", dir_key, "vise", "drilling", elems)
        if grinding_elems:
            add_cluster("grinding", "+Z", "centers", "grinding", grinding_elems)
    else:
        # Корпусная / призматическая деталь: 1..6 установов по уникальным setup_direction
        by_dir_mill: Dict[str, List[FeatureOrFaceItem]] = {}
        grinding_by_dir: Dict[str, List[FeatureOrFaceItem]] = {}

        for elem in passport.elements:
            by_dir_mill.setdefault(elem.setup_direction, []).append(elem)
            if _needs_grinding(elem, passport):
                grinding_by_dir.setdefault(elem.setup_direction, []).append(elem)

        clamping = "vise" if passport.blank_mass_kg <= 20.0 else "table_clamps"
        for dir_key, elems in by_dir_mill.items():
            # Если в установе только отверстия — классифицируем как drilling, иначе milling
            only_holes = all(e.geometry_type == GeometryType.CYLINDER_INT_HOLE for e in elems)
            add_cluster(
                "drilling" if only_holes else "milling",
                dir_key,
                clamping,
                "drilling" if only_holes else "milling_3axis",
                elems,
            )
        for dir_key, elems in grinding_by_dir.items():
            add_cluster("grinding", dir_key, "table_clamps", "grinding", elems)

    return clusters


__all__ = ["SetupCluster", "cluster_setups"]

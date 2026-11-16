"""Базовый абстрактный CAD-адаптер: OBB, расчет заготовки, каскадный PMI и сборка PartPassport v2.0."""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ingro_dfm.classifier.aag_feature_recognizer import (
    AAGFeatureRecognizer,
    BRepEdgeLink,
    BRepFaceNode,
)
from ingro_dfm.classifier.tech_coder_10 import classify_passport
from ingro_dfm.core_schema.part_passport import (
    BlankType,
    CADSource,
    GeomToleranceType,
    PMISource,
    PMISpec,
    PartPassport,
    ProductionType,
    MachinabilityGroup,
    MaterialGroup,
)
from ingro_dfm.core_schema.pmi_utils import (
    map_fcf_symbol_to_enum,
    parse_roughness_text,
    parse_tech_requirements,
    parse_tolerance_text,
)
from ingro_dfm.database.loader import load_turning_db, resolve_material_info

logger = logging.getLogger(__name__)


@dataclass
class PMIFaceBinding:
    face_ids: List[int] = field(default_factory=list)
    roughness_text: Optional[str] = None
    tolerance_text: Optional[str] = None
    nominal_mm: Optional[float] = None
    fcf_symbol: Optional[str] = None
    fcf_value_mm: Optional[float] = None
    thread_pitch_mm: Optional[float] = None


@dataclass
class RawCADModelSnapshot:
    part_id: str
    part_name: str
    cad_source: CADSource
    material_raw: str = "Сталь 45 ГОСТ 1050-2013"
    part_volume_mm3: float = 0.0
    part_surface_area_mm2: float = 0.0
    part_mass_kg: float = 0.0
    bounding_box_mm: Dict[str, float] = field(default_factory=lambda: {"L": 100.0, "W": 50.0, "H": 50.0, "D_max": 50.0})
    blank_volume_mm3: Optional[float] = None
    blank_mass_kg: Optional[float] = None
    blank_type_hint: Optional[BlankType] = None
    batch_size_q: int = 10
    faces: List[BRepFaceNode] = field(default_factory=list)
    edges: List[BRepEdgeLink] = field(default_factory=list)
    pmi_bindings: List[PMIFaceBinding] = field(default_factory=list)
    raw_tech_requirements: List[str] = field(default_factory=list)


def _cos_angle(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na <= 1e-9 or nb <= 1e-9:
        return 0.0
    return abs(a[0] * b[0] + a[1] * b[1] + a[2] * b[2]) / (na * nb)


def detect_is_rotational_part(faces: List[BRepFaceNode]) -> bool:
    """Определяет тело вращения (§2.1: >60% площади образуют соосные цилиндр./конич./торц. грани)."""
    total_area = sum(max(f.area_mm2, 0.0) for f in faces)
    if total_area <= 1e-6:
        return False

    # Находим доминирующую ось по суммарной площади цилиндров/конусов
    axis_areas: List[Tuple[Tuple[float, float, float], float]] = []
    for f in faces:
        if f.surface_type in ("Cylinder", "Cone", "Torus") and not f.is_internal and f.axis_vector:
            axis_areas.append((f.axis_vector, f.area_mm2))

    if not axis_areas:
        return False

    # Выбираем главную ось с наибольшей площадью
    best_axis = max(axis_areas, key=lambda item: item[1])[0]
    coaxial_area = 0.0
    for f in faces:
        if f.surface_type in ("Cylinder", "Cone", "Torus") and f.axis_vector and _cos_angle(f.axis_vector, best_axis) >= 0.96:
            coaxial_area += f.area_mm2
        elif f.surface_type == "Plane" and _cos_angle(f.normal_vector, best_axis) >= 0.96:
            coaxial_area += f.area_mm2

    return (coaxial_area / total_area) > 0.60


def _compute_blank_defaults(
    bbox: Dict[str, float],
    part_vol_mm3: float,
    part_mass_kg: float,
    density_g_cm3: float,
    is_rotational: bool,
    blank_type_hint: Optional[BlankType],
) -> Tuple[BlankType, float, float]:
    """Авто-подбор заготовки и объема по ГОСТ/припуску (Приложение 11 для валов или плита)."""
    if is_rotational:
        btype = blank_type_hint or BlankType.ROLLED_BAR
        d_max = float(bbox.get("D_max") or max(bbox.get("W", 40.0), bbox.get("H", 40.0)))
        l_tot = float(bbox.get("L", 100.0))
        prip_a, prip_b = 4.0, 6.0
        try:
            rows = load_turning_db()["prilozhenie11"]["rows"]
            cand = [r for r in rows if float(r["D_max"]) >= d_max and float(r["L_max"]) >= l_tot]
            if cand:
                best = min(cand, key=lambda r: (float(r["D_max"]), float(r["L_max"])))
                prip_a = float(best["a"])
                prip_b = float(best["b"])
        except Exception:
            pass
        d_stock = d_max + prip_a
        l_stock = l_tot + prip_b
        blank_vol = max(part_vol_mm3 * 1.05, math.pi * ((d_stock / 2.0) ** 2) * l_stock)
    else:
        btype = blank_type_hint or BlankType.ROLLED_PLATE
        l_v = float(bbox.get("L", 100.0)) + 6.0
        w_v = float(bbox.get("W", 80.0)) + 6.0
        h_v = float(bbox.get("H", 40.0)) + 5.0
        blank_vol = max(part_vol_mm3 * 1.10, l_v * w_v * h_v)

    blank_mass = max(part_mass_kg * 1.05, (blank_vol / 1e6) * density_g_cm3)
    return btype, round(blank_vol, 2), round(blank_mass, 4)


def _apply_pmi_cascade(
    faces: List[BRepFaceNode],
    bindings: List[PMIFaceBinding],
    default_ra: float,
    default_it: int,
    fallback_source: PMISource,
) -> None:
    """Привязывает PMI к граням с каскадом Explicit_PMI -> Inherited_From_TT -> System_Default."""
    by_id: Dict[int, BRepFaceNode] = {f.face_id: f for f in faces}

    for bind in bindings:
        ra_val = parse_roughness_text(bind.roughness_text) if bind.roughness_text else None
        it_val, tol_um = (
            parse_tolerance_text(bind.tolerance_text, bind.nominal_mm or 30.0)
            if bind.tolerance_text
            else (None, None)
        )
        fcf_type = map_fcf_symbol_to_enum(bind.fcf_symbol or "")

        for fid in bind.face_ids:
            node = by_id.get(fid)
            if node is None:
                continue
            if bind.thread_pitch_mm and not node.pitch_mm:
                node.pitch_mm = bind.thread_pitch_mm

            cur = node.pmi or PMISpec(source=fallback_source, roughness_ra_um=default_ra, it_grade=default_it)
            updated = PMISpec(
                source=PMISource.EXPLICIT_PMI,
                roughness_ra_um=min(cur.roughness_ra_um, ra_val) if ra_val is not None else cur.roughness_ra_um,
                it_grade=min(cur.it_grade, it_val) if it_val is not None else cur.it_grade,
                tolerance_field_um=tol_um if tol_um is not None else cur.tolerance_field_um,
                geom_tolerance_type=fcf_type if fcf_type != GeomToleranceType.NONE else cur.geom_tolerance_type,
                geom_tolerance_val_mm=bind.fcf_value_mm if bind.fcf_value_mm is not None else cur.geom_tolerance_val_mm,
            )
            node.pmi = updated

    for f in faces:
        if f.pmi is None:
            f.pmi = PMISpec(
                source=fallback_source,
                roughness_ra_um=default_ra,
                it_grade=default_it,
            )


class BaseCADExtractor(ABC):
    """Единый интерфейс CAD-адаптера (Siemens NX / КОМПАС-3D / снимок)."""

    @abstractmethod
    def collect_snapshot(self, *args, **kwargs) -> RawCADModelSnapshot:
        """Извлекает сырой B-Rep, AAG-связи, масс-инерционные свойства, PMI и ТТ."""

    def build_passport(self, snapshot: RawCADModelSnapshot) -> PartPassport:
        """Преобразует снимок модели в валидированный классифицированный PartPassport v2.0."""
        mat_info = resolve_material_info(snapshot.material_raw)
        mat_group = MaterialGroup(mat_info["material_group"])
        mach_group = MachinabilityGroup(mat_info["machinability_group"])
        density = float(mat_info["density_g_cm3"])

        tt = parse_tech_requirements(snapshot.raw_tech_requirements)
        fallback_source = PMISource.INHERITED_TT if (tt.ra_source_found or tt.it_source_found) else PMISource.SYSTEM_DEFAULT

        is_rot = detect_is_rotational_part(snapshot.faces)
        part_vol = snapshot.part_volume_mm3
        if part_vol <= 0:
            part_vol = max(1000.0, sum(f.area_mm2 for f in snapshot.faces) * 4.0)
        part_mass = snapshot.part_mass_kg if snapshot.part_mass_kg > 0 else (part_vol / 1e6) * density

        if snapshot.blank_volume_mm3 and snapshot.blank_mass_kg:
            blank_type = snapshot.blank_type_hint or (BlankType.ROLLED_BAR if is_rot else BlankType.ROLLED_PLATE)
            blank_vol = max(part_vol, float(snapshot.blank_volume_mm3))
            blank_mass = max(part_mass, float(snapshot.blank_mass_kg))
        else:
            blank_type, blank_vol, blank_mass = _compute_blank_defaults(
                snapshot.bounding_box_mm,
                part_vol,
                part_mass,
                density,
                is_rot,
                snapshot.blank_type_hint,
            )

        removed_vol = max(0.0, blank_vol - part_vol)

        _apply_pmi_cascade(
            snapshot.faces,
            snapshot.pmi_bindings,
            default_ra=tt.default_ra_um,
            default_it=tt.default_it_grade,
            fallback_source=fallback_source,
        )

        recognizer = AAGFeatureRecognizer()
        d_stock_est = snapshot.bounding_box_mm.get("D_max", 40.0) + 4.0
        elements = recognizer.recognize(
            faces=snapshot.faces,
            edges=snapshot.edges,
            is_rotational_part=is_rot,
            default_ra=tt.default_ra_um,
            default_it=tt.default_it_grade,
            default_source=fallback_source,
            stock_diameter_mm=d_stock_est if is_rot else None,
        )

        q = max(1, int(snapshot.batch_size_q))
        prod_type = (
            ProductionType.SINGLE if q <= 1
            else ProductionType.SMALL_BATCH if q <= 15
            else ProductionType.MEDIUM_BATCH if q <= 100
            else ProductionType.MASS
        )

        passport = PartPassport(
            passport_version="2.0",
            part_id=snapshot.part_id,
            part_name=snapshot.part_name,
            cad_source=snapshot.cad_source,
            production_type=prod_type,
            batch_size_q=q,
            is_rotational_part=is_rot,
            material_raw_string=snapshot.material_raw,
            material_group=mat_group,
            machinability_group=mach_group,
            k_mat_coeff=float(mat_info["k_mat_coeff"]),
            blank_type=blank_type,
            hardness_hb_or_hrc=tt.hardness_hb_or_hrc,
            has_heat_treatment=tt.has_heat_treatment,
            has_coating=tt.has_coating,
            part_mass_kg=round(part_mass, 4),
            blank_mass_kg=round(blank_mass, 4),
            part_volume_mm3=round(part_vol, 2),
            blank_volume_mm3=round(blank_vol, 2),
            total_removed_volume_mm3=round(removed_vol, 2),
            bounding_box_mm=snapshot.bounding_box_mm,
            default_roughness_ra=tt.default_ra_um,
            default_it_grade=tt.default_it_grade,
            raw_tech_requirements_text=list(snapshot.raw_tech_requirements),
            elements=elements,
        )
        return classify_passport(passport)


__all__ = [
    "PMIFaceBinding",
    "RawCADModelSnapshot",
    "detect_is_rotational_part",
    "BaseCADExtractor",
]

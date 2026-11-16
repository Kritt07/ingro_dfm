"""Миграция старых форматов JSON-паспортов v1 (Python schema_passport и C# IngroDFMNX) в PartPassport v2.0."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List

from ingro_dfm.core_schema.part_passport import (
    BlankType,
    CADSource,
    DimensionsSpec,
    ElementCategory,
    FeatureOrFaceItem,
    GeomToleranceType,
    GeometryType,
    MachinabilityGroup,
    MaterialGroup,
    PMISource,
    PMISpec,
    PartPassport,
    ProductionType,
)
from ingro_dfm.database.loader import resolve_material_info


_SURF_MAP = {
    "cylinder": (GeometryType.CYLINDER_EXT, ElementCategory.ELEMENTARY_FACE),
    "цилиндр": (GeometryType.CYLINDER_EXT, ElementCategory.ELEMENTARY_FACE),
    "hole": (GeometryType.CYLINDER_INT_HOLE, ElementCategory.KTE_FEATURE),
    "отверстие": (GeometryType.CYLINDER_INT_HOLE, ElementCategory.KTE_FEATURE),
    "face_end": (GeometryType.PLANE, ElementCategory.ELEMENTARY_FACE),
    "плоскость": (GeometryType.PLANE, ElementCategory.ELEMENTARY_FACE),
    "shoulder": (GeometryType.STEP, ElementCategory.KTE_FEATURE),
    "уступ": (GeometryType.STEP, ElementCategory.KTE_FEATURE),
    "cone": (GeometryType.CONE, ElementCategory.ELEMENTARY_FACE),
    "конус": (GeometryType.CONE, ElementCategory.ELEMENTARY_FACE),
    "chamfer": (GeometryType.CHAMFER, ElementCategory.KTE_FEATURE),
    "фаска": (GeometryType.CHAMFER, ElementCategory.KTE_FEATURE),
    "groove": (GeometryType.GROOVE, ElementCategory.KTE_FEATURE),
    "канавка": (GeometryType.GROOVE, ElementCategory.KTE_FEATURE),
    "fillet": (GeometryType.GROOVE, ElementCategory.KTE_FEATURE),
    "галтель": (GeometryType.GROOVE, ElementCategory.KTE_FEATURE),
    "thread": (GeometryType.THREAD, ElementCategory.KTE_FEATURE),
    "резьба": (GeometryType.THREAD, ElementCategory.KTE_FEATURE),
    "keyway": (GeometryType.SLOT, ElementCategory.KTE_FEATURE),
    "паз": (GeometryType.SLOT, ElementCategory.KTE_FEATURE),
    "паз_фрез": (GeometryType.SLOT, ElementCategory.KTE_FEATURE),
    "pocket": (GeometryType.POCKET, ElementCategory.KTE_FEATURE),
    "карман": (GeometryType.POCKET, ElementCategory.KTE_FEATURE),
    "spline": (GeometryType.SPLINE, ElementCategory.KTE_FEATURE),
    "шлицы": (GeometryType.SPLINE, ElementCategory.KTE_FEATURE),
}

_STOCK_MAP = {
    "bar": BlankType.ROLLED_BAR,
    "круглый прокат": BlankType.ROLLED_BAR,
    "пруток": BlankType.ROLLED_BAR,
    "plate": BlankType.ROLLED_PLATE,
    "плита": BlankType.ROLLED_PLATE,
    "tube": BlankType.TUBE,
    "труба": BlankType.TUBE,
    "casting": BlankType.CASTING,
    "отливка": BlankType.CASTING,
    "forging": BlankType.STAMPING_FORGING,
    "поковка": BlankType.STAMPING_FORGING,
    "штамповка": BlankType.STAMPING_FORGING,
}


def _production_type_from_q(q: int) -> ProductionType:
    if q <= 1:
        return ProductionType.SINGLE
    if q <= 15:
        return ProductionType.SMALL_BATCH
    if q <= 100:
        return ProductionType.MEDIUM_BATCH
    return ProductionType.MASS


def _confidence_to_pmi_source(conf: str) -> PMISource:
    c = (conf or "").lower()
    if "pmi" in c:
        return PMISource.EXPLICIT_PMI
    if "manual" in c:
        return PMISource.USER_OVERRIDE
    if "tt" in c:
        return PMISource.INHERITED_TT
    if "geometry" in c:
        return PMISource.EXPLICIT_PMI
    return PMISource.SYSTEM_DEFAULT


def migrate_v1_to_v2(
    raw_v1: Dict[str, Any],
    cad_source: CADSource = CADSource.SIEMENS_NX,
) -> PartPassport:
    """Конвертирует словарь старого паспорта v1 (schema_passport / test_passport.json) в PartPassport v2.0."""
    if raw_v1.get("passport_version") == "2.0":
        return PartPassport.model_validate(raw_v1)

    ident = raw_v1.get("identification", {})
    geom = raw_v1.get("geometry", {})
    stock = raw_v1.get("stock", {})
    prod = raw_v1.get("production", {})

    mat_str = str(ident.get("material_key", "45"))
    mat_info = resolve_material_info(mat_str)
    mat_group = MaterialGroup(mat_info["material_group"])
    mach_group = MachinabilityGroup(mat_info["machinability_group"])
    density = float(ident.get("density_g_cm3") or mat_info["density_g_cm3"])

    hb = ident.get("hardness_hb")
    has_ht = bool(ident.get("has_heat_treatment", ident.get("heat_treatment", False)))
    q = int(prod.get("batch_size_q", prod.get("batch_q", 5)) or 5)

    d_max = float(geom.get("D_max_mm", 50.0) or 50.0)
    l_tot = float(geom.get("L_total_mm", 100.0) or 100.0)

    part_mass_kg = float(geom.get("part_mass_kg") or geom.get("mass_kg") or 1.0)
    part_vol_mm3 = float(geom.get("volume_cm3", 0.0) or 0.0) * 1000.0
    if part_vol_mm3 <= 0:
        part_vol_mm3 = (part_mass_kg * 1e6) / max(density, 0.1)

    d_stock = float(stock.get("D_stock_mm", prod.get("D_stock_mm", d_max + 4.0)) or (d_max + 4.0))
    l_stock = float(stock.get("L_stock_mm", prod.get("L_stock_mm", l_tot + 6.0)) or (l_tot + 6.0))
    blank_vol_mm3 = float(stock.get("volume_cm3", 0.0) or 0.0) * 1000.0
    if blank_vol_mm3 <= 0:
        blank_vol_mm3 = math.pi * ((d_stock / 2.0) ** 2) * l_stock

    blank_mass_kg = float(stock.get("mass_kg", prod.get("stock_mass_kg", 0.0)) or 0.0)
    if blank_mass_kg <= 0:
        blank_mass_kg = (blank_vol_mm3 / 1e6) * density

    blank_vol_mm3 = max(blank_vol_mm3, part_vol_mm3)
    blank_mass_kg = max(blank_mass_kg, part_mass_kg)
    removed_vol = max(0.0, blank_vol_mm3 - part_vol_mm3)

    stock_raw = str(stock.get("type", prod.get("stock_type", "bar"))).strip().lower()
    blank_type = _STOCK_MAP.get(stock_raw, BlankType.ROLLED_BAR)

    raw_surfaces: List[Dict[str, Any]] = raw_v1.get("surfaces", [])
    elements: List[FeatureOrFaceItem] = []

    rot_types = {"cylinder", "цилиндр", "cone", "конус", "chamfer", "фаска", "groove", "канавка", "галтель", "thread", "резьба", "face_end", "плоскость"}
    rot_count = 0

    for idx, s in enumerate(raw_surfaces, start=1):
        s_type_raw = str(s.get("surf_type", s.get("type", "cylinder"))).strip().lower()
        geom_type, category = _SURF_MAP.get(
            s_type_raw, (GeometryType.CYLINDER_EXT, ElementCategory.ELEMENTARY_FACE)
        )
        if s_type_raw in rot_types:
            rot_count += 1

        d_mm = float(s.get("D_mm", 0.0) or 0.0)
        l_mm = float(s.get("L_mm", 0.0) or 0.0)
        radius = float(s.get("radius_mm", s.get("extra_params", {}).get("radius_R_mm", 0.0)) or 0.0)
        groove_d = float(s.get("groove_depth_mm", s.get("extra_params", {}).get("groove_depth_mm", 0.0)) or 0.0)
        pitch = float(s.get("pitch_mm", s.get("extra_params", {}).get("pitch_mm", 0.0)) or 0.0)
        fillet_r = float(s.get("fillet_radius_mm", 0.0) or 0.0)
        inner_d = float(s.get("inner_d_mm", 0.0) or 0.0)

        if geom_type == GeometryType.PLANE:
            area = math.pi * (max(d_mm, 5.0) ** 2 - max(inner_d, 0.0) ** 2) / 4.0
            area = max(area, 25.0)
            vol_est = area * 2.5
            normal = (0.0, 0.0, 1.0 if idx % 2 == 1 else -1.0)
            setup_dir = "+Z" if normal[2] > 0 else "-Z"
        elif geom_type in (GeometryType.CYLINDER_EXT, GeometryType.CYLINDER_INT_HOLE, GeometryType.THREAD, GeometryType.CONE):
            diam = max(d_mm, 4.0)
            length = max(l_mm, 5.0)
            area = math.pi * diam * length
            if geom_type == GeometryType.CYLINDER_INT_HOLE:
                vol_est = math.pi * ((diam / 2.0) ** 2) * length
            else:
                z_allow = max(0.5, (d_stock - diam) / 2.0)
                vol_est = math.pi * diam * length * z_allow * 0.35
            normal = (1.0, 0.0, 0.0)
            setup_dir = "+X"
        elif geom_type == GeometryType.SLOT:
            w = max(s.get("width_mm", radius or 8.0), 3.0)
            length = max(l_mm, 20.0)
            depth = max(groove_d or 4.0, 2.0)
            area = length * w + 2.0 * length * depth
            vol_est = length * w * depth
            normal = (0.0, 1.0, 0.0)
            setup_dir = "+Y"
        else:
            diam = max(d_mm, 10.0)
            w = max(l_mm, groove_d, 2.0)
            area = max(math.pi * diam * w, 20.0)
            vol_est = area * max(groove_d, 1.0)
            normal = (1.0, 0.0, 0.0)
            setup_dir = "+X"

        ra_val = float(s.get("Ra_um", 6.3) or 6.3)
        it_val = max(1, min(17, int(s.get("IT", 12) or 12)))
        tag = int(s.get("tag", 0) or 0)
        code = str(s.get("code", f"E_{idx}"))

        elements.append(
            FeatureOrFaceItem(
                element_id=code,
                name=f"{code} ({s_type_raw})",
                cad_face_ids=[tag] if tag > 0 else [],
                category=category,
                geometry_type=geom_type,
                normal_vector=normal,
                setup_direction=setup_dir,
                area_mm2=round(area, 2),
                removed_volume_mm3=round(vol_est, 2),
                dimensions=DimensionsSpec(
                    diameter_mm=d_mm or None,
                    length_or_depth_mm=l_mm or (groove_d if groove_d > 0 else None),
                    width_mm=groove_d or (s.get("width_mm") or None),
                    allowance_t_mm=max(0.5, (d_stock - d_mm) / 2.0) if (d_mm > 0 and geom_type == GeometryType.CYLINDER_EXT) else 2.0,
                    corner_radius_mm=fillet_r or (radius if geom_type in (GeometryType.POCKET, GeometryType.GROOVE) else None),
                    pitch_mm=pitch or None,
                    radius_mm=fillet_r or (radius or None),
                ),
                pmi=PMISpec(
                    source=_confidence_to_pmi_source(str(s.get("confidence", "auto (PMI)" if s.get("function") else ""))),
                    roughness_ra_um=ra_val,
                    it_grade=it_val,
                    geom_tolerance_type=GeomToleranceType.NONE,
                ),
            )
        )

    is_rot = rot_count >= max(1, int(0.6 * max(len(raw_surfaces), 1)))
    part_name = str(ident.get("part_name", "PART_V1"))

    return PartPassport(
        passport_version="2.0",
        part_id=part_name,
        part_name=part_name,
        cad_source=cad_source,
        production_type=_production_type_from_q(q),
        batch_size_q=q,
        is_rotational_part=is_rot,
        material_raw_string=mat_str,
        material_group=mat_group,
        machinability_group=mach_group,
        k_mat_coeff=float(ident.get("Km") or mat_info["k_mat_coeff"]),
        blank_type=blank_type,
        hardness_hb_or_hrc=f"{int(hb)} HB" if hb else None,
        has_heat_treatment=has_ht,
        has_coating=False,
        part_mass_kg=round(part_mass_kg, 4),
        blank_mass_kg=round(blank_mass_kg, 4),
        part_volume_mm3=round(part_vol_mm3, 2),
        blank_volume_mm3=round(blank_vol_mm3, 2),
        total_removed_volume_mm3=round(removed_vol, 2),
        bounding_box_mm={"L": l_tot, "W": d_max, "H": d_max, "D_max": d_max},
        default_roughness_ra=12.5,
        default_it_grade=14,
        raw_tech_requirements_text=[],
        elements=elements,
    )


def migrate_v1_file(path: Path, cad_source: CADSource = CADSource.SIEMENS_NX) -> PartPassport:
    """Читает JSON-паспорт v1 (с поддержкой UTF-8 BOM) и мигрирует его в PartPassport v2.0."""
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return migrate_v1_to_v2(raw, cad_source=cad_source)


__all__ = ["migrate_v1_to_v2", "migrate_v1_file"]

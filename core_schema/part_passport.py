"""Модели Pydantic v2 для контракта данных PartPassport v2.0 (КТМД)."""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field


class CADSource(str, Enum):
    SIEMENS_NX = "Siemens_NX"
    KOMPAS_3D = "Kompas_3D"
    STEP_STANDALONE = "STEP_Standalone"


class ProductionType(str, Enum):
    SINGLE = "Single"
    SMALL_BATCH = "SmallBatch"
    MEDIUM_BATCH = "MediumBatch"
    MASS = "Mass"


class MaterialGroup(str, Enum):
    CARBON_STEEL = "ST_Carbon"
    ALLOY_STEEL = "ST_Alloy"
    STAINLESS_STEEL = "ST_Stainless"
    CAST_IRON_GRAY = "CI_Gray"
    CAST_IRON_DUCTILE = "CI_Ductile"
    ALUMINUM_ALLOY = "AL_Alloy"
    COPPER_ALLOY = "CU_Alloy"
    TITANIUM_ALLOY = "TI_Alloy"


class MachinabilityGroup(str, Enum):
    GOOD = "G1_Good"
    SATISFACTORY = "G2_Satisfactory"
    POOR = "G3_Poor"


class BlankType(str, Enum):
    ROLLED_BAR = "PR_Bar"
    ROLLED_PLATE = "PR_Plate"
    TUBE = "PR_Tube"
    CASTING = "LT_Casting"
    STAMPING_FORGING = "SH_Forging"


class ElementCategory(str, Enum):
    KTE_FEATURE = "KTE"
    ELEMENTARY_FACE = "FACE"


class GeometryType(str, Enum):
    CYLINDER_EXT = "CYL"
    CYLINDER_INT_HOLE = "HOL"
    PLANE = "PLN"
    CONE = "CON"
    SPHERE = "SPH"
    SLOT = "SLT"
    POCKET = "PKT"
    STEP = "STP"
    CHAMFER = "CHM"
    GROOVE = "GRV"
    THREAD = "THR"
    SPLINE = "SPL"


class GeomToleranceType(str, Enum):
    NONE = "GT_NONE"
    POSITION = "GT_POS"
    ORIENTATION = "GT_ORT"
    FORM_RUNOUT = "GT_FRM"


class PMISource(str, Enum):
    EXPLICIT_PMI = "Explicit_PMI"
    INHERITED_TT = "Inherited_From_TT"
    SYSTEM_DEFAULT = "System_Default"
    USER_OVERRIDE = "User_Override"


class DimensionsSpec(BaseModel):
    diameter_mm: Optional[float] = None
    length_or_depth_mm: Optional[float] = None
    width_mm: Optional[float] = None
    allowance_t_mm: Optional[float] = Field(default=2.0, description="Припуск на обработку")
    corner_radius_mm: Optional[float] = None
    is_blind: bool = False
    identical_count: int = Field(default=1, ge=1, description="Число одинаковых элементов в массиве")
    pitch_mm: Optional[float] = Field(default=None, description="Шаг резьбы / модуль (доп. параметр КТЭ)")
    radius_mm: Optional[float] = Field(default=None, description="Радиус галтели / сферы")


class PMISpec(BaseModel):
    source: PMISource = PMISource.SYSTEM_DEFAULT
    roughness_ra_um: float = Field(default=12.5, gt=0)
    it_grade: int = Field(default=14, ge=1, le=17)
    tolerance_field_um: Optional[float] = None
    geom_tolerance_type: GeomToleranceType = GeomToleranceType.NONE
    geom_tolerance_val_mm: Optional[float] = None


class ClassificationSpec(BaseModel):
    tech_code_10: Optional[str] = None
    assigned_transitions: List[str] = Field(default_factory=list)
    cbnt_search_filters: Dict[str, Union[float, str, int]] = Field(default_factory=dict)


class FeatureOrFaceItem(BaseModel):
    element_id: str
    name: str
    cad_face_ids: List[int] = Field(default_factory=list)
    category: ElementCategory
    geometry_type: GeometryType
    normal_vector: Tuple[float, float, float] = (0.0, 0.0, 1.0)
    setup_direction: str = Field(default="+Z", description="Ось подхода инструмента: +X,-X,+Y,-Y,+Z,-Z,Custom")
    area_mm2: float = Field(..., gt=0)
    removed_volume_mm3: float = Field(default=0.0, ge=0)
    dimensions: DimensionsSpec
    pmi: PMISpec
    classification: ClassificationSpec = Field(default_factory=ClassificationSpec)


class PartPassport(BaseModel):
    passport_version: str = "2.0"
    part_id: str
    part_name: str
    cad_source: CADSource
    production_type: ProductionType = ProductionType.SMALL_BATCH
    batch_size_q: int = Field(default=10, ge=1)
    is_rotational_part: bool = False

    # Материал и заготовка
    material_raw_string: str
    material_group: MaterialGroup
    machinability_group: MachinabilityGroup = MachinabilityGroup.SATISFACTORY
    k_mat_coeff: float = Field(default=1.0, gt=0)
    blank_type: BlankType = BlankType.ROLLED_BAR
    hardness_hb_or_hrc: Optional[str] = None
    has_heat_treatment: bool = False
    has_coating: bool = False

    # Масс-габаритные параметры
    part_mass_kg: float = Field(..., gt=0)
    blank_mass_kg: float = Field(..., gt=0)
    part_volume_mm3: float = Field(..., gt=0)
    blank_volume_mm3: float = Field(..., gt=0)
    total_removed_volume_mm3: float = Field(..., ge=0)
    bounding_box_mm: Dict[str, float]  # {"L": float, "W": float, "H": float, "D_max": float}

    # Технические требования по умолчанию
    default_roughness_ra: float = 12.5
    default_it_grade: int = 14
    raw_tech_requirements_text: List[str] = Field(default_factory=list)

    # Массив распознанных КТЭ и элементарных поверхностей
    elements: List[FeatureOrFaceItem]


__all__ = [
    "CADSource",
    "ProductionType",
    "MaterialGroup",
    "MachinabilityGroup",
    "BlankType",
    "ElementCategory",
    "GeometryType",
    "GeomToleranceType",
    "PMISource",
    "DimensionsSpec",
    "PMISpec",
    "ClassificationSpec",
    "FeatureOrFaceItem",
    "PartPassport",
]

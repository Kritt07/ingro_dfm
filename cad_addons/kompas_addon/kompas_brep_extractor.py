"""Адаптер КОМПАС-3D (API 7 через COM win32com): извлечение B-Rep, AAG, массы и свойств."""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ingro_dfm.cad_addons.base_extractor import (
    BaseCADExtractor,
    PMIFaceBinding,
    RawCADModelSnapshot,
)
from ingro_dfm.classifier.aag_feature_recognizer import BRepEdgeLink, BRepFaceNode
from ingro_dfm.core_schema.part_passport import BlankType, CADSource, PartPassport

logger = logging.getLogger(__name__)


class KompasBRepExtractor(BaseCADExtractor):
    """Экстрактор 3D-геометрии и дерева элементов из КОМПАС-3D API7 (или JSON-снимка)."""

    def collect_snapshot(
        self,
        doc3d: Optional[Any] = None,
        snapshot_json_path: Optional[Path] = None,
        pmi_bindings: Optional[List[PMIFaceBinding]] = None,
        raw_tt: Optional[List[str]] = None,
    ) -> RawCADModelSnapshot:
        if snapshot_json_path is not None:
            return self.load_snapshot_from_json(Path(snapshot_json_path))

        try:
            import win32com.client  # type: ignore
        except ImportError as exc:
            raise RuntimeError("Пакет pywin32 (win32com) не установлен для работы с КОМПАС-3D API 7.") from exc

        if doc3d is None:
            app = win32com.client.GetActiveObject("Kompas.Application.7")
            doc3d = app.ActiveDocument
        if doc3d is None:
            raise RuntimeError("В КОМПАС-3D не открыт активный 3D-документ.")

        top_part = doc3d.TopPart  # IPart7
        model_container = top_part.ModelContainer if hasattr(top_part, "ModelContainer") else top_part
        bodies = list(getattr(model_container, "Bodies", []) or [])
        if not bodies:
            raise RuntimeError("В детали КОМПАС-3D отсутствуют твердые тела (IBody7).")

        blank_body = next(
            (b for b in bodies if any(k in str(getattr(b, "Name", "")).lower() for k in ("заготов", "blank", "stock"))),
            None,
        )
        part_bodies = [b for b in bodies if b is not blank_body] or [bodies[0]]

        faces: List[BRepFaceNode] = []
        edges: List[BRepEdgeLink] = []
        seen_edges: set[int] = set()

        min_x = min_y = min_z = float("inf")
        max_x = max_y = max_z = float("-inf")
        total_area = 0.0
        total_vol = 0.0
        total_mass = 0.0

        # Масс-инерционные свойства
        try:
            mi = top_part.MassInertiaParam
            if hasattr(mi, "Volume"):
                total_vol = float(mi.Volume)
            if hasattr(mi, "Area"):
                total_area = float(mi.Area)
            if hasattr(mi, "Mass"):
                total_mass = float(mi.Mass)
        except Exception:
            pass

        for body in part_bodies:
            for k_face in getattr(body, "Faces", []):
                ref_id = int(getattr(k_face, "Reference", id(k_face)))
                area = float(getattr(k_face, "Area", 100.0) or 100.0)
                if total_area == 0.0:
                    total_area += area

                surf_type = "Plane"
                normal = (0.0, 0.0, 1.0)
                axis = None
                diameter = None
                is_internal = False
                bbox = (0.0, 10.0, 0.0, 10.0, 0.0, 10.0)

                try:
                    ms = k_face.MathSurface
                    if getattr(k_face, "IsCylinder", False):
                        surf_type = "Cylinder"
                        r = float(ms.GetCylinderRadius() if hasattr(ms, "GetCylinderRadius") else 10.0)
                        diameter = round(2.0 * r, 3)
                    elif getattr(k_face, "IsCone", False):
                        surf_type = "Cone"
                    elif getattr(k_face, "IsPlane", False):
                        surf_type = "Plane"
                    elif getattr(k_face, "IsSphere", False):
                        surf_type = "Sphere"
                    elif getattr(k_face, "IsTorus", False):
                        surf_type = "Torus"
                    else:
                        surf_type = "BSplineSurface"

                    gabarit = k_face.Gabarit
                    if hasattr(gabarit, "MinX"):
                        bbox = (
                            float(gabarit.MinX),
                            float(gabarit.MaxX),
                            float(gabarit.MinY),
                            float(gabarit.MaxY),
                            float(gabarit.MinZ),
                            float(gabarit.MaxZ),
                        )
                        min_x, min_y, min_z = min(min_x, bbox[0]), min(min_y, bbox[2]), min(min_z, bbox[4])
                        max_x, max_y, max_z = max(max_x, bbox[1]), max(max_y, bbox[3]), max(max_z, bbox[5])

                    nrm = k_face.GetNormal(0.5, 0.5)
                    if nrm:
                        normal = (float(nrm[0]), float(nrm[1]), float(nrm[2]))
                except Exception:
                    pass

                dx, dy, dz = bbox[1] - bbox[0], bbox[3] - bbox[2], bbox[5] - bbox[4]
                faces.append(
                    BRepFaceNode(
                        face_id=ref_id,
                        surface_type=surf_type,
                        area_mm2=round(area, 2),
                        normal_vector=normal,
                        axis_vector=axis or (normal if surf_type in ("Cylinder", "Cone") else None),
                        is_internal=is_internal,
                        diameter_mm=diameter,
                        length_mm=round(max(dx, dy, dz), 3),
                        bounding_box_mm=bbox,
                    )
                )

            for k_edge in getattr(body, "Edges", []):
                eid = int(getattr(k_edge, "Reference", id(k_edge)))
                if eid in seen_edges:
                    continue
                seen_edges.add(eid)
                adj = list(getattr(k_edge, "Faces", []) or [])
                if len(adj) == 2:
                    edges.append(
                        BRepEdgeLink(
                            face_a_id=int(getattr(adj[0], "Reference", id(adj[0]))),
                            face_b_id=int(getattr(adj[1], "Reference", id(adj[1]))),
                            edge_convexity="convex",
                        )
                    )

        L = round(max(1.0, max_x - min_x), 2) if max_x > min_x else 100.0
        W = round(max(1.0, max_y - min_y), 2) if max_y > min_y else 50.0
        H = round(max(1.0, max_z - min_z), 2) if max_z > min_z else 50.0

        part_name = str(getattr(top_part, "Name", "KOMPAS_PART"))
        mat_raw = str(getattr(top_part, "Material", "Сталь 45 ГОСТ 1050-2013") or "Сталь 45 ГОСТ 1050-2013")

        return RawCADModelSnapshot(
            part_id=str(getattr(top_part, "Marking", part_name) or part_name),
            part_name=part_name,
            cad_source=CADSource.KOMPAS_3D,
            material_raw=mat_raw,
            part_volume_mm3=round(total_vol, 2),
            part_surface_area_mm2=round(total_area, 2),
            part_mass_kg=round(total_mass, 4),
            bounding_box_mm={"L": L, "W": W, "H": H, "D_max": round(max(W, H), 2)},
            faces=faces,
            edges=edges,
            pmi_bindings=pmi_bindings or [],
            raw_tech_requirements=raw_tt or [],
        )

    def load_snapshot_from_json(self, json_path: Path) -> RawCADModelSnapshot:
        """Загружает B-Rep+AAG+PMI снимок из JSON (для offline/pytest верификации КОМПАС-адаптера)."""
        with json_path.open("r", encoding="utf-8-sig") as fh:
            raw = json.load(fh)
        faces = [BRepFaceNode(**f) for f in raw.get("faces", [])]
        edges = [BRepEdgeLink(**e) for e in raw.get("edges", [])]
        bindings = [PMIFaceBinding(**b) for b in raw.get("pmi_bindings", [])]
        btype = BlankType(raw["blank_type_hint"]) if raw.get("blank_type_hint") else None
        return RawCADModelSnapshot(
            part_id=raw.get("part_id", raw.get("part_name", "KOMPAS_PART")),
            part_name=raw.get("part_name", "KOMPAS_PART"),
            cad_source=CADSource(raw.get("cad_source", CADSource.KOMPAS_3D.value)),
            material_raw=raw.get("material_raw", "Сталь 45 ГОСТ 1050-2013"),
            part_volume_mm3=float(raw.get("part_volume_mm3", 0.0)),
            part_surface_area_mm2=float(raw.get("part_surface_area_mm2", 0.0)),
            part_mass_kg=float(raw.get("part_mass_kg", 0.0)),
            bounding_box_mm=raw.get("bounding_box_mm", {"L": 100.0, "W": 50.0, "H": 50.0, "D_max": 50.0}),
            blank_volume_mm3=raw.get("blank_volume_mm3"),
            blank_mass_kg=raw.get("blank_mass_kg"),
            blank_type_hint=btype,
            batch_size_q=int(raw.get("batch_size_q", 10)),
            faces=faces,
            edges=edges,
            pmi_bindings=bindings,
            raw_tech_requirements=list(raw.get("raw_tech_requirements", [])),
        )

    def extract_passport(self, **kwargs) -> PartPassport:
        snapshot = self.collect_snapshot(**kwargs)
        return self.build_passport(snapshot)


__all__ = ["KompasBRepExtractor"]

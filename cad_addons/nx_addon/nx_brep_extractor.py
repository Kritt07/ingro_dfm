"""Адаптер Siemens NX Open: извлечение B-Rep геометрии, масс-инерционных свойств и AAG."""

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


def _attr_str(obj: Any, title: str, default: Optional[str] = None) -> Optional[str]:
    try:
        if obj.HasUserAttribute(title, -1, -1):
            return str(obj.GetUserAttributeAsString(title, -1, -1))
    except Exception:
        try:
            val = obj.GetUserAttribute(title)
            return str(val) if val is not None else default
        except Exception:
            pass
    return default


def _map_nx_face_type(nx_face: Any) -> str:
    try:
        stype = str(nx_face.SolidFaceType).lower()
        if "cyl" in stype:
            return "Cylinder"
        if "planar" in stype or "plane" in stype:
            return "Plane"
        if "conical" in stype or "cone" in stype:
            return "Cone"
        if "spher" in stype:
            return "Sphere"
        if "toroid" in stype or "torus" in stype:
            return "Torus"
    except Exception:
        pass
    return "BSplineSurface"


class NXBRepExtractor(BaseCADExtractor):
    """Экстрактор Siemens NX Open (NXOpen Python API + автономный JSON-режим)."""

    def collect_snapshot(
        self,
        part: Optional[Any] = None,
        snapshot_json_path: Optional[Path] = None,
        pmi_bindings: Optional[List[PMIFaceBinding]] = None,
        raw_tt: Optional[List[str]] = None,
    ) -> RawCADModelSnapshot:
        if snapshot_json_path is not None:
            return self.load_snapshot_from_json(Path(snapshot_json_path))

        try:
            import NXOpen  # type: ignore
            import NXOpen.UF  # type: ignore
        except ImportError:
            try:
                import nxopen as NXOpen  # type: ignore
                import nxopen.uf as _uf  # noqa: F401
            except ImportError as exc:
                raise RuntimeError(
                    "NXOpen недоступен вне среды Siemens NX. Используйте snapshot_json_path или запуск внутри NX."
                ) from exc

        if part is None:
            session = NXOpen.Session.GetSession()
            part = session.Parts.Work
        if part is None:
            raise RuntimeError("В активной сессии Siemens NX нет открытой детали.")

        uf = NXOpen.UF.UFSession.GetUFSession()
        bodies = list(part.Bodies)
        if not bodies:
            raise RuntimeError("В детали NX отсутствуют твердые тела B-Rep.")

        blank_body = next(
            (b for b in bodies if any(k in (b.Name or "").lower() for k in ("заготов", "blank", "stock"))),
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

        # Сбор флагов резьбы и фасок по дереву Features
        thread_face_hints: Dict[int, float] = {}
        try:
            for feat in part.Features:
                ftype = str(getattr(feat, "FeatureType", "")).upper()
                if "THREAD" in ftype:
                    pitch = 1.5
                    for f in feat.GetFaces():
                        thread_face_hints[int(f.Tag)] = pitch
        except Exception:
            pass

        for body in part_bodies:
            try:
                mass_props, _ = uf.Modl.AskMassProps3d([body.Tag], 1, 1, 4, 1.0, 1, [0.99, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
                total_area += float(mass_props[0])
                total_vol += float(mass_props[1])
            except Exception:
                pass

            for nx_face in body.GetFaces():
                tag = int(nx_face.Tag)
                surf_type = _map_nx_face_type(nx_face)
                normal = (0.0, 0.0, 1.0)
                axis: Optional[Tuple[float, float, float]] = None
                diameter = None
                is_internal = False
                area = 100.0
                origin = (0.0, 0.0, 0.0)

                try:
                    data = uf.Modl.AskFaceData(tag)
                    # UFModl.AskFaceData: type, point, dir, box, radius, rad_data, norm_dir
                    point, dir_vec, box, radius, _, norm_dir = data[1], data[2], data[3], data[4], data[5], data[6]
                    origin = (float(point[0]), float(point[1]), float(point[2]))
                    d_vec = (float(dir_vec[0]), float(dir_vec[1]), float(dir_vec[2]))
                    if surf_type == "Plane":
                        normal = d_vec
                    else:
                        axis = d_vec
                        normal = d_vec
                    if radius and float(radius) > 0:
                        diameter = round(float(radius) * 2.0, 3)
                    is_internal = int(norm_dir) < 0
                    min_x, min_y, min_z = min(min_x, box[0]), min(min_y, box[1]), min(min_z, box[2])
                    max_x, max_y, max_z = max(max_x, box[3]), max(max_y, box[4]), max(max_z, box[5])
                    bbox_tuple = (float(box[0]), float(box[3]), float(box[1]), float(box[4]), float(box[2]), float(box[5]))
                    dx, dy, dz = box[3] - box[0], box[4] - box[1], box[5] - box[2]
                    length_val = round(max(dx, dy, dz), 3)
                    if total_area == 0.0:
                        area = max(10.0, math.pi * (diameter or dx) * length_val)
                except Exception:
                    bbox_tuple = (0.0, 10.0, 0.0, 10.0, 0.0, 10.0)
                    length_val = 10.0

                hint = "Thread" if tag in thread_face_hints else None
                faces.append(
                    BRepFaceNode(
                        face_id=tag,
                        surface_type=surf_type,
                        area_mm2=round(area, 2),
                        normal_vector=normal,
                        axis_vector=axis,
                        origin_point=origin,
                        is_internal=is_internal,
                        diameter_mm=diameter,
                        length_mm=length_val,
                        bounding_box_mm=bbox_tuple,
                        feature_hint=hint,
                        pitch_mm=thread_face_hints.get(tag),
                    )
                )

            for nx_edge in body.GetEdges():
                etag = int(nx_edge.Tag)
                if etag in seen_edges:
                    continue
                seen_edges.add(etag)
                adj = list(nx_edge.GetFaces())
                if len(adj) == 2:
                    t1, t2 = int(adj[0].Tag), int(adj[1].Tag)
                    edges.append(BRepEdgeLink(face_a_id=t1, face_b_id=t2, edge_convexity="convex"))

        L = round(max(1.0, max_x - min_x), 2) if max_x > min_x else 100.0
        W = round(max(1.0, max_y - min_y), 2) if max_y > min_y else 50.0
        H = round(max(1.0, max_z - min_z), 2) if max_z > min_z else 50.0
        d_max = round(max(W, H), 2)

        blank_vol = None
        if blank_body is not None:
            try:
                mp_b, _ = uf.Modl.AskMassProps3d([blank_body.Tag], 1, 1, 4, 1.0, 1, [0.99] + [0.0] * 10)
                blank_vol = float(mp_b[1])
            except Exception:
                pass

        mat_raw = _attr_str(part, "Material", _attr_str(part, "MaterialKey", "Сталь 45")) or "Сталь 45"
        q = int(_attr_str(part, "BatchSize", "10") or "10")

        return RawCADModelSnapshot(
            part_id=str(getattr(part, "Name", "NX_PART")),
            part_name=str(getattr(part, "Name", "NX_PART")),
            cad_source=CADSource.SIEMENS_NX,
            material_raw=mat_raw,
            part_volume_mm3=round(total_vol, 2),
            part_surface_area_mm2=round(total_area, 2),
            bounding_box_mm={"L": L, "W": W, "H": H, "D_max": d_max},
            blank_volume_mm3=blank_vol,
            batch_size_q=q,
            faces=faces,
            edges=edges,
            pmi_bindings=pmi_bindings or [],
            raw_tech_requirements=raw_tt or [],
        )

    def load_snapshot_from_json(self, json_path: Path) -> RawCADModelSnapshot:
        """Загружает предсобранный B-Rep+AAG+PMI снимок из JSON (для offline/pytest верификации)."""
        with json_path.open("r", encoding="utf-8-sig") as fh:
            raw = json.load(fh)
        faces = [BRepFaceNode(**f) for f in raw.get("faces", [])]
        edges = [BRepEdgeLink(**e) for e in raw.get("edges", [])]
        bindings = [PMIFaceBinding(**b) for b in raw.get("pmi_bindings", [])]
        btype = BlankType(raw["blank_type_hint"]) if raw.get("blank_type_hint") else None
        return RawCADModelSnapshot(
            part_id=raw.get("part_id", raw.get("part_name", "NX_PART")),
            part_name=raw.get("part_name", "NX_PART"),
            cad_source=CADSource(raw.get("cad_source", CADSource.SIEMENS_NX.value)),
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


__all__ = ["NXBRepExtractor"]

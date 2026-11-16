"""Распознавание КТЭ по графу смежности граней (AAG — Attributed Adjacency Graph)."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from ingro_dfm.core_schema.part_passport import (
    DimensionsSpec,
    ElementCategory,
    FeatureOrFaceItem,
    GeomToleranceType,
    GeometryType,
    PMISource,
    PMISpec,
)

logger = logging.getLogger(__name__)


@dataclass
class BRepFaceNode:
    face_id: int
    surface_type: str  # Plane, Cylinder, Cone, Sphere, Torus, BSplineSurface
    area_mm2: float
    normal_vector: Tuple[float, float, float] = (0.0, 0.0, 1.0)
    axis_vector: Optional[Tuple[float, float, float]] = None
    origin_point: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    is_internal: bool = False
    diameter_mm: Optional[float] = None
    length_mm: Optional[float] = None
    width_mm: Optional[float] = None
    bounding_box_mm: Tuple[float, float, float, float, float, float] = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    pmi: Optional[PMISpec] = None
    feature_hint: Optional[str] = None
    pitch_mm: Optional[float] = None
    name: Optional[str] = None


@dataclass
class BRepEdgeLink:
    face_a_id: int
    face_b_id: int
    edge_convexity: str = "convex"  # convex, concave, smooth
    dihedral_angle_deg: float = 90.0


@dataclass
class AAGGraph:
    nodes: Dict[int, BRepFaceNode] = field(default_factory=dict)
    adjacency: Dict[int, List[BRepEdgeLink]] = field(default_factory=dict)

    def neighbors(self, face_id: int, convexity: Optional[str] = None) -> List[int]:
        links = self.adjacency.get(face_id, [])
        res: List[int] = []
        for link in links:
            if convexity is not None and link.edge_convexity != convexity:
                continue
            other = link.face_b_id if link.face_a_id == face_id else link.face_a_id
            res.append(other)
        return res


def _dot(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _normalize(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    norm = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if norm <= 1e-9:
        return (0.0, 0.0, 1.0)
    return (v[0] / norm, v[1] / norm, v[2] / norm)


def quantize_setup_direction(vec: Tuple[float, float, float]) -> str:
    """Квантует направление подхода инструмента в {+X,-X,+Y,-Y,+Z,-Z,Custom}."""
    v = _normalize(vec)
    axes = (
        ("+X", (1.0, 0.0, 0.0)),
        ("-X", (-1.0, 0.0, 0.0)),
        ("+Y", (0.0, 1.0, 0.0)),
        ("-Y", (0.0, -1.0, 0.0)),
        ("+Z", (0.0, 0.0, 1.0)),
        ("-Z", (0.0, 0.0, -1.0)),
    )
    best_name, best_cos = max(((name, _dot(v, ax)) for name, ax in axes), key=lambda item: item[1])
    if best_cos >= 0.82:
        return best_name
    return "Custom"


def _combine_pmi(faces: Sequence[BRepFaceNode], default_ra: float, default_it: int, default_source: PMISource) -> PMISpec:
    """Объединяет PMI группы граней в КТЭ (берет наиболее строгие Ra/IT и явные допуски)."""
    with_pmi = [f.pmi for f in faces if f.pmi is not None]
    if not with_pmi:
        return PMISpec(source=default_source, roughness_ra_um=default_ra, it_grade=default_it)

    priority = {
        PMISource.USER_OVERRIDE: 4,
        PMISource.EXPLICIT_PMI: 3,
        PMISource.INHERITED_TT: 2,
        PMISource.SYSTEM_DEFAULT: 1,
    }
    best_source = max((p.source for p in with_pmi), key=lambda s: priority.get(s, 0))
    best_ra = min(p.roughness_ra_um for p in with_pmi)
    best_it = min(p.it_grade for p in with_pmi)
    tols = [p.tolerance_field_um for p in with_pmi if p.tolerance_field_um is not None]
    fcf = [p for p in with_pmi if p.geom_tolerance_type != GeomToleranceType.NONE]
    best_fcf = min(fcf, key=lambda p: p.geom_tolerance_val_mm if p.geom_tolerance_val_mm is not None else 999.0) if fcf else None
    return PMISpec(
        source=best_source,
        roughness_ra_um=best_ra,
        it_grade=best_it,
        tolerance_field_um=min(tols) if tols else None,
        geom_tolerance_type=best_fcf.geom_tolerance_type if best_fcf else GeomToleranceType.NONE,
        geom_tolerance_val_mm=best_fcf.geom_tolerance_val_mm if best_fcf else None,
    )


def _group_bbox(faces: Sequence[BRepFaceNode]) -> Tuple[float, float, float, float, float, float]:
    xs_min = [f.bounding_box_mm[0] for f in faces]
    xs_max = [f.bounding_box_mm[1] for f in faces]
    ys_min = [f.bounding_box_mm[2] for f in faces]
    ys_max = [f.bounding_box_mm[3] for f in faces]
    zs_min = [f.bounding_box_mm[4] for f in faces]
    zs_max = [f.bounding_box_mm[5] for f in faces]
    return (min(xs_min), max(xs_max), min(ys_min), max(ys_max), min(zs_min), max(zs_max))


class AAGFeatureRecognizer:
    """Распознаватель КТЭ по B-Rep граням и графу смежности (AAG)."""

    def build_graph(self, faces: Sequence[BRepFaceNode], edges: Sequence[BRepEdgeLink]) -> AAGGraph:
        nodes = {f.face_id: f for f in faces}
        adjacency: Dict[int, List[BRepEdgeLink]] = {f.face_id: [] for f in faces}
        for edge in edges:
            if edge.face_a_id in adjacency and edge.face_b_id in adjacency:
                adjacency[edge.face_a_id].append(edge)
                adjacency[edge.face_b_id].append(edge)
        return AAGGraph(nodes=nodes, adjacency=adjacency)

    def recognize(
        self,
        faces: Sequence[BRepFaceNode],
        edges: Sequence[BRepEdgeLink],
        is_rotational_part: bool = False,
        default_ra: float = 12.5,
        default_it: int = 14,
        default_source: PMISource = PMISource.SYSTEM_DEFAULT,
        stock_diameter_mm: Optional[float] = None,
    ) -> List[FeatureOrFaceItem]:
        graph = self.build_graph(faces, edges)
        consumed: Set[int] = set()
        elements: List[FeatureOrFaceItem] = []
        kte_seq = 0

        def next_id(prefix: str) -> str:
            nonlocal kte_seq
            kte_seq += 1
            return f"{prefix}_{kte_seq:03d}"

        # 1. Явные признаки резьбы и шлицев/зубьев из дерева или PMI
        for f in faces:
            if f.face_id in consumed:
                continue
            hint = (f.feature_hint or "").lower()
            if any(k in hint for k in ("thread", "резьб")):
                consumed.add(f.face_id)
                d = f.diameter_mm or 12.0
                l_val = f.length_mm or 15.0
                axis = f.axis_vector or f.normal_vector
                elements.append(
                    FeatureOrFaceItem(
                        element_id=next_id("THR"),
                        name=f.name or f"Резьба Ø{d:.1f}x{l_val:.1f}",
                        cad_face_ids=[f.face_id],
                        category=ElementCategory.KTE_FEATURE,
                        geometry_type=GeometryType.THREAD,
                        normal_vector=_normalize(axis),
                        setup_direction=quantize_setup_direction(axis),
                        area_mm2=max(f.area_mm2, 1.0),
                        removed_volume_mm3=round(math.pi * d * l_val * (f.pitch_mm or 1.5) * 0.4, 2),
                        dimensions=DimensionsSpec(
                            diameter_mm=d,
                            length_or_depth_mm=l_val,
                            allowance_t_mm=1.0,
                            pitch_mm=f.pitch_mm or 1.5,
                        ),
                        pmi=_combine_pmi([f], default_ra, default_it, default_source),
                    )
                )
            elif any(k in hint for k in ("spline", "gear", "шлиц", "зуб")):
                consumed.add(f.face_id)
                d = f.diameter_mm or 30.0
                l_val = f.length_mm or 25.0
                axis = f.axis_vector or f.normal_vector
                elements.append(
                    FeatureOrFaceItem(
                        element_id=next_id("SPL"),
                        name=f.name or f"Шлицы Ø{d:.1f}",
                        cad_face_ids=[f.face_id],
                        category=ElementCategory.KTE_FEATURE,
                        geometry_type=GeometryType.SPLINE,
                        normal_vector=_normalize(axis),
                        setup_direction=quantize_setup_direction(axis),
                        area_mm2=max(f.area_mm2, 1.0),
                        removed_volume_mm3=round(max(f.area_mm2, 10.0) * 2.5, 2),
                        dimensions=DimensionsSpec(diameter_mm=d, length_or_depth_mm=l_val, allowance_t_mm=2.5),
                        pmi=_combine_pmi([f], default_ra, default_it, default_source),
                    )
                )

        # 2. Внутренние отверстия (HOL: сквозные и глухие) и токарные канавки (GRV)
        hole_candidates: List[FeatureOrFaceItem] = []
        for f in faces:
            if f.face_id in consumed or f.surface_type != "Cylinder" or not f.is_internal:
                continue

            # Проверяем, не является ли это узкой токарной канавкой между двумя противоположными торцами
            concave_nbrs = [graph.nodes[nid] for nid in graph.neighbors(f.face_id, "concave") if nid not in consumed]
            plane_nbrs = [n for n in concave_nbrs if n.surface_type == "Plane"]
            d = f.diameter_mm or max(0.0, f.bounding_box_mm[1] - f.bounding_box_mm[0]) or 10.0
            l_val = f.length_mm or max(0.0, f.bounding_box_mm[5] - f.bounding_box_mm[4]) or 10.0

            # Исключаем угловые скругления карманов/пазов (часть дуги < 250° либо смежность с плоским дном, имеющим >= 2 стенок)
            is_pocket_corner = (
                f.diameter_mm and f.length_mm and f.area_mm2 < 0.70 * math.pi * d * l_val
            ) or any(
                len([
                    graph.nodes[pid]
                    for pid in graph.neighbors(p.face_id, "concave")
                    if graph.nodes[pid].surface_type == "Plane"
                    and abs(_dot(_normalize(graph.nodes[pid].normal_vector), _normalize(p.normal_vector))) < 0.35
                ]) >= 2
                for p in plane_nbrs
            )
            if is_pocket_corner:
                continue

            if is_rotational_part and len(plane_nbrs) == 2 and _dot(_normalize(plane_nbrs[0].normal_vector), _normalize(plane_nbrs[1].normal_vector)) < -0.8 and l_val <= max(16.0, d * 0.4):
                group = [f, *plane_nbrs]
                for g in group:
                    consumed.add(g.face_id)
                groove_depth = max(1.5, min(plane_nbrs[0].width_mm or 3.0, 12.0))
                axis = f.axis_vector or (1.0, 0.0, 0.0)
                elements.append(
                    FeatureOrFaceItem(
                        element_id=next_id("GRV"),
                        name=f.name or f"Канавка Ø{d:.1f}x{l_val:.1f}",
                        cad_face_ids=[g.face_id for g in group],
                        category=ElementCategory.KTE_FEATURE,
                        geometry_type=GeometryType.GROOVE,
                        normal_vector=_normalize(axis),
                        setup_direction=quantize_setup_direction(axis),
                        area_mm2=round(sum(g.area_mm2 for g in group), 2),
                        removed_volume_mm3=round(math.pi * d * groove_depth * l_val, 2),
                        dimensions=DimensionsSpec(
                            diameter_mm=d,
                            length_or_depth_mm=l_val,
                            width_mm=groove_depth,
                            allowance_t_mm=groove_depth,
                        ),
                        pmi=_combine_pmi(group, default_ra, default_it, default_source),
                    )
                )
                continue

            # Иначе — отверстие (сквозное или глухое с дном Plane/Cone по вогнутому ребру)
            axis = f.axis_vector or (0.0, 0.0, 1.0)
            bottom_faces = [
                n for n in concave_nbrs
                if n.surface_type in ("Plane", "Cone")
                and abs(_dot(_normalize(n.axis_vector or n.normal_vector), _normalize(axis))) > 0.75
            ]
            # Если есть ровно одно вогнутое дно/конус (и не сквозная симметричная проточка)
            convex_planes = [
                graph.nodes[nid] for nid in graph.neighbors(f.face_id, "convex")
                if nid not in consumed and graph.nodes[nid].surface_type == "Plane"
            ]
            is_blind = len(bottom_faces) >= 1 and len(convex_planes) <= 1
            group = [f] + (bottom_faces[:1] if is_blind else [])
            for g in group:
                consumed.add(g.face_id)

            # Вход инструмента противоположен нормали дна или от ближайшего выпуклого торца
            approach = _normalize(axis)
            if bottom_faces:
                approach = _normalize(bottom_faces[0].normal_vector)
            elif convex_planes:
                approach = _normalize(convex_planes[0].normal_vector)

            vol = math.pi * ((d / 2.0) ** 2) * l_val
            hole_candidates.append(
                FeatureOrFaceItem(
                    element_id=next_id("HOL"),
                    name=f.name or f"{'Глухое' if is_blind else 'Сквозное'} отв. Ø{d:.1f}x{l_val:.1f}",
                    cad_face_ids=[g.face_id for g in group],
                    category=ElementCategory.KTE_FEATURE,
                    geometry_type=GeometryType.CYLINDER_INT_HOLE,
                    normal_vector=approach,
                    setup_direction=quantize_setup_direction(approach),
                    area_mm2=round(sum(g.area_mm2 for g in group), 2),
                    removed_volume_mm3=round(vol, 2),
                    dimensions=DimensionsSpec(
                        diameter_mm=d,
                        length_or_depth_mm=l_val,
                        allowance_t_mm=round(d / 2.0, 2),
                        is_blind=is_blind,
                    ),
                    pmi=_combine_pmi(group, default_ra, default_it, default_source),
                )
            )

        # Объединяем массивы одинаковых отверстий в одном направлении подхода
        grouped_holes: Dict[tuple, FeatureOrFaceItem] = {}
        for h in hole_candidates:
            key = (
                h.setup_direction,
                round(h.dimensions.diameter_mm or 0.0, 1),
                round(h.dimensions.length_or_depth_mm or 0.0, 1),
                h.dimensions.is_blind,
                round(h.pmi.roughness_ra_um, 3),
                h.pmi.it_grade,
            )
            if key not in grouped_holes:
                grouped_holes[key] = h
            else:
                existing = grouped_holes[key]
                existing.dimensions.identical_count += 1
                existing.cad_face_ids.extend(h.cad_face_ids)
                existing.area_mm2 = round(existing.area_mm2 + h.area_mm2, 2)
                existing.removed_volume_mm3 = round(existing.removed_volume_mm3 + h.removed_volume_mm3, 2)
        for h in grouped_holes.values():
            if h.dimensions.identical_count > 1:
                h.name = f"{h.name} (массив {h.dimensions.identical_count} шт.)"
            elements.append(h)

        # 3. Карманы (PKT) и Пазы (SLT) и Уступы (STP) из вогнутых компонент плоских + внутренних цилиндрических граней
        # Ищем плоские донья, у которых >= 3 вогнуто-смежных стенок -> Pocket
        for f in faces:
            if f.face_id in consumed or f.surface_type != "Plane":
                continue
            concave_nbrs = [graph.nodes[nid] for nid in graph.neighbors(f.face_id, "concave") if nid not in consumed]
            wall_planes = [n for n in concave_nbrs if n.surface_type == "Plane" and abs(_dot(_normalize(n.normal_vector), _normalize(f.normal_vector))) < 0.35]
            corner_fillets = [n for n in concave_nbrs if n.surface_type == "Cylinder" and n.is_internal]
            # Замкнутый карман: >= 3 плоских стенок или 2 полуокружности/скругления (глухой овальный карман/паз)
            if len(wall_planes) >= 3 or (len(wall_planes) == 2 and len(corner_fillets) >= 2):
                # Собираем все угловые скругления смежные со стенками
                extra_corners = []
                for wp in wall_planes:
                    for nid in graph.neighbors(wp.face_id, "smooth"):
                        cand = graph.nodes[nid]
                        if nid not in consumed and cand.surface_type == "Cylinder" and cand.is_internal and cand not in corner_fillets and cand not in extra_corners:
                            extra_corners.append(cand)
                group = [f] + wall_planes + corner_fillets + extra_corners
                for g in group:
                    consumed.add(g.face_id)

                bb = _group_bbox(group)
                dx, dy, dz = max(1.0, bb[1] - bb[0]), max(1.0, bb[3] - bb[2]), max(1.0, bb[5] - bb[4])
                nrm = _normalize(f.normal_vector)
                # Глубина вдоль нормали дна
                depth = abs(nrm[0]) * dx + abs(nrm[1]) * dy + abs(nrm[2]) * dz
                depth = max(depth, max((wp.length_mm or wp.width_mm or 0.0) for wp in wall_planes), 3.0)
                dims_2d = sorted([d for d in (dx, dy, dz) if abs(d - depth) > 1e-3] or [dx, dy])
                width = dims_2d[0] if len(dims_2d) >= 1 else math.sqrt(f.area_mm2)
                length = dims_2d[-1] if len(dims_2d) >= 2 else width
                radii = [max(0.1, (c.diameter_mm or 6.0) / 2.0) for c in corner_fillets + extra_corners]
                min_r = min(radii) if radii else 0.0

                is_slot_closed = len(wall_planes) == 2 and len(corner_fillets) >= 2 and length > width * 1.8
                gtype = GeometryType.SLOT if is_slot_closed else GeometryType.POCKET
                elements.append(
                    FeatureOrFaceItem(
                        element_id=next_id("SLT" if is_slot_closed else "PKT"),
                        name=f.name or (f"Паз закрытый {length:.1f}x{width:.1f}x{depth:.1f}" if is_slot_closed else f"Карман {length:.1f}x{width:.1f}x{depth:.1f}"),
                        cad_face_ids=[g.face_id for g in group],
                        category=ElementCategory.KTE_FEATURE,
                        geometry_type=gtype,
                        normal_vector=nrm,
                        setup_direction=quantize_setup_direction(nrm),
                        area_mm2=round(sum(g.area_mm2 for g in group), 2),
                        removed_volume_mm3=round(f.area_mm2 * depth, 2),
                        dimensions=DimensionsSpec(
                            length_or_depth_mm=round(depth, 2),
                            width_mm=round(width, 2),
                            diameter_mm=round(length, 2),
                            corner_radius_mm=round(min_r, 2),
                            allowance_t_mm=round(depth, 2),
                            is_blind=True,
                        ),
                        pmi=_combine_pmi(group, default_ra, default_it, default_source),
                    )
                )
            elif len(wall_planes) == 2 and _dot(_normalize(wall_planes[0].normal_vector), _normalize(wall_planes[1].normal_vector)) < -0.8:
                # П-образный открытый/сквозной паз
                group = [f] + wall_planes
                for g in group:
                    consumed.add(g.face_id)
                bb = _group_bbox(group)
                dx, dy, dz = max(1.0, bb[1] - bb[0]), max(1.0, bb[3] - bb[2]), max(1.0, bb[5] - bb[4])
                nrm = _normalize(f.normal_vector)
                depth = max(abs(nrm[0]) * dx + abs(nrm[1]) * dy + abs(nrm[2]) * dz, 2.0)
                width = min(max(1.0, min(dx, dy, dz)), max(f.width_mm or 10.0, 2.0))
                length = max(dx, dy, dz)
                elements.append(
                    FeatureOrFaceItem(
                        element_id=next_id("SLT"),
                        name=f.name or f"Паз открытый {length:.1f}x{width:.1f}x{depth:.1f}",
                        cad_face_ids=[g.face_id for g in group],
                        category=ElementCategory.KTE_FEATURE,
                        geometry_type=GeometryType.SLOT,
                        normal_vector=nrm,
                        setup_direction=quantize_setup_direction(nrm),
                        area_mm2=round(sum(g.area_mm2 for g in group), 2),
                        removed_volume_mm3=round(f.area_mm2 * depth, 2),
                        dimensions=DimensionsSpec(
                            diameter_mm=round(length, 2),
                            length_or_depth_mm=round(depth, 2),
                            width_mm=round(width, 2),
                            allowance_t_mm=round(depth, 2),
                            is_blind=False,
                        ),
                        pmi=_combine_pmi(group, default_ra, default_it, default_source),
                    )
                )
            elif not is_rotational_part and len(wall_planes) == 1:
                # Призматический уступ (L-профиль)
                group = [f, wall_planes[0]]
                for g in group:
                    consumed.add(g.face_id)
                nrm = _normalize(f.normal_vector)
                depth = max(wall_planes[0].length_mm or wall_planes[0].width_mm or 4.0, 1.5)
                elements.append(
                    FeatureOrFaceItem(
                        element_id=next_id("STP"),
                        name=f.name or f"Уступ h={depth:.1f}",
                        cad_face_ids=[g.face_id for g in group],
                        category=ElementCategory.KTE_FEATURE,
                        geometry_type=GeometryType.STEP,
                        normal_vector=nrm,
                        setup_direction=quantize_setup_direction(nrm),
                        area_mm2=round(sum(g.area_mm2 for g in group), 2),
                        removed_volume_mm3=round(f.area_mm2 * depth, 2),
                        dimensions=DimensionsSpec(
                            diameter_mm=round(max(f.length_mm or 20.0, math.sqrt(f.area_mm2)), 2),
                            length_or_depth_mm=round(depth, 2),
                            width_mm=round(f.width_mm or math.sqrt(f.area_mm2), 2),
                            allowance_t_mm=round(depth, 2),
                        ),
                        pmi=_combine_pmi(group, default_ra, default_it, default_source),
                    )
                )

        # 4. Фаски (CHM) и галтели (GRV/Fillet), а также оставшиеся элементарные грани
        for f in faces:
            if f.face_id in consumed:
                continue
            consumed.add(f.face_id)
            hint = (f.feature_hint or "").lower()
            st = f.surface_type

            if "chamfer" in hint or "фаск" in hint or (st == "Cone" and (f.length_mm or 99.0) <= 5.0 and f.area_mm2 < 600.0):
                d = f.diameter_mm or 20.0
                w = f.length_mm or f.width_mm or 1.5
                axis = f.axis_vector or f.normal_vector
                elements.append(
                    FeatureOrFaceItem(
                        element_id=next_id("CHM"),
                        name=f.name or f"Фаска {w:.1f}x45°",
                        cad_face_ids=[f.face_id],
                        category=ElementCategory.KTE_FEATURE,
                        geometry_type=GeometryType.CHAMFER,
                        normal_vector=_normalize(axis),
                        setup_direction=quantize_setup_direction(axis),
                        area_mm2=round(max(f.area_mm2, 1.0), 2),
                        removed_volume_mm3=round(max(f.area_mm2, 1.0) * w * 0.5, 2),
                        dimensions=DimensionsSpec(diameter_mm=d, length_or_depth_mm=w, width_mm=w, allowance_t_mm=w),
                        pmi=_combine_pmi([f], default_ra, default_it, default_source),
                    )
                )
            elif st == "Torus" or "fillet" in hint or "галтел" in hint:
                d = f.diameter_mm or 25.0
                r = f.width_mm or f.length_mm or 2.0
                axis = f.axis_vector or f.normal_vector
                elements.append(
                    FeatureOrFaceItem(
                        element_id=next_id("GRV"),
                        name=f.name or f"Галтель R{r:.1f}",
                        cad_face_ids=[f.face_id],
                        category=ElementCategory.KTE_FEATURE,
                        geometry_type=GeometryType.GROOVE,
                        normal_vector=_normalize(axis),
                        setup_direction=quantize_setup_direction(axis),
                        area_mm2=round(max(f.area_mm2, 1.0), 2),
                        removed_volume_mm3=round(max(f.area_mm2, 1.0) * r * 0.4, 2),
                        dimensions=DimensionsSpec(
                            diameter_mm=d,
                            length_or_depth_mm=r,
                            width_mm=r,
                            radius_mm=r,
                            corner_radius_mm=r,
                            allowance_t_mm=r,
                        ),
                        pmi=_combine_pmi([f], default_ra, default_it, default_source),
                    )
                )
            elif st == "Cylinder":
                d = f.diameter_mm or 40.0
                l_val = f.length_mm or max(f.area_mm2 / max(math.pi * d, 1.0), 5.0)
                z_allow = max(0.5, ((stock_diameter_mm - d) / 2.0) if (stock_diameter_mm and stock_diameter_mm > d) else 2.5)
                vol = math.pi * d * l_val * z_allow * 0.35
                nrm = _normalize(f.axis_vector or f.normal_vector)
                elements.append(
                    FeatureOrFaceItem(
                        element_id=next_id("CYL"),
                        name=f.name or f"Цилиндр Ø{d:.1f}x{l_val:.1f}",
                        cad_face_ids=[f.face_id],
                        category=ElementCategory.ELEMENTARY_FACE,
                        geometry_type=GeometryType.CYLINDER_EXT,
                        normal_vector=nrm,
                        setup_direction=quantize_setup_direction(nrm),
                        area_mm2=round(max(f.area_mm2, 1.0), 2),
                        removed_volume_mm3=round(max(vol, 0.0), 2),
                        dimensions=DimensionsSpec(diameter_mm=d, length_or_depth_mm=l_val, allowance_t_mm=round(z_allow, 2)),
                        pmi=_combine_pmi([f], default_ra, default_it, default_source),
                    )
                )
            elif st == "Cone":
                d = f.diameter_mm or 35.0
                l_val = f.length_mm or 20.0
                nrm = _normalize(f.axis_vector or f.normal_vector)
                elements.append(
                    FeatureOrFaceItem(
                        element_id=next_id("CON"),
                        name=f.name or f"Конус Ø{d:.1f}x{l_val:.1f}",
                        cad_face_ids=[f.face_id],
                        category=ElementCategory.ELEMENTARY_FACE,
                        geometry_type=GeometryType.CONE,
                        normal_vector=nrm,
                        setup_direction=quantize_setup_direction(nrm),
                        area_mm2=round(max(f.area_mm2, 1.0), 2),
                        removed_volume_mm3=round(max(f.area_mm2, 1.0) * 1.5, 2),
                        dimensions=DimensionsSpec(diameter_mm=d, length_or_depth_mm=l_val, allowance_t_mm=2.0),
                        pmi=_combine_pmi([f], default_ra, default_it, default_source),
                    )
                )
            elif st in ("Sphere", "BSplineSurface"):
                d = f.diameter_mm or math.sqrt(max(f.area_mm2, 1.0))
                l_val = f.length_mm or d
                nrm = _normalize(f.normal_vector)
                elements.append(
                    FeatureOrFaceItem(
                        element_id=next_id("SPH"),
                        name=f.name or f"Сложная поверхность ({st})",
                        cad_face_ids=[f.face_id],
                        category=ElementCategory.ELEMENTARY_FACE,
                        geometry_type=GeometryType.SPHERE,
                        normal_vector=nrm,
                        setup_direction=quantize_setup_direction(nrm),
                        area_mm2=round(max(f.area_mm2, 1.0), 2),
                        removed_volume_mm3=round(max(f.area_mm2, 1.0) * 1.5, 2),
                        dimensions=DimensionsSpec(diameter_mm=round(d, 2), length_or_depth_mm=round(l_val, 2), allowance_t_mm=1.5),
                        pmi=_combine_pmi([f], default_ra, default_it, default_source),
                    )
                )
            else:
                # Plane
                nrm = _normalize(f.normal_vector)
                d = f.diameter_mm or round(math.sqrt(max(f.area_mm2, 1.0)), 2)
                l_val = f.length_mm or d
                w_val = f.width_mm or d
                elements.append(
                    FeatureOrFaceItem(
                        element_id=next_id("PLN"),
                        name=f.name or f"Плоскость/торец (S={f.area_mm2:.0f} мм²)",
                        cad_face_ids=[f.face_id],
                        category=ElementCategory.ELEMENTARY_FACE,
                        geometry_type=GeometryType.PLANE,
                        normal_vector=nrm,
                        setup_direction=quantize_setup_direction(nrm),
                        area_mm2=round(max(f.area_mm2, 1.0), 2),
                        removed_volume_mm3=round(max(f.area_mm2, 1.0) * 2.0, 2),
                        dimensions=DimensionsSpec(
                            diameter_mm=round(d, 2),
                            length_or_depth_mm=round(l_val, 2),
                            width_mm=round(w_val, 2),
                            allowance_t_mm=2.0,
                        ),
                        pmi=_combine_pmi([f], default_ra, default_it, default_source),
                    )
                )

        return elements


__all__ = [
    "BRepFaceNode",
    "BRepEdgeLink",
    "AAGGraph",
    "AAGFeatureRecognizer",
    "quantize_setup_direction",
]

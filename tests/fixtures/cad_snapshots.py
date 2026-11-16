"""Тестовая фикстура 1: Тело вращения «Вал/Муфта» (B-Rep + AAG + PMI для NX и КОМПАС-3D)."""

from __future__ import annotations

from typing import Any, Dict


def build_shaft_coupling_snapshot_dict() -> Dict[str, Any]:
    """Синтетический B-Rep+AAG снимок ступенчатого вала с шпоночным пазом, резьбой, канавкой и отверстием."""
    return {
        "part_id": "VAL_MUFTA_01",
        "part_name": "Вал-муфта приводная М24",
        "cad_source": "Siemens_NX",
        "material_raw": "Сталь 40Х ГОСТ 4543-2016",
        "part_volume_mm3": 195000.0,
        "part_mass_kg": 1.53,
        "bounding_box_mm": {"L": 180.0, "W": 52.0, "H": 52.0, "D_max": 52.0},
        "batch_size_q": 10,
        "raw_tech_requirements": [
            "Неуказанная шероховатость поверхностей Ra 6.3",
            "Неуказанные предельные отклонения размеров H14, h14, ±IT14/2",
            "Закалка ТВЧ посадочных шеек 42..48 HRC",
            "Покрытие Хим.Окс.прм",
        ],
        "faces": [
            # 1: Левый торец (-Z)
            {
                "face_id": 101,
                "surface_type": "Plane",
                "area_mm2": 804.0,
                "normal_vector": [0.0, 0.0, -1.0],
                "diameter_mm": 32.0,
                "bounding_box_mm": [-16.0, 16.0, -16.0, 16.0, 0.0, 0.0],
            },
            # 2: Цилиндрическая резьбовая шейка M24x1.5 (L=25)
            {
                "face_id": 102,
                "surface_type": "Cylinder",
                "area_mm2": 1885.0,
                "normal_vector": [1.0, 0.0, 0.0],
                "axis_vector": [0.0, 0.0, 1.0],
                "diameter_mm": 24.0,
                "length_mm": 25.0,
                "feature_hint": "Thread",
                "pitch_mm": 1.5,
                "bounding_box_mm": [-12.0, 12.0, -12.0, 12.0, 0.0, 25.0],
            },
            # 3: Канавка выхода резьбы (дно + 2 торца 104, 105)
            {
                "face_id": 103,
                "surface_type": "Cylinder",
                "area_mm2": 320.0,
                "is_internal": True,
                "normal_vector": [1.0, 0.0, 0.0],
                "axis_vector": [0.0, 0.0, 1.0],
                "diameter_mm": 21.0,
                "length_mm": 4.0,
                "bounding_box_mm": [-10.5, 10.5, -10.5, 10.5, 25.0, 29.0],
            },
            {"face_id": 104, "surface_type": "Plane", "area_mm2": 150.0, "normal_vector": [0.0, 0.0, 1.0], "width_mm": 2.5},
            {"face_id": 105, "surface_type": "Plane", "area_mm2": 150.0, "normal_vector": [0.0, 0.0, -1.0], "width_mm": 2.5},
            # 4: Точная посадочная шейка под подшипник Ø35 k6 (L=55)
            {
                "face_id": 106,
                "surface_type": "Cylinder",
                "area_mm2": 6048.0,
                "normal_vector": [1.0, 0.0, 0.0],
                "axis_vector": [0.0, 0.0, 1.0],
                "diameter_mm": 35.0,
                "length_mm": 55.0,
                "bounding_box_mm": [-17.5, 17.5, -17.5, 17.5, 29.0, 84.0],
            },
            # 5: Главный бурт муфты Ø52 (L=60)
            {
                "face_id": 107,
                "surface_type": "Cylinder",
                "area_mm2": 9802.0,
                "normal_vector": [1.0, 0.0, 0.0],
                "axis_vector": [0.0, 0.0, 1.0],
                "diameter_mm": 52.0,
                "length_mm": 60.0,
                "bounding_box_mm": [-26.0, 26.0, -26.0, 26.0, 84.0, 144.0],
            },
            # 6: Шейка Ø32 (L=36)
            {
                "face_id": 108,
                "surface_type": "Cylinder",
                "area_mm2": 3619.0,
                "normal_vector": [1.0, 0.0, 0.0],
                "axis_vector": [0.0, 0.0, 1.0],
                "diameter_mm": 32.0,
                "length_mm": 36.0,
                "bounding_box_mm": [-16.0, 16.0, -16.0, 16.0, 144.0, 180.0],
            },
            # 7: Фаска 2x45
            {
                "face_id": 109,
                "surface_type": "Cone",
                "area_mm2": 220.0,
                "normal_vector": [0.7, 0.0, 0.7],
                "axis_vector": [0.0, 0.0, 1.0],
                "diameter_mm": 32.0,
                "length_mm": 2.0,
                "width_mm": 2.0,
                "feature_hint": "Chamfer",
            },
            # 8: Правый торец (+Z)
            {
                "face_id": 110,
                "surface_type": "Plane",
                "area_mm2": 804.0,
                "normal_vector": [0.0, 0.0, 1.0],
                "diameter_mm": 32.0,
                "bounding_box_mm": [-16.0, 16.0, -16.0, 16.0, 180.0, 180.0],
            },
            # 9: Глухое осевое отверстие Ø10x45 (L/D = 4.5)
            {
                "face_id": 111,
                "surface_type": "Cylinder",
                "area_mm2": 1413.0,
                "is_internal": True,
                "normal_vector": [0.0, 0.0, 1.0],
                "axis_vector": [0.0, 0.0, 1.0],
                "diameter_mm": 10.0,
                "length_mm": 45.0,
            },
            {"face_id": 112, "surface_type": "Cone", "area_mm2": 95.0, "is_internal": True, "normal_vector": [0.0, 0.0, 1.0], "axis_vector": [0.0, 0.0, 1.0]},
            # 10: Шпоночный паз на главном бурте (+Y): дно + 2 стенки
            {"face_id": 113, "surface_type": "Plane", "area_mm2": 450.0, "normal_vector": [0.0, 1.0, 0.0], "width_mm": 10.0, "bounding_box_mm": [-5.0, 5.0, 21.0, 21.0, 92.0, 137.0]},
            {"face_id": 114, "surface_type": "Plane", "area_mm2": 225.0, "normal_vector": [1.0, 0.0, 0.0], "bounding_box_mm": [-5.0, -5.0, 21.0, 26.0, 92.0, 137.0]},
            {"face_id": 115, "surface_type": "Plane", "area_mm2": 225.0, "normal_vector": [-1.0, 0.0, 0.0], "bounding_box_mm": [5.0, 5.0, 21.0, 26.0, 92.0, 137.0]},
        ],
        "edges": [
            {"face_a_id": 103, "face_b_id": 104, "edge_convexity": "concave"},
            {"face_a_id": 103, "face_b_id": 105, "edge_convexity": "concave"},
            {"face_a_id": 111, "face_b_id": 112, "edge_convexity": "concave"},
            {"face_a_id": 113, "face_b_id": 114, "edge_convexity": "concave"},
            {"face_a_id": 113, "face_b_id": 115, "edge_convexity": "concave"},
        ],
        "pmi_bindings": [
            {"face_ids": [106], "roughness_text": "Ra 0.8", "tolerance_text": "k6", "nominal_mm": 35.0, "fcf_symbol": "Runout", "fcf_value_mm": 0.015},
            {"face_ids": [108], "roughness_text": "Rz 20", "tolerance_text": "H11", "nominal_mm": 32.0},
            {"face_ids": [113, 114, 115], "roughness_text": "Ra 3.2", "tolerance_text": "N9", "nominal_mm": 10.0},
        ],
    }


def build_housing_cover_snapshot_dict() -> Dict[str, Any]:
    """Синтетический B-Rep+AAG снимок корпусной детали «Крышка/Корпус» (КОМПАС-3D / 3D PMI)."""
    return {
        "part_id": "KORPUS_KRYSHKA_02",
        "part_name": "Корпус редуктора крышка",
        "cad_source": "Kompas_3D",
        "material_raw": "Д16Т ГОСТ 4784-2019",
        "part_volume_mm3": 420000.0,
        "part_mass_kg": 1.17,
        "bounding_box_mm": {"L": 160.0, "W": 120.0, "H": 50.0, "D_max": 160.0},
        "blank_type_hint": "PR_Plate",
        "batch_size_q": 25,
        "raw_tech_requirements": [
            "Неуказанная шероховатость Rz 40",
            "Неуказанные предельные отклонения H14, h14",
        ],
        "faces": [
            # Верхняя плоскость (+Z)
            {"face_id": 201, "surface_type": "Plane", "area_mm2": 14000.0, "normal_vector": [0.0, 0.0, 1.0], "length_mm": 160.0, "width_mm": 120.0},
            # Нижняя привалочная плоскость (-Z)
            {"face_id": 202, "surface_type": "Plane", "area_mm2": 18000.0, "normal_vector": [0.0, 0.0, -1.0], "length_mm": 160.0, "width_mm": 120.0},
            # Карман 80x60x28 с малым радиусом скругления угла R3 (H/R = 28/3 = 9.33 > 6 -> DFM Critical!)
            {"face_id": 203, "surface_type": "Plane", "area_mm2": 4800.0, "normal_vector": [0.0, 0.0, 1.0], "bounding_box_mm": [-40.0, 40.0, -30.0, 30.0, 22.0, 22.0]},
            {"face_id": 204, "surface_type": "Plane", "area_mm2": 2240.0, "normal_vector": [1.0, 0.0, 0.0], "bounding_box_mm": [-40.0, -40.0, -30.0, 30.0, 22.0, 50.0]},
            {"face_id": 205, "surface_type": "Plane", "area_mm2": 2240.0, "normal_vector": [-1.0, 0.0, 0.0], "bounding_box_mm": [40.0, 40.0, -30.0, 30.0, 22.0, 50.0]},
            {"face_id": 206, "surface_type": "Plane", "area_mm2": 1680.0, "normal_vector": [0.0, 1.0, 0.0], "bounding_box_mm": [-40.0, 40.0, -30.0, -30.0, 22.0, 50.0]},
            {"face_id": 207, "surface_type": "Plane", "area_mm2": 1680.0, "normal_vector": [0.0, -1.0, 0.0], "bounding_box_mm": [-40.0, 40.0, 30.0, 30.0, 22.0, 50.0]},
            {"face_id": 208, "surface_type": "Cylinder", "area_mm2": 260.0, "is_internal": True, "normal_vector": [0.7, 0.7, 0.0], "diameter_mm": 6.0, "length_mm": 28.0, "bounding_box_mm": [-40.0, -34.0, -30.0, -24.0, 22.0, 50.0]},
            # Сквозной П-паз со стороны +X
            {"face_id": 209, "surface_type": "Plane", "area_mm2": 900.0, "normal_vector": [1.0, 0.0, 0.0], "width_mm": 12.0, "bounding_box_mm": [72.0, 72.0, -6.0, 6.0, 0.0, 50.0]},
            {"face_id": 210, "surface_type": "Plane", "area_mm2": 400.0, "normal_vector": [0.0, 1.0, 0.0], "bounding_box_mm": [72.0, 80.0, -6.0, -6.0, 0.0, 50.0]},
            {"face_id": 211, "surface_type": "Plane", "area_mm2": 400.0, "normal_vector": [0.0, -1.0, 0.0], "bounding_box_mm": [72.0, 80.0, 6.0, 6.0, 0.0, 50.0]},
            # Массив 4 крепежных сквозных отверстий Ø8.0x25 (+Z)
            {"face_id": 212, "surface_type": "Cylinder", "area_mm2": 628.0, "is_internal": True, "normal_vector": [0.0, 0.0, 1.0], "axis_vector": [0.0, 0.0, 1.0], "diameter_mm": 8.0, "length_mm": 25.0},
            {"face_id": 213, "surface_type": "Cylinder", "area_mm2": 628.0, "is_internal": True, "normal_vector": [0.0, 0.0, 1.0], "axis_vector": [0.0, 0.0, 1.0], "diameter_mm": 8.0, "length_mm": 25.0},
            {"face_id": 214, "surface_type": "Cylinder", "area_mm2": 628.0, "is_internal": True, "normal_vector": [0.0, 0.0, 1.0], "axis_vector": [0.0, 0.0, 1.0], "diameter_mm": 8.0, "length_mm": 25.0},
            {"face_id": 215, "surface_type": "Cylinder", "area_mm2": 628.0, "is_internal": True, "normal_vector": [0.0, 0.0, 1.0], "axis_vector": [0.0, 0.0, 1.0], "diameter_mm": 8.0, "length_mm": 25.0},
            # Глубокое отверстие под смазку Ø8.5x52 со стороны -Y (L/D = 6.12 > 5 и близкий диаметр к 8.0!)
            {"face_id": 216, "surface_type": "Cylinder", "area_mm2": 1388.0, "is_internal": True, "normal_vector": [0.0, -1.0, 0.0], "axis_vector": [0.0, -1.0, 0.0], "diameter_mm": 8.5, "length_mm": 52.0},
            {"face_id": 217, "surface_type": "Cone", "area_mm2": 60.0, "is_internal": True, "normal_vector": [0.0, -1.0, 0.0], "axis_vector": [0.0, -1.0, 0.0]},
            # Точное центральное расточенное отверстие под подшипник Ø42 H7 (+Z)
            {"face_id": 218, "surface_type": "Cylinder", "area_mm2": 3298.0, "is_internal": True, "normal_vector": [0.0, 0.0, 1.0], "axis_vector": [0.0, 0.0, 1.0], "diameter_mm": 42.0, "length_mm": 25.0},
        ],
        "edges": [
            {"face_a_id": 203, "face_b_id": 204, "edge_convexity": "concave"},
            {"face_a_id": 203, "face_b_id": 205, "edge_convexity": "concave"},
            {"face_a_id": 203, "face_b_id": 206, "edge_convexity": "concave"},
            {"face_a_id": 203, "face_b_id": 207, "edge_convexity": "concave"},
            {"face_a_id": 203, "face_b_id": 208, "edge_convexity": "concave"},
            {"face_a_id": 209, "face_b_id": 210, "edge_convexity": "concave"},
            {"face_a_id": 209, "face_b_id": 211, "edge_convexity": "concave"},
            {"face_a_id": 216, "face_b_id": 217, "edge_convexity": "concave"},
        ],
        "pmi_bindings": [
            {"face_ids": [202], "roughness_text": "Ra 1.6", "tolerance_text": "+0.025/0", "nominal_mm": 50.0, "fcf_symbol": "Perpendicularity", "fcf_value_mm": 0.03},
            {"face_ids": [218], "roughness_text": "Ra 1.25", "tolerance_text": "H7", "nominal_mm": 42.0, "fcf_symbol": "Concentricity", "fcf_value_mm": 0.02},
        ],
    }

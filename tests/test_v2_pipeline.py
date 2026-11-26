"""Комплексный интеграционный и модульный pytest-набор для Ingro Master Specification v2.0."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

from ingro_dfm.cad_addons.kompas_addon.kompas_brep_extractor import KompasBRepExtractor
from ingro_dfm.cad_addons.nx_addon.nx_brep_extractor import NXBRepExtractor
from ingro_dfm.calc_engine.hybrid_orchestrator import calculate_passport
from ingro_dfm.calibration.cam_dataset_loader import CalibrationSQLiteStore, CalibrationSample, load_cam_csv, load_cam_xlsx
from ingro_dfm.calibration.ridge_calibrator import fit_constrained_ridge, rollback_weights
from ingro_dfm.classifier.tech_coder_10 import classify_passport
from ingro_dfm.core_schema.migration_v1_to_v2 import migrate_v1_file, migrate_v1_to_v2
from ingro_dfm.core_schema.part_passport import GeomToleranceType, GeometryType, PMISource, PartPassport
from ingro_dfm.core_schema.pmi_utils import (
    it_from_tolerance_um,
    parse_roughness_text,
    parse_tech_requirements,
    parse_tolerance_text,
    rz_to_ra,
)
from ingro_dfm.database.loader import DATABASE_DIR, load_regression_weights
from ingro_dfm.dfm_engine.cost_drivers_analyzer import analyze_cost_drivers
from ingro_dfm.dfm_engine.dfm_rules_kb import evaluate_dfm
from ingro_dfm.dfm_engine.what_if_simulator import simulate_parameter_change
from ingro_dfm.tests.fixtures.cad_snapshots import (
    build_housing_cover_snapshot_dict,
    build_shaft_coupling_snapshot_dict,
)
from ingro_dfm.ui_reporting.inspector_app import IngroInspectorState
from ingro_dfm.ui_reporting.report_exporter import export_all_reports


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def shaft_passport(tmp_path: Path) -> PartPassport:
    snap_path = tmp_path / "shaft_snap.json"
    snap_path.write_text(json.dumps(build_shaft_coupling_snapshot_dict(), ensure_ascii=False), encoding="utf-8")
    return NXBRepExtractor().extract_passport(snapshot_json_path=snap_path)


@pytest.fixture
def housing_passport(tmp_path: Path) -> PartPassport:
    snap_path = tmp_path / "housing_snap.json"
    snap_path.write_text(json.dumps(build_housing_cover_snapshot_dict(), ensure_ascii=False), encoding="utf-8")
    return KompasBRepExtractor().extract_passport(snapshot_json_path=snap_path)


def test_pmi_and_tt_parsing() -> None:
    assert rz_to_ra(20.0) == pytest.approx(5.0)
    assert parse_roughness_text("Rz 6.3") == pytest.approx(1.25)
    assert parse_roughness_text("Ra 1.6") == pytest.approx(1.6)

    it_h7, tol_um = parse_tolerance_text("H7", nominal_mm=42.0)
    assert it_h7 == 7
    assert tol_um and tol_um > 20.0

    it_num, tol_num = parse_tolerance_text("+0.025 / 0", nominal_mm=50.0)
    assert it_num in (6, 7)
    assert tol_num == pytest.approx(25.0)
    assert it_from_tolerance_um(30.0, 21.0) == 7

    tt = parse_tech_requirements([
        "Неуказанная шероховатость Ra 6.3",
        "H14, h14, ±IT14/2",
        "Закалка ТВЧ 45..50 HRC",
        "Покрытие Ц9.хр",
    ])
    assert tt.default_ra_um == pytest.approx(6.3)
    assert tt.default_it_grade == 14
    assert tt.has_heat_treatment is True
    assert tt.has_coating is True
    assert "HRC" in (tt.hardness_hb_or_hrc or "")


def test_migration_v1_to_v2_from_deployed_test_passport() -> None:
    v1_path = REPO_ROOT / "test_passport.json"
    raw = json.loads(v1_path.read_text(encoding="utf-8-sig"))
    v2 = migrate_v1_to_v2(raw)
    assert v2.passport_version == "2.0"
    assert v2.is_rotational_part is True
    assert len(v2.elements) == len(raw["surfaces"])
    calc = calculate_passport(v2)
    assert calc.hybrid_totals.t_shk_total_min > 0
    assert calc.cbnt_totals.t_shk_total_min > 0
    assert calc.regression_totals.t_shk_total_min > 0


def test_shaft_coupling_nx_aag_tech_code_and_dual_contour(shaft_passport: PartPassport) -> None:
    assert shaft_passport.is_rotational_part is True
    assert shaft_passport.has_heat_treatment is True
    assert shaft_passport.has_coating is True

    geom_types = {e.geometry_type for e in shaft_passport.elements}
    assert GeometryType.THREAD in geom_types
    assert GeometryType.GROOVE in geom_types
    assert GeometryType.CYLINDER_INT_HOLE in geom_types
    assert GeometryType.SLOT in geom_types
    assert GeometryType.CHAMFER in geom_types

    # Проверка глухого отверстия (L=45, D=10 -> L/D = 4.5 > 3 -> добавляется Центрование!)
    hole = next(e for e in shaft_passport.elements if e.geometry_type == GeometryType.CYLINDER_INT_HOLE)
    assert hole.dimensions.is_blind is True
    assert hole.classification.assigned_transitions[0] == "Центрование"

    # Проверка 10-уровневого кода формата L1.L2.L3.L4.L5-L6.L7.L8.L9.L10
    cyl_k6 = next(e for e in shaft_passport.elements if e.geometry_type == GeometryType.CYLINDER_EXT and e.pmi.it_grade == 6)
    code = cyl_k6.classification.tech_code_10 or ""
    assert code.startswith("M2.ST_A.G2.PR.HT2-FACE.CYL.IT_B4.RA_B4.GT_FRM")

    calc = calculate_passport(shaft_passport)
    # У вала-муфты как минимум токарный + фрезерный (шпонка) + шлифовальный установаы
    assert calc.setups_count >= 3
    assert calc.cbnt_totals.t_shk_total_min > calc.cbnt_totals.t_osn_total_min
    assert calc.regression_totals.t_shk_total_min > 0
    assert calc.hybrid_totals.t_norm_hours == pytest.approx(calc.hybrid_totals.t_shk_total_min / 60.0, abs=0.002)

    # What-If: ослабление шейки k6 с Ra 0.8 / IT6 до Ra 3.2 / IT11 исключает шлифование и сокращает T_шк
    wf = simulate_parameter_change(shaft_passport, cyl_k6.element_id, new_ra=3.2, new_it=11)
    assert wf.new_t_shk_min < wf.old_t_shk_min
    assert wf.delta_min < 0


def test_housing_cover_kompas_aag_setups_and_dfm(housing_passport: PartPassport) -> None:
    assert housing_passport.is_rotational_part is False

    geom_types = {e.geometry_type for e in housing_passport.elements}
    assert GeometryType.POCKET in geom_types
    assert GeometryType.SLOT in geom_types
    assert GeometryType.CYLINDER_INT_HOLE in geom_types

    # Проверка объединения массива 4 одинаковых отверстий Ø8
    array_hole = next(e for e in housing_passport.elements if e.geometry_type == GeometryType.CYLINDER_INT_HOLE and e.dimensions.identical_count == 4)
    assert array_hole.dimensions.identical_count == 4

    # Проверка каскадного наследования ТТ (Rz 40 -> Ra 10.0) на свободных плоскостях
    inherited = [e for e in housing_passport.elements if e.pmi.source == PMISource.INHERITED_TT]
    assert inherited and inherited[0].pmi.roughness_ra_um == pytest.approx(10.0)

    calc = calculate_passport(housing_passport)
    # Должно быть >= 3 уникальных направлений подхода (+Z, -Z, +X, -Y)
    assert calc.setups_count >= 3

    dfm = evaluate_dfm(housing_passport, calc)
    rule_ids = {f.rule_id for f in dfm.findings}
    assert "DFM_03_POCKET_H_R_RATIO" in rule_ids  # H=28, R=3 -> 9.33 > 6!
    assert "DFM_02_DEEP_HOLE" in rule_ids         # D=8.5, L=52 -> L/D = 6.12 > 5!
    assert "DFM_05_UNIFY_HOLES" in rule_ids       # Ø8.0 vs Ø8.5
    assert dfm.is_manufacturable is False

    pkt = next(e for e in housing_passport.elements if e.geometry_type == GeometryType.POCKET)
    assert dfm.traffic_lights[pkt.element_id].color == "red"
    assert dfm.traffic_lights[inherited[0].element_id].color == "yellow"


def test_ridge_calibrator_physical_bounds_and_rollback(tmp_path: Path) -> None:
    # Копируем regression_weights.json во временный каталог, чтобы тест не мусорил в рабочей базе
    tmp_weights = tmp_path / "regression_weights.json"
    shutil.copyfile(DATABASE_DIR / "regression_weights.json", tmp_weights)

    # Генерируем синтетический CAM CSV dataset из 16 точек с известным степенным законом
    csv_path = tmp_path / "cam_samples.csv"
    lines = ["tech_code_10,S_mm2,V_mm3,Ra_um,IT_grade,cam_machining_time_min,material_group"]
    for s_area in (800.0, 2200.0, 5000.0, 9500.0):
        for ra, it in ((6.3, 12), (3.2, 10), (1.6, 8), (0.8, 7)):
            v_vol = s_area * 1.5
            t_finish = 0.011 * (s_area ** 0.76) * (ra ** -0.27) * (it ** -0.38)
            t_cam = (1.15 * v_vol / 42000.0) + t_finish
            lines.append(f"M2.ST_C.G2.PR.HT0-FACE.CYL.IT_B3.RA_B3.GT_NONE,{s_area},{v_vol},{ra},{it},{t_cam:.4f},ST_Carbon")
    csv_path.write_text("\n".join(lines), encoding="utf-8")

    samples = load_cam_csv(csv_path)
    assert len(samples) == 16

    report = fit_constrained_ridge(samples, weight_key="CYL.TEST", alpha=1.0, weights_path=tmp_weights)
    assert report.x1 > 0
    assert report.x2 < 0
    assert report.x3 < 0
    assert report.r2_log_score > 0.90

    # Сохранение в SQLite
    store = CalibrationSQLiteStore(tmp_path / "cal.sqlite")
    assert store.add_samples(samples) == 16
    assert len(store.fetch_samples("CYL")) == 16

    # Проверка Rollback
    reverted_ver = rollback_weights(weights_path=tmp_weights)
    assert reverted_ver == report.previous_version
    after_rollback = load_regression_weights(tmp_weights)
    assert "CYL.TEST" not in after_rollback["weights"]


def test_inspector_override_and_exports(housing_passport: PartPassport, tmp_path: Path) -> None:
    state = IngroInspectorState(housing_passport, calibration_db_path=tmp_path / "fb.sqlite")
    drivers = analyze_cost_drivers(state.calc_result)
    assert drivers

    # Переопределение PMI в 1 клик (ЖЕЛТ -> ЗЕЛЕН/override)
    plane_elem = next(e for e in state.passport.elements if e.geometry_type == GeometryType.PLANE and e.pmi.source == PMISource.INHERITED_TT)
    state.override_element_pmi(plane_elem.element_id, new_ra=3.2, new_it=11)
    updated_elem = next(e for e in state.passport.elements if e.element_id == plane_elem.element_id)
    assert updated_elem.pmi.source == PMISource.USER_OVERRIDE

    sample = state.save_production_feedback(plane_elem.element_id, actual_time_min=3.45)
    assert sample.cam_machining_time_min == pytest.approx(3.45)

    paths = export_all_reports(
        state.passport,
        state.calc_result,
        state.dfm_assessment,
        drivers,
        out_dir=tmp_path / "out",
    )
    assert paths["json"].is_file() and paths["json"].stat().st_size > 200
    assert paths["xlsx"].is_file() and paths["xlsx"].stat().st_size > 2000
    assert paths["pdf"].is_file() and paths["pdf"].stat().st_size > 1000


def test_no_grinding_double_counting_between_setups(shaft_passport: PartPassport) -> None:
    calc = calculate_passport(shaft_passport)
    cyl_k6 = next(
        e for e in shaft_passport.elements
        if e.geometry_type == GeometryType.CYLINDER_EXT and e.pmi.it_grade == 6
    )
    k6_details = [d for d in calc.elements if d.element_id == cyl_k6.element_id]
    turn_det = next(d for d in k6_details if d.operation_kind == "turning")
    grind_det = next(d for d in k6_details if d.operation_kind == "grinding")

    # Контур 1: К.58 (шлифование) присутствует только в grinding-операции, не в лезвийной turning
    assert not any("К.58" in c for c in turn_det.cbnt_cards)
    assert any("К.58" in c for c in grind_det.cbnt_cards)

    # Контур 2: черновой MRR снимается в turning, а чистовая составляющая разделена 65% / 35% без 100% дублирования
    assert turn_det.reg_t_rough_mrr_min > grind_det.reg_t_rough_mrr_min
    assert grind_det.reg_t_finish_min == pytest.approx(turn_det.reg_t_finish_min * (0.35 / 0.65), rel=0.05)


def test_xlsx_loader_and_noisy_constrained_ridge(tmp_path: Path) -> None:
    tmp_weights = tmp_path / "regression_weights.json"
    shutil.copyfile(DATABASE_DIR / "regression_weights.json", tmp_weights)

    xlsx_path = tmp_path / "cam_noisy.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["tech_code_10", "S_mm2", "V_mm3", "Ra_um", "IT_grade", "cam_machining_time_min", "material_group"])
    # Зашумленная малая выборка с обратной корреляцией по S/Ra, чтобы сработал ConstrainedL2
    noisy_rows = [
        ("M2.ST_C.G2.PR.HT0-FACE.CYL.IT_B3.RA_B3.GT_NONE", 1200.0, 0.0, 0.8, 7, 1.2, "ST_Carbon"),
        ("M2.ST_C.G2.PR.HT0-FACE.CYL.IT_B3.RA_B3.GT_NONE", 3500.0, 0.0, 1.6, 8, 2.8, "ST_Carbon"),
        ("M2.ST_C.G2.PR.HT0-FACE.CYL.IT_B3.RA_B3.GT_NONE", 6000.0, 0.0, 3.2, 10, 4.9, "ST_Carbon"),
        ("M2.ST_C.G2.PR.HT0-FACE.CYL.IT_B3.RA_B3.GT_NONE", 9000.0, 0.0, 6.3, 12, 0.9, "ST_Carbon"),
        ("M2.ST_C.G2.PR.HT0-FACE.CYL.IT_B3.RA_B3.GT_NONE", 4200.0, 0.0, 12.5, 14, 5.5, "ST_Carbon"),
    ]
    for r in noisy_rows:
        ws.append(list(r))
    wb.save(xlsx_path)

    samples = load_cam_xlsx(xlsx_path)
    assert len(samples) == 5

    report = fit_constrained_ridge(samples, weight_key="CYL.NOISY", alpha=1.0, weights_path=tmp_weights)
    assert report.method_used == "sklearn.Ridge+ConstrainedL2"
    assert report.x1 > 0
    assert report.x2 < 0
    assert report.x3 < 0


def test_migrate_v1_file_and_cli_smoke(tmp_path: Path) -> None:
    v1_path = REPO_ROOT / "test_passport.json"
    v2 = migrate_v1_file(v1_path)
    assert v2.passport_version == "2.0"

    shaft_snap = tmp_path / "shaft_snap.json"
    housing_snap = tmp_path / "housing_snap.json"
    shaft_snap.write_text(json.dumps(build_shaft_coupling_snapshot_dict(), ensure_ascii=False), encoding="utf-8")
    housing_snap.write_text(json.dumps(build_housing_cover_snapshot_dict(), ensure_ascii=False), encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT.parent), *filter(None, [env.get("PYTHONPATH", "")])]
    )

    nx_out = tmp_path / "nx_out"
    res_nx = subprocess.run(
        [sys.executable, "-m", "ingro_dfm.cad_addons.nx_addon.nx_ui_dialog", "--snapshot", str(shaft_snap), "--out-dir", str(nx_out)],
        env=env, capture_output=True, text=True, encoding="utf-8", check=True,
    )
    assert "[NX Addon]" in res_nx.stdout
    assert list(nx_out.glob("*.xlsx"))

    kompas_out = tmp_path / "kompas_out"
    res_kp = subprocess.run(
        [sys.executable, "-m", "ingro_dfm.cad_addons.kompas_addon.kompas_ui_panel", "--snapshot", str(housing_snap), "--cnc", "--out-dir", str(kompas_out)],
        env=env, capture_output=True, text=True, encoding="utf-8", check=True,
    )
    assert "[KOMPAS Addon]" in res_kp.stdout
    assert list(kompas_out.glob("*.pdf"))

    ed_out = tmp_path / "ed_out"
    res_ed = subprocess.run(
        [sys.executable, "-m", "ingro_dfm.ui.passport_editor", str(v1_path), "--v2", "--export-dir", str(ed_out)],
        env=env, capture_output=True, text=True, encoding="utf-8", check=True,
    )
    assert "[Ingro v2.0]" in res_ed.stdout
    assert list(ed_out.glob("*.json"))

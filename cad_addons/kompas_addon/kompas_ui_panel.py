"""Запуск панели / конвейера анализа КОМПАС-3D API7 для проекта Ingro v2.0."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from ingro_dfm.cad_addons.kompas_addon.kompas_brep_extractor import KompasBRepExtractor
from ingro_dfm.cad_addons.kompas_addon.kompas_pmi_extractor import KompasPMIExtractor
from ingro_dfm.calc_engine.hybrid_orchestrator import HybridCalculationResult, calculate_passport
from ingro_dfm.dfm_engine.cost_drivers_analyzer import analyze_cost_drivers
from ingro_dfm.dfm_engine.dfm_rules_kb import DFMAssessment, evaluate_dfm


def run_kompas_pipeline(
    snapshot_json: Optional[Path] = None,
    use_cnc: bool = False,
) -> tuple[HybridCalculationResult, DFMAssessment]:
    """Запускает полный конвейер КОМПАС-3D (COM API7 либо JSON-снимок) -> расчет -> DFM."""
    brep = KompasBRepExtractor()
    if snapshot_json is not None:
        passport = brep.extract_passport(snapshot_json_path=snapshot_json)
    else:
        import win32com.client  # type: ignore

        app = win32com.client.GetActiveObject("Kompas.Application.7")
        doc3d = app.ActiveDocument
        pmi_ext = KompasPMIExtractor()
        bindings, notes = pmi_ext.extract(doc3d)
        passport = brep.extract_passport(doc3d=doc3d, pmi_bindings=bindings, raw_tt=notes)

    calc = calculate_passport(passport, use_cnc=use_cnc)
    dfm = evaluate_dfm(passport, calc)
    return calc, dfm


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingro v2.0 KOMPAS-3D Addon Runner")
    parser.add_argument("--snapshot", type=Path, default=None, help="Путь к JSON-снимок модели КОМПАС-3D")
    parser.add_argument("--cnc", action="store_true", help="Использовать станок с ЧПУ")
    parser.add_argument("--out-dir", type=Path, default=None, help="Каталог для сохранения ведомостей XLSX/PDF/JSON")
    args = parser.parse_args()

    calc, dfm = run_kompas_pipeline(snapshot_json=args.snapshot, use_cnc=args.cnc)
    drivers = analyze_cost_drivers(calc)
    print(f"[KOMPAS Addon] {calc.part_name}: T_шк = {calc.hybrid_totals.t_shk_total_min:.2f} мин ({calc.hybrid_totals.t_norm_hours:.3f} н/ч), КИМ={calc.kim_ratio:.3f}")
    if args.out_dir and args.snapshot:
        from ingro_dfm.ui_reporting.report_exporter import export_all_reports
        passport = KompasBRepExtractor().extract_passport(snapshot_json_path=args.snapshot)
        export_all_reports(passport, calc, dfm, drivers, args.out_dir)


if __name__ == "__main__":
    main()

"""Точка входа диалога NX UI / CLI для запуска расчета Ingro v2.0 по модели Siemens NX."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from ingro_dfm.cad_addons.nx_addon.nx_brep_extractor import NXBRepExtractor
from ingro_dfm.cad_addons.nx_addon.nx_pmi_extractor import NXPMIExtractor
from ingro_dfm.calc_engine.hybrid_orchestrator import HybridCalculationResult, calculate_passport
from ingro_dfm.dfm_engine.cost_drivers_analyzer import analyze_cost_drivers
from ingro_dfm.dfm_engine.dfm_rules_kb import DFMAssessment, evaluate_dfm


def run_nx_pipeline(
    snapshot_json: Optional[Path] = None,
    use_cnc: bool = False,
) -> tuple[HybridCalculationResult, DFMAssessment]:
    """Запускает полный конвейер извлечения (живой NX либо снимок JSON) -> расчет -> DFM."""
    brep = NXBRepExtractor()
    if snapshot_json is not None:
        passport = brep.extract_passport(snapshot_json_path=snapshot_json)
    else:
        pmi_ext = NXPMIExtractor()
        try:
            import NXOpen  # type: ignore
            part = NXOpen.Session.GetSession().Parts.Work
        except Exception as exc:
            raise RuntimeError("Нет активного подключения к NXOpen; передайте --snapshot <file.json>") from exc
        bindings, notes = pmi_ext.extract(part)
        passport = brep.extract_passport(part=part, pmi_bindings=bindings, raw_tt=notes)

    calc = calculate_passport(passport, use_cnc=use_cnc)
    dfm = evaluate_dfm(passport, calc)
    return calc, dfm


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingro v2.0 NX Addon Runner")
    parser.add_argument("--snapshot", type=Path, default=None, help="Путь к JSON-снимок B-Rep/PMI (для автономного запуска)")
    parser.add_argument("--cnc", action="store_true", help="Использовать станок с ЧПУ")
    parser.add_argument("--out-dir", type=Path, default=None, help="Каталог для экспорта JSON/XLSX/PDF отчета")
    args = parser.parse_args()

    calc, dfm = run_nx_pipeline(snapshot_json=args.snapshot, use_cnc=args.cnc)
    drivers = analyze_cost_drivers(calc)
    print(f"[NX Addon] {calc.part_name}: T_шк = {calc.hybrid_totals.t_shk_total_min:.2f} мин ({calc.hybrid_totals.t_norm_hours:.3f} н/ч), КИМ={calc.kim_ratio:.3f}")
    print(f"  ЦБНТ: {calc.cbnt_totals.t_shk_total_min:.2f} мин | Регрессия+MRR: {calc.regression_totals.t_shk_total_min:.2f} мин | Расхождение={calc.contours_diff_percent:.1f}%")
    if args.out_dir:
        from ingro_dfm.ui_reporting.report_exporter import export_all_reports
        brep = NXBRepExtractor()
        passport = brep.extract_passport(snapshot_json_path=args.snapshot) if args.snapshot else None
        if passport is not None:
            export_all_reports(passport, calc, dfm, drivers, args.out_dir)


if __name__ == "__main__":
    main()

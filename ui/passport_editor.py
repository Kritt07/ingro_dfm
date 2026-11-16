"""Passport editor UI (console based placeholder).

In a full Antigravity UI this module would provide an interactive widget that
shows the extracted surfaces, highlights entries with ``confidence == 'default'``
and allows the user to edit fields such as ``Ra_um``, ``IT`` and the batch
size ``batch_size_q``.

For this prototype we implement a very small command‑line helper that prints a
summary and accepts optional JSON patches via the ``--patch`` argument.
"""

import json
import argparse
from pathlib import Path
from typing import Dict, Any

def load_passport(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)

def apply_patch(passport: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge *patch* into *passport*.
    """
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(passport.get(k), dict):
            passport[k] = apply_patch(passport.get(k, {}), v)
        else:
            passport[k] = v
    return passport

def _to_v2_passport(raw: Dict[str, Any]):
    from ingro_dfm.core_schema.migration_v1_to_v2 import migrate_v1_to_v2
    from ingro_dfm.core_schema.part_passport import PartPassport

    if str(raw.get("passport_version")) == "2.0" and "elements" in raw:
        return PartPassport.model_validate(raw)
    return migrate_v1_to_v2(raw)


def main():
    parser = argparse.ArgumentParser(description="Simple passport editor")
    parser.add_argument("passport", type=str, help="Path to passport JSON file")
    parser.add_argument("--patch", type=str, help="JSON string with fields to update")
    parser.add_argument("--v2", action="store_true", help="Run Master Spec v2.0 calculation & DFM summary")
    parser.add_argument("--cnc", action="store_true", help="Use CNC equipment mode in v2 calculation")
    parser.add_argument("--gui", action="store_true", help="Launch Tkinter Ingro v2.0 Inspector window")
    parser.add_argument("--export-dir", type=Path, default=None, help="Export v2 reports (JSON, XLSX, PDF) to directory")
    args = parser.parse_args()

    p_path = Path(args.passport)
    passport = load_passport(p_path)
    if args.patch:
        patch = json.loads(args.patch)
        passport = apply_patch(passport, patch)
        # Write back the updated passport.
        with p_path.open("w", encoding="utf-8") as f:
            json.dump(passport, f, ensure_ascii=False, indent=2)
        print("Passport updated and saved.")

    if args.v2 or args.gui or args.export_dir is not None:
        from ingro_dfm.dfm_engine.cost_drivers_analyzer import analyze_cost_drivers
        from ingro_dfm.ui_reporting.inspector_app import IngroInspectorState
        from ingro_dfm.ui_reporting.report_exporter import export_all_reports

        v2_passport = _to_v2_passport(passport)
        state = IngroInspectorState(v2_passport, use_cnc=args.cnc)
        calc = state.calc_result
        print(
            f"[Ingro v2.0] {calc.part_name}: T_шк = {calc.hybrid_totals.t_shk_total_min:.2f} мин "
            f"({calc.hybrid_totals.t_norm_hours:.3f} н/ч) | Установов: {calc.setups_count} | "
            f"Контур1 ЦБНТ={calc.cbnt_totals.t_shk_total_min:.2f} / Контур2 Reg={calc.regression_totals.t_shk_total_min:.2f}"
        )
        if args.export_dir is not None:
            drivers = analyze_cost_drivers(calc)
            paths = export_all_reports(state.passport, calc, state.dfm_assessment, drivers, args.export_dir)
            print("Exported v2 reports:", {k: str(v) for k, v in paths.items()})
        if args.gui:
            state.launch_gui()
    elif not args.patch:
        # Pretty-print a short summary.
        ident = passport.get("identification", {})
        geo = passport.get("geometry", {})
        prod = passport.get("production", {})
        print("--- Passport Summary ---")
        print(f"Part: {ident.get('part_name', '<unknown>')} | Material: {ident.get('material_key')}")
        print(f"D_max = {geo.get('D_max_mm')} mm, L_total = {geo.get('L_total_mm')} mm")
        print(f"Batch size q = {prod.get('batch_size_q')} | Kim = {prod.get('kim_ratio')}")
        print(f"Surfaces: {len(passport.get('surfaces', []))}")

if __name__ == "__main__":
    main()

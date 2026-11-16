"""UI-панель / инспектор Ingro v2.0 (паспорт ДСЕ, дерево КТЭ со 'светофором', What-If, калибровка)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from ingro_dfm.calc_engine.hybrid_orchestrator import HybridCalculationResult, calculate_passport
from ingro_dfm.calibration.cam_dataset_loader import CalibrationSQLiteStore, CalibrationSample
from ingro_dfm.core_schema.part_passport import PMISource, PartPassport
from ingro_dfm.dfm_engine.cost_drivers_analyzer import analyze_cost_drivers
from ingro_dfm.dfm_engine.dfm_rules_kb import DFMAssessment, evaluate_dfm
from ingro_dfm.dfm_engine.what_if_simulator import simulate_parameter_change
from ingro_dfm.ui_reporting.report_exporter import export_all_reports

logger = logging.getLogger(__name__)

LIGHT_ICON = {"green": "[ЗЕЛЕН]", "yellow": "[ЖЕЛТ]", "red": "[КРАСН]"}


class IngroInspectorState:
    """Модель состояния окна плагина (отделена от Tkinter для автоматического тестирования)."""

    def __init__(
        self,
        passport: PartPassport,
        use_cnc: bool = False,
        calibration_db_path: Optional[Path] = None,
    ):
        self.passport = passport.model_copy(deep=True)
        self.use_cnc = use_cnc
        self.calibration_db_path = calibration_db_path or (
            Path(__file__).resolve().parent.parent / "database" / "calibration_samples.sqlite"
        )
        self.calc_result: HybridCalculationResult
        self.dfm_assessment: DFMAssessment
        self.recalculate()

    def recalculate(self) -> None:
        self.calc_result = calculate_passport(self.passport, use_cnc=self.use_cnc)
        self.dfm_assessment = evaluate_dfm(self.passport, self.calc_result)

    def override_element_pmi(self, element_id: str, new_ra: float, new_it: int) -> None:
        """Переопределение Ra/IT в 1 клик (снимает желтый флаг System_Default -> User_Override)."""
        target = next((e for e in self.passport.elements if e.element_id == element_id), None)
        if target is None:
            raise KeyError(f"Элемент {element_id} не найден")
        target.pmi.roughness_ra_um = float(new_ra)
        target.pmi.it_grade = int(new_it)
        target.pmi.source = PMISource.USER_OVERRIDE
        self.recalculate()

    def save_production_feedback(self, element_id: str, actual_time_min: float) -> CalibrationSample:
        """Сохраняет фактическое цеховое время технолога в SQLite calibration_samples."""
        elem = next((e for e in self.passport.elements if e.element_id == element_id), None)
        det = next((d for d in self.calc_result.elements if d.element_id == element_id), None)
        if elem is None or det is None:
            raise KeyError(f"Элемент {element_id} не найден")
        sample = CalibrationSample(
            tech_code_10=det.tech_code_10,
            S_mm2=elem.area_mm2,
            V_mm3=elem.removed_volume_mm3,
            Ra_um=elem.pmi.roughness_ra_um,
            IT_grade=elem.pmi.it_grade,
            cam_machining_time_min=float(actual_time_min),
            material_group=self.passport.material_group.value,
            source="Production_Feedback",
        )
        store = CalibrationSQLiteStore(self.calibration_db_path)
        store.add_sample(sample)
        return sample

    def launch_gui(self) -> None:
        """Запускает настольное окно Tkinter со 'светофором', What-If и экспортом."""
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk

        root = tk.Tk()
        root.title(f"ИНГРО v2.0 — {self.passport.part_name} ({self.passport.cad_source.value})")
        root.geometry("1120x680")

        # Блок 1: Паспорт ДСЕ
        hdr = ttk.LabelFrame(root, text="Паспорт ДСЕ и Сводка")
        hdr.pack(fill="x", padx=8, pady=6)
        lbl_summary = ttk.Label(hdr, text="")
        lbl_summary.pack(anchor="w", padx=8, pady=4)

        # Блок 2: Дерево КТЭ со светофором
        cols = ("light", "id", "name", "code", "ra", "it", "time_hyb", "transitions")
        tree = ttk.Treeview(root, columns=cols, show="headings", height=12)
        for c, title, w in [
            ("light", "Статус", 85),
            ("id", "ID", 75),
            ("name", "Элемент / КТЭ", 210),
            ("code", "10-уровневый код", 215),
            ("ra", "Ra", 55),
            ("it", "IT", 45),
            ("time_hyb", "Т_осн, мин", 85),
            ("transitions", "Переходы", 290),
        ]:
            tree.heading(c, text=title)
            tree.column(c, width=w)
        tree.tag_configure("green", background="#d9f2d9")
        tree.tag_configure("yellow", background="#fff3cd")
        tree.tag_configure("red", background="#f8d7da")
        tree.pack(fill="both", expand=True, padx=8, pady=4)

        # Панель действий: быстрое переопределение, What-If, Fact, Export
        ctrl = ttk.Frame(root)
        ctrl.pack(fill="x", padx=8, pady=6)
        ra_var = tk.StringVar(value="3.2")
        it_var = tk.StringVar(value="11")
        fact_var = tk.StringVar(value="2.5")

        ttk.Label(ctrl, text="Ra:").pack(side="left")
        ttk.Combobox(ctrl, textvariable=ra_var, values=["12.5", "6.3", "3.2", "1.6", "0.8", "0.4"], width=6).pack(side="left", padx=4)
        ttk.Label(ctrl, text="IT:").pack(side="left")
        ttk.Combobox(ctrl, textvariable=it_var, values=["14", "12", "11", "9", "8", "7", "6"], width=5).pack(side="left", padx=4)

        dfm_box = tk.Text(root, height=7)
        dfm_box.pack(fill="x", padx=8, pady=6)

        def refresh_view() -> None:
            r = self.calc_result
            lbl_summary.config(
                text=(
                    f"Материал: {self.passport.material_raw_string} | Заготовка: {self.passport.blank_type.value} | "
                    f"Масса дет./заг.: {self.passport.part_mass_kg:.3f}/{self.passport.blank_mass_kg:.3f} кг | "
                    f"КИМ={r.kim_ratio:.3f} | Партия q={r.batch_size_q} | "
                    f"T_шк={r.hybrid_totals.t_shk_total_min:.2f} мин ({r.hybrid_totals.t_norm_hours:.3f} н/ч)"
                )
            )
            tree.delete(*tree.get_children())
            for el in r.elements:
                tl = self.dfm_assessment.traffic_lights.get(el.element_id)
                color = tl.color if tl else "yellow"
                tree.insert(
                    "",
                    "end",
                    iid=el.element_id,
                    tags=(color,),
                    values=(
                        LIGHT_ICON[color],
                        el.element_id,
                        el.name,
                        el.tech_code_10,
                        el.roughness_ra_um,
                        el.it_grade,
                        f"{el.hybrid_t_osn_min:.2f}",
                        ", ".join(el.assigned_transitions),
                    ),
                )
            dfm_box.delete("1.0", "end")
            for f in self.dfm_assessment.findings:
                dfm_box.insert("end", f"[{f.severity.upper()}] {f.message} -> {f.recommendation}\n")

        def on_apply_override() -> None:
            sel = tree.selection()
            if not sel:
                return
            self.override_element_pmi(sel[0], float(ra_var.get()), int(it_var.get()))
            refresh_view()

        def on_what_if() -> None:
            sel = tree.selection()
            if not sel:
                return
            wf = simulate_parameter_change(self.passport, sel[0], float(ra_var.get()), int(it_var.get()), self.use_cnc)
            messagebox.showinfo(
                "What-If симулятор",
                f"Элемент {wf.element_id}: {wf.old_t_shk_min:.2f} -> {wf.new_t_shk_min:.2f} мин "
                f"(Δ = {wf.delta_min:+.2f} мин / {wf.delta_percent:+.1f}%)\n"
                f"Исключено: {', '.join(wf.removed_transitions) or '—'}",
            )

        def on_save_fact() -> None:
            sel = tree.selection()
            if not sel:
                return
            sample = self.save_production_feedback(sel[0], float(fact_var.get()))
            messagebox.showinfo("База знаний", f"Сохранена точка {sample.tech_code_10} (T_факт={sample.cam_machining_time_min} мин)")

        def on_export() -> None:
            out_dir = filedialog.askdirectory(title="Куда сохранить ведомость (XLSX/PDF/JSON)")
            if not out_dir:
                return
            drivers = analyze_cost_drivers(self.calc_result)
            paths = export_all_reports(self.passport, self.calc_result, self.dfm_assessment, drivers, Path(out_dir))
            messagebox.showinfo("Экспорт завершен", "\n".join(f"{k}: {v}" for k, v in paths.items()))

        ttk.Button(ctrl, text="Применить Ra/IT", command=on_apply_override).pack(side="left", padx=4)
        ttk.Button(ctrl, text="What-If", command=on_what_if).pack(side="left", padx=4)
        ttk.Label(ctrl, text="T_факт:").pack(side="left", padx=(12, 2))
        ttk.Entry(ctrl, textvariable=fact_var, width=6).pack(side="left")
        ttk.Button(ctrl, text="Сохранить в БЗ", command=on_save_fact).pack(side="left", padx=4)
        ttk.Button(ctrl, text="Экспорт XLSX/PDF/JSON", command=on_export).pack(side="right", padx=4)

        refresh_view()
        root.mainloop()


__all__ = ["IngroInspectorState", "LIGHT_ICON"]

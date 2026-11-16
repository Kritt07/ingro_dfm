"""Экспорт расчетной ведомости в форматы JSON, XLSX (openpyxl) и PDF (fpdf2) (§8.2 ТЗ)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List

from fpdf import FPDF
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from ingro_dfm.calc_engine.hybrid_orchestrator import HybridCalculationResult
from ingro_dfm.core_schema.part_passport import PartPassport
from ingro_dfm.dfm_engine.cost_drivers_analyzer import CostDriverItem
from ingro_dfm.dfm_engine.dfm_rules_kb import DFMAssessment

logger = logging.getLogger(__name__)


def export_json(
    passport: PartPassport,
    calc: HybridCalculationResult,
    dfm: DFMAssessment,
    drivers: List[CostDriverItem],
    out_path: Path,
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "passport": passport.model_dump(mode="json"),
        "calculation": calc.model_dump(mode="json"),
        "dfm_assessment": dfm.model_dump(mode="json"),
        "cost_drivers": [d.model_dump(mode="json") for d in drivers],
    }
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    logger.info("Экспортирован JSON-отчет: %s", out_path)
    return out_path


def export_xlsx(
    passport: PartPassport,
    calc: HybridCalculationResult,
    dfm: DFMAssessment,
    drivers: List[CostDriverItem],
    out_path: Path,
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    header_fill = PatternFill("solid", fgColor="1E3A5F")
    header_font = Font(bold=True, color="FFFFFF")
    bold_font = Font(bold=True)
    tl_fills = {
        "green": PatternFill("solid", fgColor="C6EFCE"),
        "yellow": PatternFill("solid", fgColor="FFEB9C"),
        "red": PatternFill("solid", fgColor="FFC7CE"),
    }

    # --- Лист 1: Паспорт ДСЕ и Сводка ---
    ws1 = wb.active
    ws1.title = "1_Паспорт_и_Сводка"
    rows1 = [
        ("Показатель", "Значение", "Примечание"),
        ("Идентификатор / Обозначение", f"{passport.part_id} — {passport.part_name}", f"CAD: {passport.cad_source.value}"),
        ("Тип детали", "Тело вращения" if passport.is_rotational_part else "Корпусная / призматическая", ""),
        ("Материал", passport.material_raw_string, f"Группа: {passport.material_group.value}, k_мат={passport.k_mat_coeff}"),
        ("Заготовка", passport.blank_type.value, f"ТО: {'Да' if passport.has_heat_treatment else 'Нет'}, Твердость: {passport.hardness_hb_or_hrc or '—'}"),
        ("Масса детали / заготовки, кг", f"{passport.part_mass_kg:.3f} / {passport.blank_mass_kg:.3f}", f"КИМ = {calc.kim_ratio:.4f}"),
        ("Удаляемый объем V_срез, мм3", round(passport.total_removed_volume_mm3, 1), f"V_дет={passport.part_volume_mm3:.1f}, V_заг={passport.blank_volume_mm3:.1f}"),
        ("Партия q / Серийность", f"{passport.batch_size_q} ({passport.production_type.value})", f"Число установов: {calc.setups_count}"),
        ("Т_шк ИТОГО (Гибрид), мин", calc.hybrid_totals.t_shk_total_min, f"{calc.hybrid_totals.t_norm_hours:.4f} н/ч"),
        ("Т_шк Контур 1 (ЦБНТ / ОУНВ), мин", calc.cbnt_totals.t_shk_total_min, f"{calc.cbnt_totals.t_norm_hours:.4f} н/ч"),
        ("Т_шк Контур 2 (MRR + Регрессия), мин", calc.regression_totals.t_shk_total_min, f"Расхождение контуров: {calc.contours_diff_percent:.1f}%"),
        ("Структура Т (Гибрид), мин", f"Tосн={calc.hybrid_totals.t_osn_total_min}, Tву={calc.hybrid_totals.t_vu_total_min}, Tвп={calc.hybrid_totals.t_vp_total_min}", f"Tшт={calc.hybrid_totals.t_sht_total_min}, ΣTпз={calc.hybrid_totals.t_pz_total_min}"),
        ("Статус DFM", "ТЕХНОЛОГИЧНА" if dfm.is_manufacturable else "КРИТИЧЕСКИЕ НАРУШЕНИЯ", f"Потенциал снижения: {dfm.total_potential_savings_min:.2f} мин"),
    ]
    for r_idx, row in enumerate(rows1, start=1):
        ws1.append(list(row))
        if r_idx == 1:
            for c in range(1, 4):
                ws1.cell(r_idx, c).fill = header_fill
                ws1.cell(r_idx, c).font = header_font
    ws1.column_dimensions["A"].width = 36
    ws1.column_dimensions["B"].width = 44
    ws1.column_dimensions["C"].width = 48

    # --- Лист 2: Операции ---
    ws2 = wb.create_sheet("2_Операции")
    headers2 = [
        "Установ №", "Операция", "Ось", "Крепление", "Станок", "Инстр.",
        "Tосн ЦБНТ", "Tосн Регр.", "Tосн Итог", "Tву", "Tвп", "Tоп",
        "Kтшт", "Tшт", "Tпз", "Tшк, мин", "Н/ч"
    ]
    ws2.append(headers2)
    for c in range(1, len(headers2) + 1):
        ws2.cell(1, c).fill = header_fill
        ws2.cell(1, c).font = header_font
    for op in calc.operations:
        ws2.append([
            op.setup_id, op.operation_name, op.setup_direction, op.clamping_type,
            op.machine_type, op.tools_count, op.t_osn_cbnt_min, op.t_osn_reg_min,
            op.t_osn_hybrid_min, op.t_vu_min, op.t_vp_min, op.t_op_min,
            op.k_tsht, op.t_sht_min, op.t_pz_min, op.t_shk_min, op.t_norm_hours,
        ])
    ws2.column_dimensions["B"].width = 32

    # --- Лист 3: Элементы и КТЭ ---
    ws3 = wb.create_sheet("3_Элементы_КТЭ")
    headers3 = [
        "Светофор", "ID", "Наименование", "10-уровневый код", "Установ",
        "Ra, мкм", "IT", "PMI источник", "Назначенные переходы",
        "Карты ЦБНТ", "Tосн ЦБНТ", "Tчерн MRR", "Tчист Регр.", "Tосн Регр.", "Tосн Гибрид", "t_изм"
    ]
    ws3.append(headers3)
    for c in range(1, len(headers3) + 1):
        ws3.cell(1, c).fill = header_fill
        ws3.cell(1, c).font = header_font
    for r_i, el in enumerate(calc.elements, start=2):
        tl = dfm.traffic_lights.get(el.element_id)
        color = tl.color if tl else "yellow"
        ws3.append([
            color.upper(), el.element_id, el.name, el.tech_code_10, el.setup_direction,
            el.roughness_ra_um, el.it_grade, el.pmi_source, ", ".join(el.assigned_transitions),
            ", ".join(el.cbnt_cards) or "—", el.cbnt_t_osn_min, el.reg_t_rough_mrr_min,
            el.reg_t_finish_min, el.reg_t_osn_min, el.hybrid_t_osn_min, el.t_vp_measure_min,
        ])
        cell = ws3.cell(r_i, 1)
        cell.fill = tl_fills.get(color, tl_fills["yellow"])
        cell.font = bold_font
        cell.alignment = Alignment(horizontal="center")
    ws3.column_dimensions["C"].width = 28
    ws3.column_dimensions["D"].width = 34
    ws3.column_dimensions["I"].width = 42
    ws3.column_dimensions["J"].width = 30

    # --- Лист 4: DFM и Cost Drivers ---
    ws4 = wb.create_sheet("4_DFM_и_Drivers")
    ws4.append(["DFM Правило", "Важность", "Элемент", "Замечание", "Рекомендация", "Влияние, мин"])
    for c in range(1, 7):
        ws4.cell(1, c).fill = header_fill
        ws4.cell(1, c).font = header_font
    for f in dfm.findings:
        ws4.append([f.rule_id, f.severity.upper(), f.element_id or "—", f.message, f.recommendation, f.estimated_impact_min])

    ws4.append([])
    ws4.append(["Ранг", "Элемент", "10-код", "Tосн+изм, мин", "Доля Tоп, %", "Драйвер"])
    hdr_row = ws4.max_row
    for c in range(1, 7):
        ws4.cell(hdr_row, c).fill = header_fill
        ws4.cell(hdr_row, c).font = header_font
    for d in drivers:
        ws4.append([d.rank, d.name, d.tech_code_10, d.total_element_min, d.share_of_t_op_percent, "ДА" if d.is_major_driver else "—"])
    ws4.column_dimensions["D"].width = 48
    ws4.column_dimensions["E"].width = 46

    wb.save(out_path)
    logger.info("Экспортирован XLSX-отчет: %s", out_path)
    return out_path


def _configure_pdf_font(pdf: FPDF) -> tuple[str, bool]:
    """Подключает системный кириллический шрифт Arial/DejaVu для PDF."""
    candidates = [
        (Path(r"C:\Windows\Fonts\arial.ttf"), Path(r"C:\Windows\Fonts\arialbd.ttf")),
        (Path(r"C:\Windows\Fonts\DejaVuSans.ttf"), Path(r"C:\Windows\Fonts\DejaVuSans-Bold.ttf")),
    ]
    for reg, bold in candidates:
        if reg.is_file():
            pdf.add_font("IngroFont", "", str(reg))
            pdf.add_font("IngroFont", "B", str(bold if bold.is_file() else reg))
            return "IngroFont", True
    return "Helvetica", False


def _pdf_safe(txt: str, unicode_ready: bool) -> str:
    if unicode_ready:
        return txt
    return txt.encode("latin-1", "replace").decode("latin-1")


def export_pdf(
    passport: PartPassport,
    calc: HybridCalculationResult,
    dfm: DFMAssessment,
    drivers: List[CostDriverItem],
    out_path: Path,
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    font_name, unicode_ok = _configure_pdf_font(pdf)

    def put_line(text: str, size: int = 9, bold: bool = False, h: float = 5.5) -> None:
        pdf.set_font(font_name, "B" if bold else "", size)
        pdf.multi_cell(0, h, _pdf_safe(text, unicode_ok), new_x="LMARGIN", new_y="NEXT")

    pdf.add_page()
    put_line(f"ИНГРО v2.0 — РАСЧЕТНАЯ ВЕДОМОСТЬ ТРУДОЕМКОСТИ И DFM-АНАЛИЗА", size=14, bold=True, h=8)
    put_line(
        f"Деталь: {passport.part_name} ({passport.part_id}) | CAD: {passport.cad_source.value} | "
        f"Материал: {passport.material_raw_string} ({passport.material_group.value})",
        size=10,
    )
    put_line(
        f"Заготовка: {passport.blank_type.value} | Масса дет./заг.: {passport.part_mass_kg:.3f} / {passport.blank_mass_kg:.3f} кг | "
        f"КИМ = {calc.kim_ratio:.3f} | Партия q = {passport.batch_size_q}",
        size=10,
    )
    put_line(
        f"ИТОГО Т_шк (Гибрид): {calc.hybrid_totals.t_shk_total_min:.2f} мин ({calc.hybrid_totals.t_norm_hours:.4f} н/ч) | "
        f"ЦБНТ Контур 1: {calc.cbnt_totals.t_shk_total_min:.2f} мин | "
        f"MRR+Регрессия Контур 2: {calc.regression_totals.t_shk_total_min:.2f} мин",
        size=10,
        bold=True,
        h=7,
    )

    put_line("1. Сводка по технологическим операциям (установам):", size=11, bold=True, h=7)
    for op in calc.operations:
        put_line(
            f"  Установ {op.setup_id} | {op.operation_name} | {op.clamping_type} | "
            f"Tосн={op.t_osn_hybrid_min:.2f}, Tву={op.t_vu_min:.2f}, Tвп={op.t_vp_min:.2f}, "
            f"Tшт={op.t_sht_min:.2f}, Tпз={op.t_pz_min:.1f} -> Tшк={op.t_shk_min:.2f} мин ({op.t_norm_hours:.3f} н/ч)",
            size=8.5,
            h=5.0,
        )

    put_line("2. Пошаговая расшифровка КТЭ и граней:", size=11, bold=True, h=7)
    for el in calc.elements:
        tl = dfm.traffic_lights.get(el.element_id)
        color = tl.color.upper() if tl else "YELLOW"
        put_line(
            f"  [{color}] {el.element_id} | {el.tech_code_10} | Ra={el.roughness_ra_um}, IT{el.it_grade} | "
            f"Переходы: {', '.join(el.assigned_transitions)} | Карты: {', '.join(el.cbnt_cards) or 'MRR'} | "
            f"Tосн={el.hybrid_t_osn_min:.2f} мин (ЦБНТ={el.cbnt_t_osn_min:.2f}, Регр={el.reg_t_osn_min:.2f})",
            size=8.0,
            h=4.6,
        )

    put_line("3. Экспертные замечания DFM и драйверы трудоемкости:", size=11, bold=True, h=7)
    if not dfm.findings:
        put_line("  Критичных замечаний и нарушений DFM не выявлено.", size=9)
    for f in dfm.findings:
        put_line(f"  [{f.severity.upper()}] {f.message} -> {f.recommendation} (экономия ≈ {f.estimated_impact_min:.2f} мин)", size=8.5, h=4.8)

    if drivers:
        top_str = "; ".join(f"#{d.rank} {d.element_id} ({d.share_of_t_op_percent:.1f}%)" for d in drivers[:5])
        put_line(f"Топ Cost Drivers: {top_str}", size=8.5, bold=True, h=6)

    pdf.output(str(out_path))
    logger.info("Экспортирован PDF-отчет: %s", out_path)
    return out_path


def export_all_reports(
    passport: PartPassport,
    calc: HybridCalculationResult,
    dfm: DFMAssessment,
    drivers: List[CostDriverItem],
    out_dir: Path,
    stem: str = "ingro_report",
) -> Dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return {
        "json": export_json(passport, calc, dfm, drivers, out_dir / f"{stem}.json"),
        "xlsx": export_xlsx(passport, calc, dfm, drivers, out_dir / f"{stem}.xlsx"),
        "pdf": export_pdf(passport, calc, dfm, drivers, out_dir / f"{stem}.pdf"),
    }


__all__ = ["export_json", "export_xlsx", "export_pdf", "export_all_reports"]

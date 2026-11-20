from pathlib import Path
from docx import Document

from norm_importer.header_parser import extract_formula, parse_card_header
from norm_importer.office_parser import parse_office_file


def test_parse_card_header_full_ounv_metadata():
    """Проверка извлечения всех атрибутов шапки из эталонной карты ОУНВ (Приложение А ТЗ)."""
    lines = [
        "Карта 04. Неполное штучное время. Сверление отверстий, Rz80, 14...12 квалитет",
        "Тип производства: Единичное и мелкосерийное",
        "Оборудование: Вертикально- и радиально-сверлильные станки",
        "Обрабатываемый материал: Чугун серый, HB 1.76-2.15 ГПа",
        "Материал режущей части инструмента: Р6М5",
        "Формула расчета: T = (Ttbl + Tvid) * Ktch * Kkotv * Kgest",
    ]

    parsed = parse_card_header(lines, fallback_stem="OUNV_MPC1", card_index=4)

    assert parsed.card_id == "OUNV_MPC1_CARD_04"
    assert "Карта 04" in parsed.card_title
    assert parsed.calculation_formula == "(Ttbl + Tvid) * Ktch * Kkotv * Kgest"
    assert parsed.result_unit == "min"

    app_cond = parsed.applicability
    assert app_cond.operation_type == "Сверление"
    assert app_cond.production_type == "Единичное и мелкосерийное"
    assert "Чугун серый" in (app_cond.material_group or "")
    assert "сверлильные станки" in (app_cond.equipment_filter or "").lower()
    assert app_cond.tool_material == "Р6М5"
    assert app_cond.extra_params["roughness_rz"] == "80"
    assert app_cond.extra_params["it_grade"] == "14...12"


def test_extract_formula_variations():
    """Проверка нормализации формул с разными символами умножения и локалью."""
    assert extract_formula(["T_sht = (t_o + t_v * K1v) × 1,08"]) == "(t_o + t_v * K1v) * 1.08"
    assert extract_formula(["Без формулы в тексте"]) == "Ttbl"


def test_office_parser_uses_header_parser(tmp_path: Path):
    """Интеграционный тест: проверка извлечения Ra, квалитета и инструмента из .docx."""
    docx_path = tmp_path / "tok2003_karta43.docx"
    doc = Document()
    doc.add_paragraph("Карта 43. Точение чистовое, Ra 2,5, 9...8 квалитет, 3<L/D<=10")
    doc.add_paragraph("Материал: Сталь 170...210 HB, резец Т15К6")
    doc.add_paragraph("T = Ttbl * Ktv")

    table = doc.add_table(rows=3, cols=3)
    table.cell(0, 0).text = "Диаметр D, мм"
    table.cell(0, 1).text = "25"
    table.cell(0, 2).text = "50"
    table.cell(1, 0).text = "20"
    table.cell(1, 1).text = "0,85"
    table.cell(1, 2).text = "0,90"
    table.cell(2, 0).text = "30"
    table.cell(2, 1).text = "0,92"
    table.cell(2, 2).text = "0,97"

    doc.save(str(docx_path))

    result = parse_office_file(docx_path)
    card = result.cards[0]

    assert card.card_id == "TOK2003_KARTA43_CARD_43"
    assert card.applicability_conditions.operation_type == "Точение"
    assert card.applicability_conditions.tool_material == "Т15К6"
    assert card.applicability_conditions.extra_params["roughness_ra"] == "2.5"
    assert card.applicability_conditions.extra_params["it_grade"] == "9...8"
    assert card.calculation_formula == "Ttbl * Ktv"

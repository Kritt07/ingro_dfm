from zipfile import ZipFile
from normdoc2json.spreadsheets import extract_spreadsheet
from norm_importer.cli import _parse_spreadsheet_file


def test_ods_to_json(tmp_path):
    path = tmp_path / "sample.ods"
    rows = [["D", "15", "30"], ["6", "0.28", "0"], ["12", "0.45", "0.88"]]
    xml = '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:spreadsheet><table:table table:name="Test">'
    for row in rows:
        xml += "<table:table-row>" + "".join('<table:table-cell office:value-type="string"><text:p>' + v + '</text:p></table:table-cell>' for v in row) + "</table:table-row>"
    xml += "</table:table></office:spreadsheet></office:body></office:document-content>"
    with ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
        z.writestr("content.xml", xml)
    assert extract_spreadsheet(path).sheets[0].values == rows
    doc = _parse_spreadsheet_file(path)
    assert doc.cards[0].table_grid.values_matrix == [[0.28, 0], [0.45, 0.88]]
    assert 'ods' in doc.model_dump_json()


def test_typed_dates_and_times_without_display_text(tmp_path):
    from datetime import datetime
    path = tmp_path / "dates.ods"
    xml = '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"><office:body><office:spreadsheet><table:table table:name="Dates"><table:table-row><table:table-cell office:value-type="date" office:date-value="2026-11-25"/><table:table-cell office:value-type="time" office:time-value="PT1H30M"/></table:table-row></table:table></office:spreadsheet></office:body></office:document-content>'
    with ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
        z.writestr("content.xml", xml)
    result = extract_spreadsheet(path)
    assert result.sheets[0].values == [["2026-11-25", "PT1H30M"]]
    assert not result.warnings

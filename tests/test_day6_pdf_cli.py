import json
from pathlib import Path
import pytest
from typer.testing import CliRunner
from norm_importer.cli import app


@pytest.mark.parametrize("name", ["ruled", "borderless"])
def test_pdf_cli_values(name, tmp_path):
    output = tmp_path / "out.json"
    source = Path(__file__).parent / "fixtures" / "pdf_tables" / f"{name}.pdf"
    result = CliRunner().invoke(app, ["-i", str(source), "-o", str(output)])
    assert result.exit_code == 0, result.output
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["cards"][0]["table_grid"]["values_matrix"] == [[0.28, None], [0, 0.88]]
    assert data["source_metadata"]["extraction_method"] == "normdoc2json.pdf"

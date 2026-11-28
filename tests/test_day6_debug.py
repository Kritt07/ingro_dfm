from norm_importer.cli import collect_input_files


def test_debug_outputs_do_not_change_batch(tmp_path):
    source = tmp_path / "scan.png"
    source.touch()
    before = collect_input_files(tmp_path)
    debug = tmp_path / "scan.png.debug"
    debug.mkdir()
    (debug / "page.png").touch()
    assert collect_input_files(tmp_path) == before == [source]

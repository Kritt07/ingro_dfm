"""Проверить контракт с grid_mapper из указанной локальной Git-ревизии."""
import subprocess
import sys
import time
from pathlib import Path
from normdoc2json import extract_pdf
from norm_importer.schema import TableGrid

revision = sys.argv[1] if len(sys.argv) > 1 else 'origin/day3_programmer2'
source = subprocess.check_output(['git', 'show', revision+':norm_importer/grid_mapper.py']).decode('utf-8')
namespace = {'__name__': 'day3_grid_mapper_check'}
exec(compile(source, revision+':grid_mapper.py', 'exec'), namespace)
for path in (Path(__file__).parent/'fixtures'/'pdf_tables').glob('*.pdf'):
    started = time.perf_counter()
    extraction = extract_pdf(path)
    for page in extraction.pages:
        for table in page.tables:
            grid, warnings = namespace['map_raw_grid_to_table_grid'](table.values)
            validated = TableGrid.model_validate_json(grid.model_dump_json())
            assert validated.rows_range == [6, 12]
            assert validated.cols_range == [15, 30]
            assert validated.values_matrix == [[0.28, None], [0.0, 0.88]]
    print(path.name, 'OK', round(time.perf_counter()-started, 3), 'seconds')

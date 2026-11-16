"""Загрузка CAM-выгрузок и SQLite-хранилище фактических производственных точек калибровки."""

from __future__ import annotations

import csv
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from openpyxl import load_workbook
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class CalibrationSample(BaseModel):
    tech_code_10: str
    S_mm2: float = Field(..., gt=0)
    V_mm3: float = Field(default=0.0, ge=0)
    Ra_um: float = Field(..., gt=0)
    IT_grade: int = Field(..., ge=1, le=17)
    cam_machining_time_min: float = Field(..., gt=0)
    material_group: str = "ST_Carbon"
    source: str = "CAM"
    recorded_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def load_cam_csv(path: Path) -> List[CalibrationSample]:
    """Импортирует выборку из CSV с колонками tech_code_10, S_mm2, V_mm3, Ra_um, IT_grade, cam_machining_time_min."""
    samples: List[CalibrationSample] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            samples.append(
                CalibrationSample(
                    tech_code_10=str(row["tech_code_10"]).strip(),
                    S_mm2=float(row["S_mm2"]),
                    V_mm3=float(row.get("V_mm3") or 0.0),
                    Ra_um=float(row["Ra_um"]),
                    IT_grade=int(float(row["IT_grade"])),
                    cam_machining_time_min=float(row["cam_machining_time_min"]),
                    material_group=str(row.get("material_group") or "ST_Carbon"),
                    source="CAM_CSV",
                )
            )
    logger.info("Загружено %d CAM-точек из CSV %s", len(samples), path)
    return samples


def load_cam_xlsx(path: Path) -> List[CalibrationSample]:
    """Импортирует выборку из Excel XLSX."""
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    samples: List[CalibrationSample] = []
    for raw_row in rows[1:]:
        if not any(raw_row):
            continue
        rec = dict(zip(headers, raw_row))
        samples.append(
            CalibrationSample(
                tech_code_10=str(rec["tech_code_10"]).strip(),
                S_mm2=float(rec["S_mm2"]),
                V_mm3=float(rec.get("V_mm3") or 0.0),
                Ra_um=float(rec["Ra_um"]),
                IT_grade=int(float(rec["IT_grade"])),
                cam_machining_time_min=float(rec["cam_machining_time_min"]),
                material_group=str(rec.get("material_group") or "ST_Carbon"),
                source="CAM_XLSX",
            )
        )
    logger.info("Загружено %d CAM-точек из XLSX %s", len(samples), path)
    return samples


def load_cam_json(path: Path) -> List[CalibrationSample]:
    """Импортирует выборку из JSON-массива."""
    with path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return [CalibrationSample.model_validate(item) for item in raw]


def load_cam_dataset(path: Path) -> List[CalibrationSample]:
    ext = path.suffix.lower()
    if ext == ".csv":
        return load_cam_csv(path)
    if ext in (".xlsx", ".xlsm"):
        return load_cam_xlsx(path)
    if ext == ".json":
        return load_cam_json(path)
    raise ValueError(f"Неподдерживаемый формат файла CAM-выборки: {path}")


class CalibrationSQLiteStore:
    """SQLite таблица calibration_samples для Production Feedback и CAM-экспериментов."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS calibration_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tech_code_10 TEXT NOT NULL,
                    S_mm2 REAL NOT NULL,
                    V_mm3 REAL NOT NULL,
                    Ra_um REAL NOT NULL,
                    IT_grade INTEGER NOT NULL,
                    cam_machining_time_min REAL NOT NULL,
                    material_group TEXT NOT NULL DEFAULT 'ST_Carbon',
                    source TEXT NOT NULL DEFAULT 'Production_Feedback',
                    recorded_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def add_sample(self, sample: CalibrationSample) -> int:
        return self.add_samples([sample])

    def add_samples(self, samples: List[CalibrationSample]) -> int:
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                """
                INSERT INTO calibration_samples
                (tech_code_10, S_mm2, V_mm3, Ra_um, IT_grade, cam_machining_time_min, material_group, source, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        s.tech_code_10,
                        s.S_mm2,
                        s.V_mm3,
                        s.Ra_um,
                        s.IT_grade,
                        s.cam_machining_time_min,
                        s.material_group,
                        s.source,
                        s.recorded_at,
                    )
                    for s in samples
                ],
            )
            conn.commit()
        return len(samples)

    def fetch_samples(self, key_prefix: Optional[str] = None) -> List[CalibrationSample]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if key_prefix:
                rows = conn.execute(
                    "SELECT * FROM calibration_samples WHERE tech_code_10 LIKE ?",
                    (f"%{key_prefix}%",),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM calibration_samples").fetchall()
        return [CalibrationSample(**dict(r)) for r in rows]


__all__ = [
    "CalibrationSample",
    "load_cam_csv",
    "load_cam_xlsx",
    "load_cam_json",
    "load_cam_dataset",
    "CalibrationSQLiteStore",
]

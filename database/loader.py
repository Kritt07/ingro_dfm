"""Загрузчик справочников и базы знаний ИнГРО v2.0."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DATABASE_DIR = Path(__file__).resolve().parent
CBNT_CARDS_DIR = DATABASE_DIR / "cbnt_cards"
LEGACY_DATA_DIR = PACKAGE_ROOT / "data"


def _resolve_card_path(filename: str) -> Path:
    primary = CBNT_CARDS_DIR / filename
    if primary.is_file():
        return primary
    fallback = LEGACY_DATA_DIR / filename
    if fallback.is_file():
        return fallback
    raise FileNotFoundError(f"Файл справочника не найден: {primary} / {fallback}")


@lru_cache(maxsize=8)
def _load_json_cached(path_str: str) -> Dict[str, Any]:
    path = Path(path_str)
    logger.debug("Загрузка JSON справочника: %s", path)
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def clear_database_cache() -> None:
    """Сбрасывает кэш JSON-файлов (например, после калибровки весов)."""
    _load_json_cached.cache_clear()


def load_turning_db() -> Dict[str, Any]:
    return _load_json_cached(str(_resolve_card_path("Нормативы_токарные.json")))


def load_milling_db() -> Dict[str, Any]:
    return _load_json_cached(str(_resolve_card_path("Библиотека_фрезерные.json")))


def load_drilling_db() -> Dict[str, Any]:
    return _load_json_cached(str(_resolve_card_path("ounv_drilling_cards.json")))


def load_materials_db() -> Dict[str, Any]:
    return _load_json_cached(str(DATABASE_DIR / "materials_machinability.json"))


def load_transitions_rules() -> Dict[str, Any]:
    return _load_json_cached(str(DATABASE_DIR / "transitions_rules.json"))


def load_regression_weights(weights_path: Optional[Path] = None) -> Dict[str, Any]:
    path = weights_path or (DATABASE_DIR / "regression_weights.json")
    return _load_json_cached(str(path))


def save_regression_weights(data: Dict[str, Any], weights_path: Optional[Path] = None) -> Path:
    path = weights_path or (DATABASE_DIR / "regression_weights.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    clear_database_cache()
    logger.info("Сохранены обновленные веса регрессии (version=%s): %s", data.get("version"), path)
    return path


def resolve_material_info(material_str: str) -> Dict[str, Any]:
    """Определяет группу материала, k_mat, плотность и MRR по сырой строке из CAD."""
    db = load_materials_db()["materials"]
    norm = (material_str or "").strip().lower()

    # Прямое совпадение ключа enum
    for group_key, info in db.items():
        if group_key.lower() == norm:
            return {"material_group": group_key, **info}

    # Поиск по наиболее длинному алиасу (чтобы "12х18н10т" не перепутался со "12")
    best_match: Optional[tuple[int, str, Dict[str, Any]]] = None
    for group_key, info in db.items():
        for alias in info.get("aliases", []):
            a = alias.lower()
            if a and a in norm:
                cand = (len(a), group_key, info)
                if best_match is None or cand[0] > best_match[0]:
                    best_match = cand

    if best_match is not None:
        _, group_key, info = best_match
        return {"material_group": group_key, **info}

    # Фоллбэк — углеродистая конструкционная сталь
    default_info = db["ST_Carbon"]
    return {"material_group": "ST_Carbon", **default_info}

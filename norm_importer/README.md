# Модуль импорта нормативов (`norm_importer`)

Утилита для конвертации и распознавания нормативно-справочных документов (ЦБНТ, ОУНВ) в машиночитаемый формат JSON для базы знаний `ingro_dfm`.

## Структура модуля

* `schema.py` — контракт выходного JSON на базе Pydantic v2 (валидация размерностей матриц, нормализация запятых, прочерков и интервалов).
* `logger.py` — система логирования хода конвертации в консоль и лог-файл.
* `cli.py` — интерфейс командной строки (Typer) для одиночной и пакетной обработки файлов.

## Наборы автоматических тестов

* `test_norm_importer_schema.py` — набор автоматических тестов для schema.py. Проверяет валидацию эталонных карт, конвертацию локальных форматов чисел и перехват ошибок при несовпадении строк и столбцов.
* `test_norm_importer_cli.py` — набор автоматических тестов для cli.py. Проверяет запуск утилиты на одиночных файлах, пакетную обработку директорий и корректность кодов возврата в строгом режиме --strict.

## Установка зависимостей

```bash
python -m pip install pydantic typer pytest
```

## Запуск утилиты (CLI)

Конвертация одного файла:
```bash
python -m norm_importer.cli --input path/to/doc.pdf --output path/to/result.json
```

Пакетная конвертация папки в строгом режиме:
```bash
python -m norm_importer.cli -i path/to/docs_dir -o path/to/out_dir --ocr-lang rus+eng --strict
```

## Запуск unit-тестов

```bash
python -m pytest -v tests/test_norm_importer_schema.py tests/test_norm_importer_cli.py
```